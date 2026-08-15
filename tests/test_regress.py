"""Headless regression harness for W40kDiviner.

Exercises the leader-attachment path and the damage computation (ranged
AND melee) on a fixed set of attacker/defender pairs, producing a
deterministic textual digest. The digest is compared against a saved
baseline so any change in the damage maths or attachment logic is caught.

The active source defaults to the bundled synthetic roster; pass
``--real_data`` to use a real ArmyFetcher tree instead. Two baselines are
kept side by side, one per data source, because the numbers differ:
  * regress_baseline_real.txt       -- a real ArmyFetcher tree
  * regress_baseline_synthetic.txt  -- the bundled synthetic roster
This script uses the matching baseline automatically.

Usage:
    python3 regress.py               # compare vs baseline (synthetic data)
    python3 regress.py -v            # compare AND print the full digest
    python3 regress.py --real_data   # same, against the real ArmyFetcher tree
    python3 regress.py --save        # (re)write the baseline for this source
    python3 regress.py --print       # just print the digest, no compare/save
    # --save/--print/-v combine with --real_data to target the real source.

Exit code: 0 == digest matches the baseline; 1 == mismatch (a unified
diff is printed); 2 == baseline missing (run --save once to create it).
Run --save the first time, and whenever an intended change alters the
numbers, then commit the updated baseline.
"""
import argparse
import difflib
import hashlib
import os
import sys

import testpaths                      # sets up sys.path to the engine src/

import analyzer_core as ac
import unit_model as um


_HERE = os.path.dirname(os.path.abspath(__file__))


def _baseline_path():
    """Baseline file for the active data source (real vs synthetic)."""
    tag = "synthetic" if testpaths.USING_SYNTHETIC else "real"
    return os.path.join(_HERE, f"regress_baseline_{tag}.txt")


def load_units(name):
    return um.units_from_native(testpaths.load_roster(name))


def by_name(units, needle):
    for u in units:
        if needle.lower() in u.name.lower():
            return u
    return None


def dmg_digest(attacker, defender):
    """Deterministic per-weapon (mean, median) Damage of attacker vs
    defender, across the ranged and melee phases. Returns a list of
    (label, mean, median). Melee needs an explicit main weapon name, so
    the first melee weapon is chosen deterministically."""
    out = []
    for mode in ("ranged", "melee"):
        try:
            aview, dview = ac.build_views(attacker, defender, {}, {})
            opts = ac.reference_options(dview)
            if not opts:
                continue
            ref = opts[0][1]
            mname = None
            if mode == "melee":
                choices = ac.melee_choices(aview)
                if not choices:
                    continue
                mname = choices[0]
            res = ac.run_analysis(aview, dview, ref, {}, mode,
                                  melee_name=mname)
        except Exception as exc:                       # noqa: BLE001
            out.append((mode, "ERROR", str(exc)[:60]))
            continue
        for row in res["weapons"]:
            dmg = row.get("damage") or {}
            out.append((f"{mode}:{row['name']}",
                        round(dmg.get("mean", 0), 4),
                        round(dmg.get("median", 0), 4)))
    return out


def build_digest():
    """Build the full digest text for the active data source."""
    lines = []
    sm = load_units("space-marines.json")
    tau = load_units("tau-empire.json")

    # Representative attacker/defender pairs spanning the varied cases:
    # infantry vs heavy FNP elites, walker vs monster, vehicle AT vs
    # infantry, walker vs battlesuit.
    pairs = [
        (sm, "Intercessor Squad", sm, "Terminator Squad"),
        (sm, "Redemptor Dreadnought", tau, "Riptide Battlesuit"),
        (tau, "Hammerhead Gunship", sm, "Intercessor Squad"),
        (sm, "Ballistus Dreadnought", tau, "Crisis Sunforge"),
    ]
    for aus, aname, dus, dname in pairs:
        a = by_name(aus, aname)
        d = by_name(dus, dname)
        if not a or not d:
            lines.append(f"MISSING {aname} vs {dname}")
            continue
        lines.append(f"### {a.name} vs {d.name}")
        for w, mean, med in dmg_digest(a, d):
            lines.append(f"  {w} | {mean} | {med}")

    # Leader attach: a standalone leader has a non-empty leadership list.
    leaders = [u for u in sm if getattr(u, "leadership", None)]
    others = [u for u in sm if not getattr(u, "leadership", None)]
    lines.append(f"### leaders={len(leaders)} others={len(others)}")
    attached = 0
    for ld in sorted(leaders, key=lambda u: u.name):
        for u in sorted(others, key=lambda u: u.name):
            if u.can_attach(ld):
                combined = u.attach_leader(ld)
                nmodels = sum(m.model_count for m in combined.models())
                lines.append(f"ATTACH {ld.name} -> {u.name} "
                             f"| models={nmodels} pts={combined.points}")
                attached += 1
                break
        if attached >= 5:
            break

    body = "\n".join(lines)
    h = hashlib.sha256(body.encode()).hexdigest()[:16]
    # The digest hash is part of the compared text: a one-line change is
    # obvious at the bottom, and the per-line diff shows exactly what moved.
    return f"{body}\n\nDIGEST {h}  ({len(lines)} lines)\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--save", action="store_true",
                   help="(re)write the baseline for the active source")
    g.add_argument("--print", dest="just_print", action="store_true",
                   help="print the digest only; do not compare or save")
    ap.add_argument("--real_data", action="store_true",
                    help="use the real ArmyFetcher roster instead of the "
                         "default synthetic one (falls back to synthetic if "
                         "the real data is absent)")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="also print the full digest (per-attack damage "
                         "results) when comparing, not just the OK/mismatch "
                         "verdict")
    args = ap.parse_args(argv)

    # Switch the data source before anything reads a roster. Default (no
    # flag) stays on the synthetic roster.
    if args.real_data:
        testpaths.set_source(real=True)

    source = "synthetic" if testpaths.USING_SYNTHETIC else "real"
    digest = build_digest()
    path = _baseline_path()

    if args.just_print:
        sys.stdout.write(digest)
        return 0

    if args.save:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(digest)
        print(f"[{source}] baseline written: {os.path.basename(path)}")
        return 0

    # Compare mode. With --verbose, print the full digest (the per-attack
    # damage results) first, then the verdict -- the older regress.py
    # always dumped these numbers, and -v restores that view on top of the
    # baseline comparison.
    if args.verbose:
        sys.stdout.write(digest)
        if not digest.endswith("\n"):
            sys.stdout.write("\n")

    # Default: compare against the saved baseline.
    if not os.path.isfile(path):
        sys.stderr.write(
            f"[{source}] no baseline at {os.path.basename(path)} -- "
            f"run 'python3 regress.py --save' once to create it.\n")
        return 2

    with open(path, encoding="utf-8") as fh:
        expected = fh.read()

    if digest == expected:
        print(f"[{source}] regression OK (digest matches baseline)")
        return 0

    sys.stderr.write(f"[{source}] REGRESSION: digest differs from baseline\n")
    diff = difflib.unified_diff(
        expected.splitlines(keepends=True),
        digest.splitlines(keepends=True),
        fromfile=f"baseline_{source}", tofile="current")
    sys.stderr.writelines(diff)
    return 1


if __name__ == "__main__":
    sys.exit(main())
