"""Headless regression harness for W40kDiviner.

Produces a deterministic textual digest of what the engine computes on a
fixed roster, and compares it against a saved baseline, so any change in
the damage maths, the ability interpretation or the attachment logic is
caught. Sections:

  ## damage      per-weapon Attacks / Wounds / Damage / Damage(net) for a
                 fixed table of attacker-defender pairs, ranged and melee
  ## profiles    every distinct defensive profile of the pair defenders
                 (the analyzer shows one tab per profile)
  ## flags       one pair swept over the context flags, ONE AT A TIME, so
                 a change in any single context path is attributable
  ## selection   which weapons the attack setup keeps or greys out
                 (indirect fire, close quarters, HUNTER)
  ## attach      leader / support attachment, and the damage it moves
  ## abilities   per-ability damage delta against a probe matrix, each
                 ability isolated (all others disabled)

Data sources -- two, each with its own baseline, because the numbers
differ:
  * ``tests/regress_data/``  -- the REAL source: a fixture compiled from
    the curated rosters in ``rosters/`` by ``make_regress_data.py`` and
    committed here, so the baseline is stable and the suite still runs on
    a checkout without ``rosters/``. This is the one carrying working
    abilities.
  * ``tests/synthetic/``     -- the default: the invented roster built by
    ``make_synthetic.py``, structurally varied and ability-bearing but
    not real game data.

Scope -- the ability section is curated by default (one representative
per distinct mechanic, restricted to the effect types whose maths is
most delicate; see regress_probes.CRITICAL_EFFECTS) and exhaustive with
``--complete``. The two scopes have separate baselines.

Usage:
    python3 test_regress.py                  # compare (synthetic, curated)
    python3 test_regress.py -v               # compare AND print the digest
    python3 test_regress.py --real_data      # same, against the real fixture
    python3 test_regress.py --complete       # probe EVERY enabled ability
    python3 test_regress.py --save           # (re)write this baseline
    python3 test_regress.py --print          # print the digest only

Exit code: 0 == digest matches the baseline; 1 == mismatch (a unified
diff is printed); 2 == baseline missing (run --save once to create it).
"""
import argparse
import copy
import difflib
import hashlib
import json
import os
import sys

import testpaths                        # sets up sys.path to the engine src/
import regress_probes as rp

import analyzer_core as ac
import unit_model as um


_HERE = os.path.dirname(os.path.abspath(__file__))

# The two data sources this harness reads. Both live inside tests/: the
# real one is a committed fixture, not the live rosters/ tree.
REAL_DIR = os.path.join(_HERE, "regress_data")
SYNTHETIC_DIR = testpaths.SYNTHETIC_DIR

_ROSTER_FILES = {"sm": "space-marines.json", "tau": "tau-empire.json"}

# Active source; flipped by --real_data before anything is read.
_SOURCE = "synthetic"


def _source_dir():
    return REAL_DIR if _SOURCE == "real" else SYNTHETIC_DIR


def _baseline_path(complete):
    suffix = "_complete" if complete else ""
    return os.path.join(_HERE, f"regress_baseline_{_SOURCE}{suffix}.txt")


def _load_native(army_key):
    path = os.path.join(_source_dir(), _ROSTER_FILES[army_key])
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _num(value):
    """Round a number for stable digests; keep None visible as such."""
    return None if value is None else round(value, 4)


def _fmt(stats):
    """'mean/median' of an analyzer stats dict, rounded for stability."""
    if not stats:
        return "-/-"
    return (f"{round(stats.get('mean', 0), 4)}/"
            f"{round(stats.get('median', 0), 4)}")


# --- Section: damage -----------------------------------------------------

