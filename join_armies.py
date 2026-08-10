#!/usr/bin/env python3
"""Join several native JSON files into one multi-army file.

Usage:
    python3 join_armies.py tau.json wolves.json -o combined.json

Inputs may be v1 (auto-migrated, army named 'Unnamed army') or v2.
Duplicate army names are rejected: rename them before joining.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "src"))

import native_format         # noqa: E402
import ability_ids           # noqa: E402


def main():
    ap = argparse.ArgumentParser(
        description="Join native JSON army files into one file.")
    ap.add_argument("inputs", nargs="+", help="input JSON files")
    ap.add_argument("-o", "--output", default="combined.json",
                    help="output path (default: combined.json)")
    ap.add_argument("-n", "--name", default="NewArmy",
                    help="New name for joined army (default: NewArmy)")
    args = ap.parse_args()

    try:
        newname=args.name
        datasets = [native_format.load(p) for p in args.inputs]
        joined = native_format.join_raw(datasets,newname)
        # After merging, guarantee every ability has a globally unique
        # id (collisions between files are re-stamped).
        n_ids = ability_ids.ensure_ids(joined)
        native_format.save(joined, args.output)
    except Exception as exc:
        sys.exit(f"Join failed: {exc}")
    names = [a["name"] for a in joined["armies"]]
    n_units = sum(len(a["units"]) for a in joined["armies"])
    print(f"Wrote {args.output}: {len(names)} armies ({', '.join(names)}), "
          f"{n_units} units")
    if n_ids:
        print(f"Assigned/normalised {n_ids} ability id(s) for uniqueness")


if __name__ == "__main__":
    main()
