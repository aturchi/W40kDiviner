# W40kDiviner

A small suite of Python tools for **Warhammer 40,000 (11th edition)** that let
you build and edit army rosters, compute **exact** attack statistics (mean,
median) of one unit against another, and resolve attacks with real dice during a
game while tracking some variables.

I know that there are many such programs that do mostly the same, but this one
implements things a little differently from most programs out there that run
Monte-Carlo simulations.

All the math is **analytic**: the attack engine composes the exact probability
distribution of a shooting/fight sequence and reads medians/percentiles off the
exact CDF. No Monte Carlo is used except as a cross-check in the test suite.
**Why this? Because it's dramatically faster** than running 10000 random realizations
of the same attack and then taking the mean...

I hope it can be useful to the W40k community. Please contact me if you want to
collaborate. This program will (for sure) contain many bugs. Also there is dire
need of help in order to properly create the army rooster files. Even if you can
automatically populate stats, creating structured abilities from text descriptions
would need at least an LLM (and I wasted too much Claude AI resources on this
project to actually do this for all the armies...). So if you want to either
contribute to the code or even manually edit the roster files and share them, you
are welcome!


> **Companion tool.** Rosters are produced by
> [`ArmyFetcher/`](ArmyFetcher/README.md), a web scraper that turns the
> datasheets on Wahapedia / 40k.app into native JSON. See its own README.
> Please remember that Warhammer 40k is property of Games Workshop and you
> shouldn't use proprietary data without the owner's consent.
> Also Wahapedia and 40k.app may have policies preventing you from scraping
> their website for data. I take no responsibility over your use or abuse
> of this program.

---

## Contents

