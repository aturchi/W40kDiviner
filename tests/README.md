# Headless test harness

GUI-free engine tests, runnable without a display. They import the engine
from `../src`; the ones that need a roster read the bundled synthetic one
unless told otherwise.

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
  and the damage it moves) and `## abilities` (per-ability damage delta). Each
  weapon line also carries the wounds actually **R**emoved and, for a HAZARDOUS
  weapon, the **S**elf-damage; each pair carries the firing **ORDER** the
  heuristic chose and what it is worth.
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
- `test_modifier_signs.py` — sign conventions of the manual modifiers: the
  `modifier_engine.improving_sign` table, the measured direction of each kind
  of modifier on the analyzer, and the panel defaults/hints when tkinter is
  importable (skipped otherwise). No external data.
- `test_ability_rows.py` — the game assistant's ability rows: the `tree_ids`
  row-id grammar, the row index -> ability mapping (`leader_core`), and the
  end-to-end effect of masking a row (no Tk). No external data.
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
- `test_spec_forms.py` — the spec-driven ability forms. A CHOICE is stored as
  `{"title", "key"}` and is resolved **key-first in both directions**, so the
  wording of a spec label can be corrected without migrating every roster
  already saved with the old wording — which used to be a `KeyError` on the
  next save. The regression case is the real one: a `singleReRoll` allowance
  saved before the labels were reworded. Also asserts that every CHOICE in
  every spec has distinct titles, distinct keys and a usable default, since the
  fallbacks lean on `options[0]`. Drives the real widgets through `tkstub`.
- `tkstub.py` — not a test: an in-memory stand-in for `tkinter` /
  `tkinter.ttk`, installed by `install_if_missing()` **only** when the real
  toolkit cannot be imported, and announcing itself on stdout when it does.
  It exists because Tkinter is an optional build: without it every GUI test
  would fail for a reason unrelated to the code under test. Call it before
  importing any GUI module. `install()` forces it even where Tkinter exists,
  which is how the widget-level harnesses drive a Treeview deterministically
  with no window and no display.
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

### Rules and engine, closed form

- `test_ap_modifiers.py`, `test_incoming_modifiers.py`,
  `test_manual_modifiers.py`, `test_setkeyword_scope.py`,
  `test_single_reroll.py`, `test_hazardous.py`, `test_player_choices.py`,
  `test_structural_rules.py` — further closed-form rules checks: AP and
  incoming-damage modifiers, the manual-modifier chain, the scope a
  `setKeyword` reaches, the "re-roll one die of your choice" per activation
  (hit and wound), HAZARDOUS self-damage, the player-choice abilities, and
  the structural invariants of a roster — the last of which now also covers
  `battleRound`, the one condition that needs a number rather than a tick.
  No external data.
- `test_single_damage_reroll.py` — the DAMAGE version of that same
  once-per-activation re-roll, which is a different problem: it replaces a
  result instead of adding a die, so it is resolved by splitting on which
  attack spends it. Checks the gain against a closed form, that the totals
  stay proper distributions (the chain subtracts one sub-probability law
  from another, which is exactly where a sign error would hide), that a
  multi-dice Damage roll spends ONE re-roll between its dice, that a flat
  Damage or an already-re-rolled one warns and changes nothing, and — the
  interesting one — it MEASURES the size of the single declared
  approximation against the dice engine, so a change that makes it worse
  fails here instead of passing quietly. No external data.
- `test_kill_chain.py` — the exact models-killed / wounds-inflicted chain:
  one event at a time capped by the wounds of the model it hits, waste on a
  destroyed model, spilling mortal wounds spent last, and the firing-order
  heuristic. Cross-checked against `attack_resolve` (the dice engine), never
  against the Monte-Carlo simulator, which shares its assumptions with the
  analytic chain. No external data.
- `test_result_pmf.py` — the damage PMFs the result popup reads.
- `test_dist_stats.py` — percentiles, `P(X >= N)` and histogram binning.
- `test_reference_suggest.py` — which defensive profile is proposed as the
  reference model.
- `test_ability_selection.py` — which abilities the attack setup offers.

### The UI features, minus the widgets

Every UI feature added on top of the engine keeps its logic in a tkinter-free
module, which is what these test — the widget file is then a renderer thin
enough to read.

- `test_result_rows.py` — the result table and its CSV: the totals row does
  **not** sum its columns (means are additive, medians are not).
- `test_comparison.py` — pinned analyses, the comparison matrix, the
  `DIFFERENT` marker for pins produced under a different context, and the CSV.
- `test_audit.py` — the per-weapon audit trail: what the engine actually used,
  never recomputed downstream.
- `test_mod_presets.py` — named modifier presets, additive application.
- `test_unit_mask.py` — what a row of the analyzer's unit tree is and what
  masking it does: a masked weapon is count 0, unmasking restores the count it
  *had*, a masked ability writes the flag the engine reads, and a joined unit
  shares those objects with the plain one.
- `test_attack_log.py` — the game assistant's attack log. The central check is
  end-to-end: a weapon resolved by the real dice engine, then the log's totals
  compared with the results popup's own arithmetic by an independent route.
- `test_undo_stack.py` — undo/redo: ordering, the redo branch, the depth limit,
  the dropping of no-op changes, and that undoing a masked ability row switches
  the ability back **on** rather than merely un-greying the row.
- `test_alloc_groups.py` — the Save Rolls allocation groups (05.03): how a
  unit splits into them, which orders the rules allow, and that an order
  declared by the player survives the groups being rebuilt at the next weapon.
- `test_attack_session.py` — the weapon-by-weapon sequence: arming stops at
  the wounds, undo takes back a whole activation *including its dice*, and the
  groups and the BLAST model count are worked out again for every weapon.
- `test_deferred_saves.py` — the dice engine split in two halves, cross-checked
  against the closed-form maths by Monte Carlo. Also that the wound pool is
  taken in phases — ordinary wounds, then mortal ones — and not attack by
  attack.
- `test_session_rows.py`, `test_attack_window.py` — what the attack window
  shows, as data, and then the window over it.
- `test_hazard_close.py`, `test_hazard_view.py` — the HAZARDOUS closing step:
  which weapons owe what, where the wounds land, and the player's choice of
  target.
- `test_auto_mask.py` — the masks that follow from the table rather than from
  a gesture: a model at zero wounds, a unit with nothing standing, and both
  riding in the same undo step as the edit that implied them.
- `test_defender_models.py` — the join between the assistant's table rows and
  the combat view, checked by position **and** by name.
- `test_cheat_sheet.py` — the printable unit sheet: dice characteristics
  printed in notation and never rolled, a disabled ability printed as `[OFF]`
  rather than dropped, HTML escaping, and the analyzer CSV export being row for
  row the table on screen.
- `test_session_io.py` — the session file (rosters, flags, modifiers, presets,
  attack log) round-tripping.
- `test_hist_canvas.py`, `test_wrap_lines.py` — the two drawing helpers, run
  against a minimal `tkinter` stub installed in `sys.modules` so the geometry
  is really executed. `test_wrap_lines.py` needs the real Tkinter and is the
  one test that fails on a machine without a display — not a regression.
- `test_multislot_join.py` — joining several helpers onto one unit.
