#!/usr/bin/env python3
"""Build the dedicated regression fixture in ``tests/regress_data/``.

Why a dedicated source: the regression digest has to exercise the
ABILITY dynamics, and the ArmyFetcher output carries only inert
placeholders (``enabled: false``, no-op ``special`` effect). The curated
rosters in ``rosters/`` do carry working abilities -- but they are live
working files that change as the ability-conversion work proceeds, so
comparing a frozen baseline against them would fail for reasons that
have nothing to do with the engine.

So the fixture is COMPILED from ``rosters/`` and then COMMITTED under
``tests/``: the digest is stable until this script is re-run on purpose,
and the test suite still runs on a checkout without ``rosters/``.

What is kept:
  * every unit carrying at least one ENABLED ability (that is what the
    ability section probes), plus
  * the archetype units the pair / attach sections look up by name
    (see regress_probes.required_names), plus
  * for every kept leader or support, one unit it can actually join --
    a leader_effects ability is inert on its owner and only measurable
    on the combined unit, so pruning every led unit would quietly make
    those abilities untestable.
What is dropped, to keep the fixture small and its diffs readable:
  * disabled abilities -- they are inert by construction and cannot
    change any number the engine produces;
  * the free-text fields (``description`` at every level,
    ``unit_composition``, ``wargear_options``, ``notes``) -- rules prose
    that the engine never reads.

Usage:
    python3 tests/make_regress_data.py            # rebuild the fixture
    python3 tests/make_regress_data.py --check    # report, write nothing
"""
import argparse
import copy
import json
import os
import sys

import testpaths                        # puts src/ on sys.path
import regress_probes as rp
import native_format as nf
import unit_model as um


_HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(_HERE, "regress_data")
ROSTERS_DIR = os.path.join(testpaths.REPO_ROOT, "rosters")

# Source rosters merged into each fixture army. Order matters only for
# the dedup (first spelling of a name wins).
SOURCES = {
    "space-marines.json": ["space-marines_1.2.json",
                           "space-marines_space_wolves_1.2.json",
                           "space-marines_legends.json",
                           "space-marines_space_wolves_legends.json"],
    "tau-empire.json": ["tau-empire_1.2.json",
                        "tau-empire_legends.json"],
}

# Which army key of regress_probes each fixture file corresponds to.
ARMY_KEY = {"space-marines.json": "sm", "tau-empire.json": "tau"}

# Free-text fields the engine never reads; dropped to shrink the fixture.
_DROP_UNIT_FIELDS = ("unit_composition", "wargear_options", "notes")


def _strip_text(node):
    """Recursively drop every 'description' key (rules prose)."""
    if isinstance(node, dict):
        return {k: _strip_text(v) for k, v in node.items()
                if k != "description"}
    if isinstance(node, list):
        return [_strip_text(v) for v in node]
    return node


def _slim_unit(unit):
    """Copy of a unit dict with disabled abilities and prose removed."""
    out = copy.deepcopy(unit)
    for lst in rp.ABILITY_LISTS:
        if lst in out:
            out[lst] = [ab for ab in (out[lst] or [])
                        if isinstance(ab, dict) and ab.get("enabled")]
    for field in _DROP_UNIT_FIELDS:
        out.pop(field, None)
    out = _strip_text(out)
    out["description"] = ""             # kept as an empty field for the schema
    return out


def _add_join_targets(units, pool, seen):
    """Make sure every kept leader/support has something to join.

    Leaders name the units they can lead in their 'leadership' list (and
    supports in 'support'). If the selection kept none of them, pull the
    first one back in from the source pool: without it the leader's
    leader_effects can never be measured."""
    for unit in list(units):
        for field in ("leadership", "support"):
            names = [str(n).strip() for n in (unit.get(field) or [])]
            if not names:
                continue
            if any(n.casefold() in seen for n in names):
                continue
            for name in names:
                cand = pool.get(name.casefold())
                if cand is None:
                    continue
                seen.add(name.casefold())
                units.append(_slim_unit(cand))
                break


def _wanted(unit, required):
    """Keep a unit when it carries an enabled ability or when the digest
    looks it up by name."""
    if rp.enabled_abilities(unit):
        return True
    return unit.get("name") in required


def build(fixture_name):
    """Assemble one fixture army from its source rosters."""
    required = rp.required_names(ARMY_KEY[fixture_name])
    units, seen, missing_sources = [], set(), []
    pool = {}                           # every source unit, by folded name
    for src in SOURCES[fixture_name]:
        path = os.path.join(ROSTERS_DIR, src)
        if not os.path.isfile(path):
            missing_sources.append(src)
            continue
        data = nf.load(path)            # migrate + validate on the way in
        for army in data.get("armies", []):
            for unit in army.get("units", []):
                key = str(unit.get("name", "")).strip().casefold()
                pool.setdefault(key, unit)
                if key in seen or not _wanted(unit, required):
                    continue
                seen.add(key)
                units.append(_slim_unit(unit))
    _add_join_targets(units, pool, seen)
    units.sort(key=lambda u: u["name"].casefold())
    data = {"format": nf.FORMAT_TAG,
            "armies": [{"name": fixture_name.replace(".json", ""),
                        "units": units}]}
    return data, required, missing_sources


def check(fixture_name, data, required):
    """Assert the fixture is loadable and holds what the digest needs."""
    nf.validate(data)
    units = um.units_from_native(copy.deepcopy(data))
    names = {u.name.casefold() for u in units}
    absent = [n for n in sorted(required)
              if not any(n.casefold() == m or n.casefold() in m
                         for m in names)]
    n_ab = sum(len(rp.enabled_abilities(u))
               for u in data["armies"][0]["units"])
    return len(units), n_ab, absent


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="build and report, but do not write the fixture")
    args = ap.parse_args(argv)

    if not os.path.isdir(ROSTERS_DIR):
        sys.stderr.write(f"no rosters/ directory at {ROSTERS_DIR}\n")
        return 2

    os.makedirs(OUT_DIR, exist_ok=True)
    failed = False
    for fixture in sorted(SOURCES):
        data, required, missing = build(fixture)
        if missing:
            sys.stderr.write(f"{fixture}: missing sources {missing}\n")
        n_units, n_ab, absent = check(fixture, data, required)
        if absent:
            failed = True
            sys.stderr.write(f"{fixture}: units the digest needs are "
                             f"absent: {absent}\n")
        path = os.path.join(OUT_DIR, fixture)
        if not args.check:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=1, ensure_ascii=False)
        size = (os.path.getsize(path) / 1024.0
                if os.path.isfile(path) else 0.0)
        print(f"{fixture}: {n_units} units, {n_ab} enabled abilities, "
              f"{size:.0f} KiB")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