def _damage_section(units, lines):
    lines.append("## damage")
    for (ak, aname), (dk, dname) in rp.PAIRS:
        att = rp.find_unit(units[ak], aname)
        dfn = rp.find_unit(units[dk], dname)
        if att is None or dfn is None:
            lines.append(f"MISSING {aname} vs {dname}")
            continue
        lines.append(f"### {att.name} vs {dfn.name}")
        for mode in ("ranged", "melee"):
            res = rp.analyse(att, dfn, rp.FLAGS_OFF, mode)
            if res is None:
                lines.append(f"  {mode}: (nothing to fire)")
                continue
            for row in res["weapons"]:
                lines.append(
                    f"  {mode}:{row['name']} | A {_fmt(row['attacks'])}"
                    f" | W {_fmt(row['wounds'])}"
                    f" | D {_fmt(row['damage'])}"
                    f" | Dnet {_fmt(row['damage_net'])}")
            tot = res["totals"]
            lines.append(f"  {mode}:TOTAL | D {_fmt(tot['damage'])}"
                         f" | Dnet {_fmt(tot['damage_net'])}"
                         f" | warn={len(res['warnings'])}")


# --- Section: defensive profiles ----------------------------------------

def _profiles_section(units, lines):
    """Every distinct defensive profile of each pair defender. The
    analyzer runs one tab per profile, and '*' marks the profile the
    rules prescribe for the wound roll (suggested_references)."""
    lines.append("## profiles")
    (ak, aname), _ = rp.FLAG_PAIR
    att = rp.find_unit(units[ak], aname)
    if att is None:
        lines.append("MISSING profiles attacker")
        return
    # The pair defenders, plus the first few units that really do carry
    # several distinct defensive profiles (mixed squads, drones): those
    # are the ones where the per-profile split can regress.
    targets = [(dk, dname) for _a, (dk, dname) in rp.PAIRS]
    multi = 0
    for key in sorted(units):
        for unit in sorted(units[key], key=lambda u: u.name):
            if multi >= 4:
                break
            _av, dv = ac.build_views(att, unit, rp.FLAGS_OFF, {})
            if len(ac.reference_options(dv)) > 1:
                targets.append((key, unit.name))
                multi += 1
    seen = set()
    for dk, dname in targets:
        dfn = rp.find_unit(units[dk], dname)
        if dfn is None or dfn.name in seen:
            continue
        seen.add(dfn.name)
        _aview, dview = ac.build_views(att, dfn, rp.FLAGS_OFF, {})
        opts = ac.reference_options(dview)
        suggested = ac.suggested_references(dview, opts)
        for i, (label, _ref) in enumerate(opts):
            res = rp.analyse(att, dfn, rp.FLAGS_OFF, "ranged", ref_index=i)
            mark = "*" if i in suggested else " "
            total = _fmt(res["totals"]["damage"]) if res else "-/-"
            lines.append(f"  {mark}{dfn.name} | {label} | D {total}")


# --- Section: context flags ---------------------------------------------

def _flags_section(units, lines):
    """One pair, one flag at a time. The '(none)' row is the shared
    baseline, so the effect of each flag is readable off the digest."""
    lines.append("## flags")
    (ak, aname), (dk, dname) = rp.FLAG_PAIR
    att = rp.find_unit(units[ak], aname)
    dfn = rp.find_unit(units[dk], dname)
    if att is None or dfn is None:
        lines.append("MISSING flag pair")
        return
    lines.append(f"### {att.name} vs {dfn.name}")
    for mode in ("ranged", "melee"):
        base = rp.total_damage(att, dfn, rp.FLAGS_OFF, mode)
        lines.append(f"  {mode}:(none) | D {_num(base)}")
        for flag in rp.SINGLE_FLAGS:
            flags = {flag: True}
            if flag == "overwatch":
                flags["overwatch_value"] = 6
            lines.append(f"  {mode}:{flag} | "
                         f"D {_num(rp.total_damage(att, dfn, flags, mode))}")


# --- Section: weapon selection ------------------------------------------