- [The four programs](#the-four-programs)
- [Requirements & install](#requirements--install)
- [Quick start](#quick-start)
- [The native JSON format](#the-native-json-format)
- [Program 1 — Profile Editor](#program-1--profile-editor)
  - [Ability reference — conditions & effects](#ability-reference--conditions--effects)
- [Program 2 — Attack Analyzer](#program-2--attack-analyzer)
- [Program 3 — Game Assistant](#program-3--game-assistant)
- [Program 4 — Join Armies (CLI)](#program-4--join-armies-cli)
- [Common UI concepts](#common-ui-concepts)
- [Keyword configuration](#keyword-configuration)
- [Building Windows executables](#building-windows-executables)
- [Tests](#tests)
- [Project layout](#project-layout)
- [Disclaimer](#disclaimer)

---

## The four programs

| Program | File | Type | Purpose |
|---|---|---|---|
| **Profile Editor** | `profile_editor.py` | GUI | Create/edit army rosters, units, models, weapons and abilities; import & save native JSON; **compare & selectively merge** a second roster (*Merge JSON*). |
| **Attack Analyzer** | `attack_analyzer.py` | GUI | Exact mean/median damage of one attacker vs one or more defenders, with full modifier context. |
| **Game Assistant** | `game_assistant.py` | GUI | In-game attack resolution with real dice rolls; per-model wound tracking and masking. |
| **Join Armies** | `join_armies.py` | CLI | Merge several units from different armies into one single army file. |

All three GUIs share the same object model (`src/unit_model.py`), the same
modifier engine (`src/modifier_engine.py`), the leader/support attachment logic
(`src/leader_core.py`), and the keyword vocabularies in `src/keywords_config.json`.

---

## Requirements & install

- **Python 3.8+** with **Tkinter** (the standard-library GUI toolkit).
  - On most Linux distros Tkinter is a separate package, e.g.
    `sudo apt install python3-tk`.
  - On Windows/macOS the official python.org installers already include it.
- **No third-party packages** are needed to run the four programs — they use
  only the standard library.
  - `ArmyFetcher/` additionally needs `requests` and `beautifulsoup4`; see its
    own README.

No installation step is required: clone the repository and run the scripts
directly.

```bash
git clone <your-repo-url>.git
cd W40kDiviner
python3 profile_editor.py      # or attack_analyzer.py / game_assistant.py
```

---

## Quick start

1. **Get a roster.** Either use
   [`ArmyFetcher`](ArmyFetcher/README.md), or open the Profile Editor and build
   one by hand. Consider that ArmyFetcher create unit's abilities which have 
   only the description. You still must edit the JSON files by hand to properly 
   create the abilities.
2. **Analyze** matchups before the game with the Attack Analyzer.
3. **Play** with the Game Assistant, which rolls the dice and helps you track wounds and other variables.

---

## The native JSON format

Schema tag: **`w40k-sim/6`**. This is the only format the GUIs and the engine
speak; it mirrors the object model 1:1 (`src/native_format.py`,
`src/unit_model.py`).

Top-level shape:

```json
{
  "format": "w40k-sim/6",
  "armies": [
    { "name": "Army/Faction name", "units": [ /* unit objects */ ] }
  ]
}
```

A **unit** carries its name, points, keywords, unit-scope abilities, the
leader/support relationships (`leadership` / `support` lists of unit names or
keywords it can attach to), `leader_effects` (abilities a leader/support applies
to the whole combined unit), and a list of **models**. Each model has its
characteristics (`M, T, Sv, W, LD, OC`, plus `invuln`, `fnp`), keywords,
abilities and **weapons** (`RNG, A, BS/WS, S, AP,
D, count`, keywords, abilities). `AP` follows the datasheet convention
(≤ 0). Characteristics may use dice notation (e.g. `"D6+1"`).

You normally never edit this JSON by hand — the Profile Editor exposes every
field.

---

## Program 1 — Profile Editor

**Run:** `python3 profile_editor.py`

A GUI to build and maintain rosters. The left pane is a tree
`army → units → models → weapons → abilities`; the right pane edits the selected
node.

**Workflow**

- **Import JSON / Save JSON** — load an existing native file, edit, save back.
  `Select army` switches between armies inside a multi-army file.
- **Tree navigation** — click a node to edit it. The editor supports two views
  of the selected node:
  - a **Quick edit** form for scalar fields (long-text fields such as
    `unit_composition`, `wargear_options` and `notes` become multi-line boxes);
  - a **JSON** view of the full node for anything the quick form doesn't cover.
- **Abilities** are edited through a dedicated ability editor
  (`src/ability_editor.py`) built on structured *effect/condition specs*
  (`src/effect_specs.py`, `src/condition_specs.py`) rather than free text, so
  they can be interpreted by the attack engine.
- **Copy/paste** of a model / weapon / ability node speeds up repetitive edits.
- **Keyword lists** are picked from the configured vocabularies
  (see [Keyword configuration](#keyword-configuration)).
- **Validation** (`src/validation.py`) flags structural problems before saving.

### Ability reference — conditions & effects

Each ability is a list of **conditions** (all must hold for it to apply) and a
single **effect**. Both are chosen from dropdowns in the ability editor and are
fully interpreted by the attack engine. No condition means that the ability
always apply. This section lists every entry available in those dropdowns and
its parameters.

Two cross-cutting notes:

- **Static vs dynamic conditions.** A condition decidable when the combat view
  is built (role, attack type, keywords, range, stationary, cover, …) gates the
  whole ability up front. A condition decidable only while rolling (a specific
  hit/wound/save value, critical, wound type) is compiled into the effect and
  honoured per die at roll time. You mix both freely; the engine sorts out when
  each is evaluated.
- **Who the ability affects.** Attacker-side effects modify *this unit's*
  attacks; defender-side effects (Feel no pain, Invulnerable save, both Damage
  effects, and the defensive half of *Ignore negative modifiers*) apply when
  *this unit is the target*. Use a **Profile role** condition when you need to
  pin an ability to one side explicitly.

#### Conditions
Those taking a *Who* parameter apply the check to the *Attacker* or the
*Defender*:

Standard conditions:

- **Profile role** — require this profile to be the *Attacker* or *Defender*.
- **Attack type** — restrict to *Melee* or *Ranged* attacks.
- **Range** — *within* or *beyond* half range.
- **Critical hit/wound** — require the hit or the wound to be a critical.
- **Attack step roll** — require a value on a chosen step (*Hit / Wound / Save*):
  a *specific / successful / failed* roll, on the *unmodified* or *modified* die,
  *or greater / or less / exactly*, versus a given value.
- **Attack characteristic** — compare an attack characteristic
  (*Strength / Attacks / AP / Damage*) against a value, on the *unmodified* or
  *modified* profile, with the usual comparison operators.
- **Remained stationary** — the *attacker* or the *defender* did not move.
- **Attacker charged** — the attacker charged this turn.
- **Keywords (only)** — require one or more keywords (comma-separated).
- **Keywords (excludes)** — exclude one or more keywords.
- **Wound type** — apply only to *Mortal* or *Normal* wounds.
- **Psychic attack** — the attacking weapon has the `PSYCHIC` keyword.
- **Target in cover** — the defender has the Benefit of Cover.
- **Below half strength** *(Who)* — the unit is Below Half-strength.
- **Below full strength** *(Who)* — the unit has lost at least one model.
- **Battle round** — compare the current battle-round number against a value.
- **Within objective range** *(Who)* — the unit is within range of an objective.
- **Leader attached** *(Who)* — the unit is being led (a CHARACTER is attached).
- **Within engagement range** *(Who)* — the unit is within Engagement Range of an
  enemy unit.

#### Effects

Standard effects:

- **Modify (relative)** — change a roll or characteristic by ±N. *Apply to* one
  of Hit/Wound/Save roll, BS, WS, AP, Damage, Attacks, Strength, M, LD, OC;
  *Operator* Add / Subtract / Improve by / Degrade by; then the value N.
- **Modify (absolute)** — set the chosen roll or characteristic to a new value.
- **Re-roll** — re-roll on Hit/Wound/Save/Damage: a *single* result, a *range*,
  or *all possible failures*, optionally limited to *once per phase*.
- **Override requirements** — set new success requirements for *Hit / Wound /
  Save*: *Always* or *Only*, optionally *on critical only* and/or *irrespective
  of modifiers*.
- **Generate extras** — extra *hits / attacks / wounds* per attack (amount N).
- **Increase weapon attacks** — change the weapon Attacks characteristic by ±N,
  optionally also applying to generated extra attacks.
- **Mortal wounds** — generate mortal wounds (N or dice notation), optionally
  *match weapon damage*, *end the attack sequence*, *no spill-over*, with an
  optional cap.
- **Feel no pain** *(defender)* — ignore each lost wound on a roll of N+.
- **Invulnerable save** *(defender)* — grant an invulnerable save of N+.
- **Damage modifier** *(defender)* — modify the Damage of each incoming attack.
  All Damage modifiers resolve in a **fixed order** regardless of how the
  abilities are declared: **(1) Set** fixes Damage to N → **(2) Multiply** by a
  factor, rounding **up** (`0.5` = halve) → **(3) Add** N (a classic “−1 damage”
  is *Add* with `-1`) → **(4)** the result is floored at **1**. Cumulative
  multipliers stack; among competing *Set* values the lowest wins.
- **Damage set to 0** *(defender)* — force each incoming attack's Damage to 0,
  **bypassing the floor at 1**. Applied after every other Damage modifier (the
  special case of step 4). No parameters.
- **Ignore negative modifiers to a roll** — ignore *negative* modifiers to the
  chosen roll (positive ones still apply). *Hit / Wound* act on this unit's
  attacks; *Save / Invuln / FNP* act when this unit defends.
- **Critical hit/wound on N+** — score a critical *hit* or *wound* on an
  unmodified N+ instead of 6 (best/lowest threshold wins).
- **Special (core weapon ability)** — a core mechanic handled natively by the
  engine: Blast, Cleave, Extra attacks, Ignore cover, Lethal hits, Devastating
  wounds, Torrent, Twin-linked, Hazardous, Precision, Lance, Indirect fire, One
  shot, Pistol, Assault, Heavy.
- **Disable mechanic** — turn off a mechanic on the target: Invulnerable save,
  Re-roll hits, Re-roll wounds, Re-roll damage, or Save (including invulnerable).
- **Set keyword** — Add or Remove a keyword on *this weapon / all weapons / this
  model / all models / the unit* (parametric keywords take their value after the
  name, e.g. `SUSTAINED HITS 2`).

### Merge JSON — compare & selectively merge a second roster

*Merge JSON* reconciles the army you have open with a **second version of the
same army** coming from another file — the same faction re-scraped later, or the
40k.app vs Wahapedia export of the same datasheets. Differences flow **from the
second file into the one you have open**, one change at a time and entirely
under your control. Nothing is decided automatically.

- **Merge JSON** (toolbar) is **disabled until a file is loaded**, then enabled.
  It asks for the second JSON and compares the **currently selected army**
  against the army with the same name in that file; if the name is missing or
  ambiguous you choose which army to compare from a list.
- A dialog opens with a colour-coded, prefixed legend (colour-blind-safe
  Okabe-Ito palette, and a text prefix so it also reads without colour):
  `= identical`, `+ new`, `− removed`, `~ modified`.

The dialog has four boxes:

1. **Units** — every unit across both files. Select **new** (green) units and
   press **Merge selected** to copy them into your army; select **removed** (red)
   units and press **Delete selected** to drop them. Selecting a single
   **modified** (blue) unit fills the two detail boxes below.
2. **Stats / flags / keywords** — the selected unit's non-ability differences:
   unit/model/weapon characteristics, flags, per-keyword additions/removals, and
   whole models or weapons added/removed. Each row is accepted individually with
   **Accept selected** (single or multi-selection) or all at once with
   **Accept all**.
3. **Abilities** — the selected unit's ability differences (unit, model, weapon
   and leader abilities), at **whole-ability** granularity: added, removed, or
   replaced. Same **Accept selected / Accept all** controls.
4. **Differences of selected modified item** (read-only inspector) — click a
   modified row, chiefly a *replaced* ability, to see its **field-level**
   differences inside (e.g. `effect.data.value: 1 → 3`). It follows your **last
   click** across the two detail boxes.

Behaviour worth knowing:

- **Case-insensitive matching.** Names are matched ignoring letter case and
  surrounding spaces at **every level** (units, models, weapons, abilities), and
  keyword / free-text differences that are *only* capitalisation or spacing are
  not reported. The two sources capitalise differently (40k.app writes keywords
  in ALL-CAPS, Wahapedia in Title-case), so this keeps the diff free of hundreds
  of false positives — e.g. `Commander In Coldstar Battlesuit` and `Commander in
  Coldstar Battlesuit` are the same unit.
- **Ability ids** are ignored while diffing (they are random per file) and
  re-stamped for global uniqueness when the merge is committed; a replaced
  ability keeps the first id so any enable/disable toggle stays stable.
- **Staging.** Accepts, merges and deletes mutate an **in-memory working copy**
  and the diff refreshes live; the window stays open so you can work in several
  passes. **Finish** applies the merged army to the loaded data; **Cancel** (or
  closing the window) discards the whole session. As everywhere else in the
  editor, **Save JSON** is what writes to disk, and **Revert changes** still
  undoes an unsaved merge.

> A **rename** is not tracked: a unit (or model/weapon/ability) whose name
> genuinely changed between the two files shows up as one *removed* + one *new*,
> not as a modification.

---

## Program 2 — Attack Analyzer

**Run:** `python3 attack_analyzer.py`

Computes **exact** statistics for **one attacker unit vs one or more defender
units** (each defender opens its own result popup, so several can be compared
side by side).

**Panels.** Each army panel is split into a small **“Leaders & Supports”** list
and the **units** list:

- Selecting a **leader** greys out the units it cannot lead.
- With a leader and a compatible unit selected, **Join** creates the
  **combined unit** (shown as `[JOINED]` in the unit list, with the
  shared abilities active). A separate **support** relationship is handled the
  same way — a unit can carry one leader **and** one support.
- Re-clicking a selected row **deselects** it.
- **Inspect** shows the full profile of the last selected unit.

**Running an analysis.** Pick the attacker and the defender(s), set the attack
context (see below), and press **Analyze**. The popup gives a **per-weapon**
damage breakdown plus totals, using the exact PMF/CDF — mean, median and
percentiles are all exact.

**Attack context / modifiers** (via the setup panel, `src/setup_panel.py`):

- combat flags — half range, attacker stationary, attacker charged, defender in
  cover, and below-half / below-full-strength states for either side;
- manual modifiers — per-roll modifiers (hit/wound/save/invuln/fnp), and
  characteristic modifiers on the weapon or on the attacker/defender model;
- **Options** — session-wide caps (roll-modifier cap, re-roll cap) enforced by
  `src/rules_config.py`;
- **Font size** — global accessibility scaling.

---

## Program 3 — Game Assistant

**Run:** `python3 game_assistant.py`

Resolves attacks with **real dice rolls** during a game.

**Workflow**

1. Load a JSON roster.
2. In the **Army setup** popup, pick the units of the two armies; running
   **points totals** are shown as you build each side.
3. During play, select an **attacker** unit and a **defender** unit in the two
   panels and press **Execute attack**. A popup lists every damaging attack and
   the mortal wounds, so you **allocate wounds to models manually** (as the game
   requires).

**Tracking aids**

- **Masking** — units, models and weapons (e.g. a `ONE SHOT` weapon) can be
  greyed out; masked entries are excluded from attack resolution. This lets you
  reflect casualties and spent one-use weapons.
- **Wounds boxes** — each model row has an editable wounds box (double-click),
  initialised to `W × model count`, so you can track remaining wounds as the
  game goes on.
- **Leaders/supports** attached to a unit are shown as one combined entry;
  masking uses a global model index and is split back to the correct part
  internally, so a joined unit tracks correctly.

---

## Program 4 — Join Armies (CLI)

**Run:**

```bash
python3 join_armies.py tau.json wolves.json -o combined.json -n "My Alliance"
```

Merge several units from different JSON files into one single army file.

- **Duplicate army names are rejected** — rename them before joining.
- After merging, every ability is re-stamped with a globally unique id so ids
  from different files can’t collide.

| Option | Meaning |
|---|---|
| `inputs...` | one or more input JSON files (positional) |
| `-o`, `--output` | output path (default `combined.json`) |
| `-n`, `--name` | name for the joined army (default `NewArmy`) |

---

## Common UI concepts

- **Search** — list widgets across the GUIs support incremental search
  (`src/search_widget.py`).
- **Inspect** — a read-only full-profile view of a unit (`src/inspect_dialog.py`).
- **Font size** — a global font-scaling dialog is available in the Analyzer and
  Game Assistant for accessibility.
- **Options / caps** — modifier and re-roll caps are set once per session and
  apply to every calculation.

---

## Keyword configuration

`keywords_config.json` holds the **unit / model / weapon keyword vocabularies**
(WH40k 11th ed. core rules + dataset). It is loaded automatically at startup and
is **editable**.
This is used only for keywords matching and validation, the code still has
hardcoded mechanics for for many of the keywords listed here.

- Search order: first next to the executable / project root, then `src/`.
- Parametric weapon keywords (`SUSTAINED HITS`, `RAPID FIRE`, `MELTA`, `ANTI`, `CLEAVE`)
  take a value typed after the name, e.g. `SUSTAINED HITS 2`.
- If the file is missing or malformed the programs still start, with empty
  vocabularies.

---

## Building Windows executables

`W40kDiviner.spec` is a **PyInstaller** spec that builds four self-contained
one-file executables (Python and all dependencies embedded):

```
ProfileEditor.exe    AttackAnalyzer.exe    GameAssistant.exe    JoinArmies.exe
```

Build (on Windows, from the `W40kDiviner` folder):

```bat
pip install pyinstaller
pyinstaller W40kDiviner.spec
```

Executables land in `dist/`. `keywords_config.json` is embedded, but a copy
placed **next to the .exe** takes precedence (user-customisable vocabularies).
Ship your roster `.json` files alongside the executables; they are loaded through
the file dialogs. UPX is disabled on purpose (compressed one-file bootloaders
trip some antivirus heuristics).

Please consider that I do now have a PC with windows, so this section is totally
untested and I just made the .spec file with Claude AI just for your convenience.
:-)

---

## Tests

A GUI-free (headless) test harness lives in `tests/`. See
[`tests/README.md`](tests/README.md). The tests exercise the engine without a
display: leader/support attachment, masking, the damage pipeline and the
dialog logic. Note that some test scripts contain **absolute paths to sample
JSON** created during development — update them to your local ArmyFetcher output
before running.

---

## Project layout

```
W40kDiviner/
├── profile_editor.py        # Program 1 (GUI)
├── attack_analyzer.py       # Program 2 (GUI)
├── game_assistant.py        # Program 3 (GUI)
├── join_armies.py           # Program 4 (CLI)
├── W40kDiviner.spec          # PyInstaller build spec (Windows)
├── src/                     # shared engine + UI modules
│   ├── native_format.py     #   native JSON schema (w40k-sim/6) I/O + migration
│   ├── unit_model.py        #   object model (units/models/weapons/abilities)
│   ├── attack_math.py       #   exact attack PMF/CDF mathematics
│   ├── attack_resolve.py    #   dice-roll resolution (game assistant)
│   ├── analyzer_core.py     #   glue: object model → attack maths
│   ├── modifier_engine.py   #   context flags & modifier application
│   ├── leader_core.py       #   leader/support attachment + masking
│   ├── rules_config.py      #   session-wide caps
│   ├── keywords_config.py   #   keyword vocabulary loader
│   ├── ability_editor.py    #   structured ability editor
│   ├── profile_diff.py      #   diff / selective-merge logic (pure; Merge JSON)
│   ├── merge_dialog.py      #   Merge JSON dialog (four-box diff & merge UI)
│   ├── effect_specs.py / condition_specs.py / spec_*.py
│   ├── editor_widgets.py / setup_panel.py / search_widget.py / ui_utils.py
│   └── … (see the folder for the full module list)
├── tests/                   # headless test harness (see tests/README.md)
└── ArmyFetcher/             # roster scraper (see ArmyFetcher/README.md)
```

---

## Disclaimer

Warhammer 40,000 and all associated names, marks and datasheet content are
trademarks of **Games Workshop Ltd.** This is an **unofficial, non-commercial
fan tool** and is not endorsed by or affiliated with Games Workshop. Roster data
scraped from third-party sites is the property of its respective owners; use it
in accordance with those sites’ terms.
