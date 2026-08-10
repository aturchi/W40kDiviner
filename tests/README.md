# Headless test harness

GUI-free engine tests, runnable without a display. They import the engine
from `../src` and (most of them) load roster JSON produced by ArmyFetcher.

## Configuration

- **Data source** — the tests default to the bundled **synthetic** roster in
  [`synthetic/`](synthetic/), so they run on a bare checkout with no external
  data. To run against a real ArmyFetcher tree instead, opt in explicitly:

  - `python3 tests/regress.py --real_data` (or `run_all.py --real_data`), or
  - set the `W40K_TEST_REAL=1` environment variable, or
  - set `W40K_TEST_DATA` to a real ArmyFetcher path.

  The real ArmyFetcher root (the folder containing `fetched_armies_40kapp/`) is
  taken from [`test_config.ini`](test_config.ini) as a path **relative to the
  repository root** (or absolute), overridable with `W40K_TEST_DATA`:

  ```ini
  [paths]
  data_dir = ArmyFetcher
  ```

  Requesting real data that is absent falls back to the synthetic roster rather
  than failing.

Both are handled by the shared helper [`testpaths.py`](testpaths.py). Tests ask
for a roster by bare name via `testpaths.roster("space-marines.json")` and stay
agnostic to the on-disk layout: the real ArmyFetcher tree keeps its
`fetched_armies_40kapp/` subdir, while the synthetic roster lives flat in
`synthetic/`. `testpaths.USING_SYNTHETIC` tells callers which source is active,
and `testpaths.set_source(real=…)` switches it at runtime.

## Synthetic roster

[`make_synthetic.py`](make_synthetic.py) generates a small stand-in roster
under `synthetic/` (`space-marines.json`, `tau-empire.json`) that the
roster-reading tests use as a fallback. It reproduces the **real role names**
the tests look up (Captain, Bladeguard Ancient, Bladeguard Veteran Squad,
Assault Intercessor Squad, Intercessor Squad, Ancient, and the regress.py
attacker/defender names) and the leader/support relationships between them;
everything else — ability names, weapon names, keywords, stat lines — is
invented (`Ability 01`, `Weapon 01`, …). It is **not** real game data, only a
structurally valid, deliberately varied stand-in.

The roster is built to span representative combat situations: light infantry vs
anti-infantry volume fire, armoured and Feel-No-Pain targets where AP and
multi-damage bite, and high-Toughness vehicles/monsters taking single big hits
— with at least one weapon carrying each common weapon keyword (Sustained Hits,
Lethal Hits, Devastating Wounds, Blast, Torrent, Rapid Fire, Melta,
Twin-linked), and both a ranged and a melee weapon on every representative
attacker.

The generator asserts every structural constraint the tests rely on (who leads
whom, who supports whom, model-group layout, non-zero ranged and melee damage,
no unsupported keywords) before writing, so the roster cannot silently drift
out of spec. Regenerate it with:

```bash
python3 tests/make_synthetic.py
```

## Running everything at once

[`run_all.py`](run_all.py) runs the engine suite and prints one comprehensive
report — a PASS / FAIL table with timings, the full output of any failing
test, and a summary line:

```bash
python3 tests/run_all.py              # run everything on synthetic data
python3 tests/run_all.py --real_data  # run everything on real ArmyFetcher data
python3 tests/run_all.py --save       # let regress.py (re)write its baseline
python3 tests/run_all.py --real_data --save   # rewrite the real baseline
python3 tests/run_all.py -v           # also stream each test's own output
python3 tests/run_all.py -k damage    # only tests whose name contains 'damage'
```

It runs each test file in its own subprocess and judges the result by the
child's exit code, so it needs **no changes to the existing tests** and is
immune to the mix of `unittest` modules and top-level `assert` scripts in the
suite. New `test_*.py` files are discovered automatically. The runner's exit
code is the number of failing tests (0 when all pass), so CI can gate on it.
`--real_data` and `--save` are forwarded to `regress.py`; `--real_data` also
selects the real source for every other roster-reading test.

Scope: `run_all.py` covers **only** the W40kDiviner engine tests in `tests/`.
`test_army_parse.py` is **excluded** — it tests the ArmyFetcher parser (a
separate component under `ArmyFetcher/` that imports its own modules), not the
engine. Run it on its own from that directory if needed.

No skipping: the roster-reading tests get their data through `testpaths`, which
defaults to the bundled synthetic roster (see above) — so the whole suite runs
on a bare checkout, and `--real_data` opts into the real tree.

## Running individual tests

From anywhere (paths are location-independent):

```bash
python3 tests/test_kwmatch.py        # no external data needed
python3 tests/test_armyload.py       # no external data needed
python3 tests/regress.py             # compare vs baseline (synthetic data)
python3 tests/regress.py -v          # compare AND print the full digest
python3 tests/regress.py --real_data # same, against the real ArmyFetcher tree
python3 tests/regress.py --save      # (re)write the baseline for this source
# one-off real data dir:
W40K_TEST_DATA=/path/to/ArmyFetcher python3 tests/regress.py --real_data
```

`test_kwmatch.py`, `test_armyload.py`, `test_damage_modifiers.py`,
`test_extra_abilities.py` and `test_profile_diff.py` use no external data. The
roster-reading tests default to the synthetic roster and switch to the real
ArmyFetcher tree with `--real_data` (or the env flags above).

## The tests

- `regress.py` — leader attachment + ranged/melee damage on the active roster,
  reduced to a deterministic digest and compared against a saved baseline
  (`regress_baseline_real.txt` / `regress_baseline_synthetic.txt`, one per
  source). `--save` (re)writes the baseline; a mismatch prints a unified diff
  and exits non-zero. `-v` also prints the full digest (per-attack damage
  results) alongside the verdict. Run `--save` once per source, and again
  whenever an intended change alters the numbers, then commit the updated
  baseline.
- `test_support.py` — `attach_support` and leader+support composition at the
  model level.
- `test_leadercore.py` — `leader_core` native-level 3-segment split/masking.
- `test_dialog_logic.py` — the two-pass leader->support join logic (no Tk).
- `test_integration.py` — end-to-end leader+support build + damage pipeline.
- `test_analyzer_logic.py` — attack-analyzer join logic via a stub panel.
- `test_joinstate.py` — the pure `ArmyJoinState` join model (incl. combo join).
- `test_twoarmy.py` — two-army join producing correct rosters.
- `test_armyload.py` — `ArmyLoadState`: join a subset, discard-on-unselect, union.
- `test_kwmatch.py` — keyword matcher (whole-entry vs word-by-word, plurals).
- `test_damage_modifiers.py` — defender Damage modifiers (set/mult/add/floor,
  set-to-zero) and exact-maths vs dice-resolver parity. No external data.
- `test_extra_abilities.py` — ability effect/condition parsing and application.
  No external data.
- `test_profile_diff.py` — profile comparison / selective-merge logic. No
  external data.