def _selection_section(units, lines):
    """Which weapons each attack setup keeps and which it greys out.
    This is rules logic (indirect fire, close quarters, HUNTER) that the
    damage numbers alone never show."""
    lines.append("## selection")
    _att_key, (dk, dname) = rp.FLAG_PAIR
    dfn = rp.find_unit(units[dk], dname)
    if dfn is None:
        lines.append("MISSING selection defender")
        return
    setups = [("ranged", {}), ("ranged", {"indirect": True}),
              ("close_quarters", {}), ("melee", {})]
    for kw, att in sorted(rp.selection_attackers(units).items()):
        lines.append(f"### {kw}: {att.name}")
        for mode, flags in setups:
            res = rp.analyse(att, dfn, flags, mode)
            if res is None:
                continue
            tag = mode + ("+indirect" if flags.get("indirect") else "")
            for skip in res["skipped"]:
                lines.append(f"  {tag} | SKIP {skip['name']} "
                             f"| {skip['reason']}")
            lines.append(f"  {tag} | kept={len(res['weapons'])} "
                         f"skipped={len(res['skipped'])}")


# --- Section: leader / support attachment -------------------------------

def _attach_section(units, lines):
    """Attachment itself (models, points) AND the damage it moves: a
    leader brings its own weapons and its leader_effects to the unit."""
    lines.append("## attach")
    sm = sorted(units["sm"], key=lambda u: u.name)
    leaders = [u for u in sm if getattr(u, "leadership", None)]
    supports = [u for u in sm if getattr(u, "support", None)]
    others = [u for u in sm if not getattr(u, "leadership", None)]
    lines.append(f"### leaders={len(leaders)} supports={len(supports)} "
                 f"others={len(others)}")
    target = (rp.find_unit(units["tau"], "Riptide Battlesuit")
              or rp.find_unit(units["sm"], "Terminator Squad"))
    done = 0
    for ld in leaders:
        for u in others:
            if not u.can_attach(ld):
                continue
            combined = u.attach_leader(ld)
            nmodels = sum(m.model_count for m in combined.models())
            lines.append(f"ATTACH {ld.name} -> {u.name} | models={nmodels}"
                         f" | pts={combined.points}")
            if target is not None:
                for mode in ("ranged", "melee"):
                    solo = rp.total_damage(u, target, rp.FLAGS_OFF, mode)
                    led = rp.total_damage(combined, target, rp.FLAGS_OFF,
                                          mode)
                    lines.append(f"  {mode} vs {target.name} | "
                                 f"D {_num(solo)} -> {_num(led)}")
            done += 1
            break
        if done >= 6:
            break
    done = 0
    for sup in supports:
        for u in others:
            if not u.can_support(sup):
                continue
            combined = u.attach_support(sup)
            nmodels = sum(m.model_count for m in combined.models())
            lines.append(f"SUPPORT {sup.name} -> {u.name} "
                         f"| models={nmodels} | pts={combined.points}")
            done += 1
            break
        if done >= 3:
            break


# --- Section: abilities --------------------------------------------------

def _ability_targets(natives, complete):
    """[(unit_dict, (list_name, index), ability)] to probe.

    Curated (default): one representative per distinct mechanic
    signature, restricted to the delicate effect types. Complete: every
    enabled ability. Deterministic either way -- units are visited in
    name order and the first unit carrying a signature owns it."""
    out, seen = [], set()
    for unit in sorted(natives, key=lambda u: str(u.get("name", ""))):
        for lst, idx, ab in rp.enabled_abilities(unit):
            if complete:
                out.append((unit, (lst, idx), ab))
                continue
            sig = rp.ability_signature(ab)
            if sig[0] not in rp.CRITICAL_EFFECTS or sig in seen:
                continue
            seen.add(sig)
            out.append((unit, (lst, idx), ab))
    return out


def _baseline_damage(off_unit, probe_unit, tag, flags, mode, cache, key):
    """Damage with EVERY ability of the unit disabled, memoised: it is
    the same reference value for every ability of that unit."""
    if key not in cache:
        pair = ((off_unit, probe_unit) if tag == "att"
                else (probe_unit, off_unit))
        cache[key] = rp.total_damage(pair[0], pair[1], flags, mode)
    return cache[key]


