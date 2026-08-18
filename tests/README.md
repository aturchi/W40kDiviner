# Headless test harness

GUI-free engine tests, runnable without a display. They import the engine
from `../src` and (most of them) load roster JSON produced by ArmyFetcher.

## Configuration

- **Data source** — the tests default to the bundled **synthetic** roster in
  [`synthetic/`](synthetic/), so they run on a bare checkout with no external
  data. To run against a real ArmyFetcher tree instead, opt in explicitly:

  - `python3 tests/test_regress.py --real_data` (or `run_all.py --real_data`), or
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
Assault Intercessor Squad, Intercessor Squad, Ancient, and the test_regress.py
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
python3 tests/test_regress.py             # compare vs baseline (synthetic)
python3 tests/test_regress.py -v          # compare AND print the digest
python3 tests/test_regress.py --real_data # same, against the real fixture
python3 tests/test_regress.py --complete  # probe EVERY enabled ability
python3 tests/test_regress.py --save      # (re)write this baseline
python3 tests/make_regress_data.py        # rebuild the real fixture
```

`test_kwmatch.py`, `test_armyload.py`, `test_damage_modifiers.py`,
`test_extra_abilities.py`, `test_extra_effects.py` and `test_profile_diff.py`
use no external data. The roster-reading tests default to the synthetic roster
and switch to the real ArmyFetcher tree with `--real_data` (or the env flags
above). **`test_regress.py` is the exception**: under `--real_data` it reads
its own committed fixture in `regress_data/`, not the ArmyFetcher tree — see
below.

## The tests

- `test_regress.py` — the whole engine reduced to a deterministic digest and
  compared against a saved baseline. Sections: `## damage` (a fixed table of
  attacker/defender pairs, ranged and melee, per weapon Attacks / Wounds /
  Damage / Damage-net), `## profiles` (every distinct defensive profile),
  `## flags` (the context flags, one at a time), `## selection` (which weapons
  the attack setup keeps or greys out), `## attach` (leader/support attachment
  and the damage it moves) and `## abilities` (per-ability damage delta).
  `--save` (re)writes the baseline; a mismatch prints a unified diff and exits
  non-zero. `-v` also prints the digest alongside the verdict. Run `--save`
  whenever an intended change alters the numbers, then commit the baseline.

  *Ability probing.* Each ability is isolated — the unit is analysed with every
  ability disabled, then with only that one enabled — against a matrix of probe
  units defined in [`regress_probes.py`](regress_probes.py): defenders spanning
  light infantry, armoured elite with invuln + FNP, vehicle, monster, flyer and
  an over-keyworded colossus (TITANIC / TOWERING / FORTIFICATION), and attackers
  spanning volume fire, a high-AP high-Damage shot with Devastating Wounds, and
  a PSYCHIC weapon. Without that spread most abilities look dead when they are
  merely untargeted. An ability that only works on a **combined** unit
  (`leader_effects`, one shared with the unit, or one gated on `leaderAttached`)
  is probed with the leader or support actually joined. Abilities that move no
  number anywhere are listed under `## abilities inert`, which doubles as a
  coverage report for the ability-conversion work.

  *Scope.* By default the ability section is **curated**: one representative per
  distinct mechanic, restricted to the effect types whose maths is most delicate
  (`regress_probes.CRITICAL_EFFECTS`). `--complete` probes every enabled ability
  and uses its own baseline. Four baselines in all:
  `regress_baseline_{real,synthetic}[_complete].txt`.

  *Data.* Unlike the other tests, `--real_data` here reads the committed fixture
  in `regress_data/`, compiled from the curated rosters in `../rosters/` by
  [`make_regress_data.py`](make_regress_data.py). The ArmyFetcher tree carries
  only inert ability placeholders, so it can test nothing of the above; the live
  `rosters/` tree does carry working abilities but changes as that work
  proceeds, which would break the baseline for reasons unrelated to the engine.
  Compiling once and committing gives both. Rerun `make_regress_data.py` (then
  `--save`) when you want the fixture to catch up with the rosters.
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
  set-to-zero) and exact-maths vs dice-resolver parity on that chain, using the
  shared statistical tolerance. No external data.
- `test_extra_abilities.py` — ability effect/condition parsing and application.
  No external data.
- `test_profile_diff.py` — profile comparison / selective-merge logic. No
  external data.
- `test_mc_parity.py` — the permanent exact-vs-dice parity sweep: ~50
  configurations covering the hit branches, the critical branches, the mortal
  streams, the damage chain, the defensive side and the context flags. For each
  one the analytic PMF is compared with the sampled one on the **mean** and on
  the **whole distribution**. The tolerance is statistical, not a guessed
  percentage: the standard error comes from the exact variance, and
  `mc_support.SIGMA` says how many standard errors are allowed (the CDF limit is
  that same SIGMA corrected for the number of points compared). Tune
  `mc_support.SIGMA`, `TRIALS` and `SEED` in one place — every MC check in the
  suite uses them. No external data.
- `mc_support.py` — not a test: the shared Monte-Carlo helpers described above.
  Parity proves the two engines AGREE; it cannot prove either matches the rules,
  which is what the closed-form tests below are for.
- `test_critical_triggers.py`, `test_modifier_caps.py`, `test_fnp_and_mortals.py`,
  `test_indirect_fire.py`, `test_close_quarters.py`, `test_hunter_conversion.py`,
  `test_dice_x_and_overwatch.py` —
  rules-level checks with the expected values worked out **in closed form**,
  independently of the engine. No external data.
- `test_extra_effects.py` — same closed-form style, for the `generateExtras`
  family (extra hits / wounds / attacks, in the any-event and the
  critical-only form), the `psychicAttack` condition on the defender side and
  a conditional `invulnSave`. Bonus hits and bonus wounds are never critical
  and never generate extras of their own; a dice-valued X is mixed over rather
  than averaged. Cross-checked against the dice resolver. No external data.