def _probe_deltas(unit_native, keep, role, flags, fname, cache,
                  attach=None):
    """[(direction, probe_name, mode, off, on)] for every probe pairing
    where isolating this ability moves the damage.

    With *attach* = (kind, target_native) the ability is probed on the
    COMBINED unit (leader or support joined to a plain unit) instead of
    on its owner alone: that is the only way a leader_effects or a
    shared ability shows up at all."""
    if attach is not None:
        kind, target = attach
        off_unit = rp.combined_unit(unit_native, None, target, kind)
        on_unit = rp.combined_unit(unit_native, keep, target, kind)
        cache_key = f"{unit_native['name']}+{target.get('name')}"
    else:
        off_unit = rp.as_unit(rp.variant(unit_native, None))
        on_unit = rp.as_unit(rp.variant(unit_native, keep))
        cache_key = unit_native["name"]
    directions = []
    if role in (None, "attacker"):
        directions.append(("att", rp.PROBE_DEFENDERS))
    if role in (None, "defender"):
        directions.append(("def", rp.PROBE_ATTACKERS))
    found = []
    for tag, probes in directions:
        for probe in probes:
            other = rp.as_unit(probe)
            for mode in rp.PROBE_MODES:
                key = (cache_key, probe["name"], tag, mode, fname)
                off = _baseline_damage(off_unit, other, tag, flags, mode,
                                       cache, key)
                if tag == "att":
                    on = rp.total_damage(on_unit, other, flags, mode)
                else:
                    on = rp.total_damage(other, on_unit, flags, mode)
                if off is None or on is None or abs(on - off) < 1e-9:
                    continue
                found.append((tag, probe["name"], mode, off, on))
    return found


def _abilities_section(natives, lines, complete, attach_map=None):
    """Per-ability delta, each ability isolated. An ability is probed in
    the neutral context first and only re-probed with every positional
    flag on when the neutral context showed nothing -- so the digest
    reports the SMALLEST context in which the ability is observable.
    Abilities that move no number anywhere are listed as inert, which
    doubles as a coverage report for the ability-conversion work."""
    lines.append("## abilities" + (" (complete)" if complete
                                   else " (curated)"))
    targets = _ability_targets(natives, complete)
    cache, inert = {}, []
    attach_map = attach_map or {"join": {}, "led": {}}
    for unit, keep, ab in targets:
        role = rp.ability_role(ab)
        # A leader_effects entry, or an ability explicitly shared with
        # the unit, only does something once the unit has been JOINED:
        # probe those on the combined unit.
        # A leader_effects (or shared) ability applies to the unit being
        # LED; an ability gated on leaderAttached needs a leader supplied
        # from outside. Both are measurable only on a combined unit.
        attach = rp.resolve_attach(unit, ab, keep[0], attach_map)
        # The list an ability lives in is part of its identity: a
        # leader_effects entry applies to the unit being LED, so it is
        # inert on the unit that owns it BY DESIGN, and core/faction
        # abilities are worth telling apart from the unit's own.
        origin = "" if keep[0] == "abilities" else f" [{keep[0]}]"
        joined = ""
        if attach:
            joined = (f" led by {attach[1].get('name')}"
                      if attach[0] == "led"
                      else f" +{attach[0]} on {attach[1].get('name')}")
        label = (f"{unit['name']}{joined} | {ab.get('name') or '?'}"
                 f"{origin} | {rp.effect_label(ab)}")
        hits = []
        for fname, flags in rp.FLAGSETS:
            hits = _probe_deltas(unit, keep, role, flags, fname, cache,
                                 attach)
            if hits:
                for tag, probe, mode, off, on in hits:
                    lines.append(f"  {label} | {tag} {mode} {probe} | "
                                 f"flags={fname} | {_num(off)} -> {_num(on)}")
                break
        if not hits:
            inert.append(f"  {label}")
    lines.append(f"## abilities inert ({len(inert)} of {len(targets)})")
    lines.extend(sorted(inert))


# --- Digest --------------------------------------------------------------

def build_digest(complete=False):
    """Build the full digest text for the active data source and scope."""
    natives = {k: _load_native(k) for k in _ROSTER_FILES}
    units = {k: um.units_from_native(copy.deepcopy(v))
             for k, v in natives.items()}
    flat = [u for k in sorted(natives)
            for army in natives[k].get("armies", [])
            for u in army.get("units", [])]

    lines = [f"# source={_SOURCE} "
             f"scope={'complete' if complete else 'curated'}"]
    _damage_section(units, lines)
    _profiles_section(units, lines)
    _flags_section(units, lines)
    _selection_section(units, lines)
    _attach_section(units, lines)
    # Leaders and supports are resolved once: a leader_effects ability
    # is inert on its owner and only measurable on the combined unit.
    attach_map = {"join": {}, "led": {}}
    for key in sorted(natives):
        army_natives = [u for army in natives[key].get("armies", [])
                        for u in army.get("units", [])]
        maps = rp.attachment_targets(units[key], army_natives)
        attach_map["join"].update(maps["join"])
        attach_map["led"].update(maps["led"])
    lines.append(f"## attachments resolved (join={len(attach_map['join'])} "
                 f"led={len(attach_map['led'])})")
    _abilities_section(flat, lines, complete, attach_map)

    body = "\n".join(lines)
    h = hashlib.sha256(body.encode()).hexdigest()[:16]
    # The digest hash is part of the compared text: a one-line change is
    # obvious at the bottom, and the per-line diff shows exactly what moved.
    return f"{body}\n\nDIGEST {h}  ({len(lines)} lines)\n"


def main(argv=None):
    global _SOURCE
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--save", action="store_true",
                   help="(re)write the baseline for the active source/scope")
    g.add_argument("--print", dest="just_print", action="store_true",
                   help="print the digest only; do not compare or save")
    ap.add_argument("--real_data", action="store_true",
                    help="use the committed real fixture in "
                         "tests/regress_data/ instead of the synthetic "
                         "roster (falls back to synthetic if absent)")
    ap.add_argument("--complete", action="store_true",
                    help="probe EVERY enabled ability instead of one "
                         "representative per delicate mechanic; uses its "
                         "own baseline")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="also print the full digest when comparing, not "
                         "just the OK/mismatch verdict")
    args = ap.parse_args(argv)

    if args.real_data:
        probe = os.path.join(REAL_DIR, _ROSTER_FILES["sm"])
        if os.path.isfile(probe):
            _SOURCE = "real"
        else:
            sys.stderr.write("real fixture absent (run "
                             "make_regress_data.py) -- using synthetic\n")

    digest = build_digest(args.complete)
    path = _baseline_path(args.complete)
    tag = f"{_SOURCE}/{'complete' if args.complete else 'curated'}"

    if args.just_print:
        sys.stdout.write(digest)
        return 0

    if args.save:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(digest)
        print(f"[{tag}] baseline written: {os.path.basename(path)}")
        return 0

    if args.verbose:
        sys.stdout.write(digest)
        if not digest.endswith("\n"):
            sys.stdout.write("\n")

    if not os.path.isfile(path):
        sys.stderr.write(
            f"[{tag}] no baseline at {os.path.basename(path)} -- run "
            f"'python3 test_regress.py --save' once to create it.\n")
        return 2

    with open(path, encoding="utf-8") as fh:
        expected = fh.read()

    if digest == expected:
        print(f"[{tag}] regression OK (digest matches baseline)")
        return 0

    sys.stderr.write(f"[{tag}] REGRESSION: digest differs from baseline\n")
    diff = difflib.unified_diff(
        expected.splitlines(keepends=True), digest.splitlines(keepends=True),
        fromfile=f"baseline_{_SOURCE}", tofile="current")
    sys.stderr.writelines(diff)
    return 1


if __name__ == "__main__":
    sys.exit(main())
