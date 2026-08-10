#!/usr/bin/env python3
"""One-shot runner for the W40kDiviner engine test suite in tests/.

Runs every ``test_*.py`` in this directory (plus the ``regress.py``
characterisation script) and prints a single comprehensive report:
a per-test PASS / FAIL table, timings, a summary line, and the captured
output of anything that did not pass.

Scope: this runner covers ONLY the engine tests that live in tests/.
``test_army_parse.py`` is intentionally excluded -- it tests the
ArmyFetcher parser (a separate component that lives under ArmyFetcher/
and imports its modules), not the W40kDiviner engine. Run it separately
from the ArmyFetcher directory if needed.

Why subprocesses? The suite mixes two incompatible styles -- ``unittest``
modules (which call ``sys.exit`` via ``unittest.main``) and top-level
``assert`` scripts. Importing them into one process would let the first
``unittest.main`` tear the whole run down. Running each file as its own
process instead isolates them completely, judges the result purely by the
child's exit code (0 == pass), and needs ZERO changes to the existing
tests -- this file only observes them.

Data: the tests that read roster JSON go through ``testpaths.roster``,
which falls back to the synthetic roster in ``tests/synthetic/`` when no
real ArmyFetcher tree is present (see make_synthetic.py). So the whole
suite runs on a bare checkout -- there is nothing to skip.

Usage:
    python3 run_all.py                # run everything on synthetic data
    python3 run_all.py --real_data    # run everything on the real data
    python3 run_all.py --save         # let regress.py (re)write its baseline
    python3 run_all.py --real_data --save   # rewrite the real baseline
    python3 run_all.py -v             # also stream each test's own output
    python3 run_all.py -k damage      # only tests whose name contains 'damage'

--real_data and --save are forwarded to regress.py; --real_data also selects
the real source for every other roster-reading test.

Exit code: the number of FAIL/ERROR tests (0 when all pass), so CI can
gate on it directly.
"""
import argparse
import os
import subprocess
import sys
import time

import testpaths                       # sets sys.path; exposes DATA_DIR

# Tests NOT part of the W40kDiviner engine suite (handled elsewhere).
_EXCLUDED = {"test_army_parse.py"}

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

# ANSI colours, disabled when the output is not a TTY (e.g. piped to a file).
_TTY = sys.stdout.isatty()


def _c(code, text):
    """Wrap text in an ANSI colour code when writing to a terminal."""
    return f"\033[{code}m{text}\033[0m" if _TTY else text


_STATUS_STYLE = {
    "PASS": ("32", "PASS"),      # green
    "FAIL": ("31", "FAIL"),      # red
    "ERROR": ("31", "ERROR"),    # red
}


def discover():
    """Return the ordered list of test filenames to run.

    All ``test_*.py`` in this directory (minus _EXCLUDED), sorted, with
    ``regress.py`` appended last (it's a characterisation digest, not a
    pass/fail test in the strict sense, but we still run and time it)."""
    names = sorted(f for f in os.listdir(_TESTS_DIR)
                   if f.startswith("test_") and f.endswith(".py")
                   and f not in _EXCLUDED)
    if os.path.exists(os.path.join(_TESTS_DIR, "regress.py")):
        names.append("regress.py")
    return names


def run_one(fname, extra_args=None, env=None):
    """Run a single test file as a subprocess.

    Returns a dict with keys: name, status, seconds, output. 'status' is
    one of PASS / FAIL / ERROR. Roster-reading tests resolve their data
    through testpaths (synthetic by default, or the real ArmyFetcher tree
    when requested via env), so nothing is skipped here. 'extra_args' are
    appended to the child's argv (only regress.py accepts any); 'env' is
    the child environment (used to select real data suite-wide)."""
    path = os.path.join(_TESTS_DIR, fname)
    cmd = [sys.executable, path] + list(extra_args or [])

    start = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, cwd=_TESTS_DIR, env=env, capture_output=True, text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired as exc:
        return {"name": fname, "status": "ERROR",
                "seconds": time.perf_counter() - start,
                "output": f"TIMEOUT after {exc.timeout}s\n"
                          f"{exc.stdout or ''}{exc.stderr or ''}"}

    seconds = time.perf_counter() - start
    output = (proc.stdout or "") + (proc.stderr or "")
    # Exit code 0 == the test's own asserts/unittest all passed.
    status = "PASS" if proc.returncode == 0 else "FAIL"
    return {"name": fname, "status": status, "seconds": seconds,
            "output": output.strip()}


def _print_report(results, verbose):
    """Print the per-test table, failing-test output, and the summary."""
    width = max(len(r["name"]) for r in results)

    print()
    print(_c("1", "W40kDiviner test suite"))
    print("=" * (width + 26))
    for r in results:
        colour, label = _STATUS_STYLE[r["status"]]
        line = (f"  {r['name']:<{width}}  "
                f"{_c(colour, f'{label:<5}')}  {r['seconds']:6.2f}s")
        print(line)
        if verbose and r["output"]:
            for ln in r["output"].splitlines():
                print(f"      {ln}")
    print("=" * (width + 26))

    # Detailed output for anything that did not pass or skip.
    problems = [r for r in results if r["status"] in ("FAIL", "ERROR")]
    if problems:
        print()
        print(_c("1", "Output of failing tests"))
        for r in problems:
            colour, label = _STATUS_STYLE[r["status"]]
            print("-" * (width + 26))
            print(f"{_c(colour, label)}  {r['name']}")
            print("-" * (width + 26))
            print(r["output"] or "(no output captured)")

    # Summary line.
    n = len(results)
    passed = sum(r["status"] == "PASS" for r in results)
    failed = sum(r["status"] in ("FAIL", "ERROR") for r in results)
    total_s = sum(r["seconds"] for r in results)
    print()
    parts = [_c("32", f"{passed} passed")]
    if failed:
        parts.append(_c("31", f"{failed} failed"))
    print(f"{', '.join(parts)}  of {n} tests in {total_s:.2f}s")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Run the W40kDiviner engine test suite and report.")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="also print each test's own captured output")
    ap.add_argument("-k", metavar="SUBSTR", default=None,
                    help="only run tests whose filename contains SUBSTR")
    ap.add_argument("--real_data", action="store_true",
                    help="run the whole suite against the real ArmyFetcher "
                         "data instead of the default synthetic roster")
    ap.add_argument("--save", action="store_true",
                    help="pass --save to regress.py so it (re)writes its "
                         "baseline for the active source instead of comparing")
    args = ap.parse_args(argv)

    tests = discover()
    if args.k:
        tests = [t for t in tests if args.k in t]
        if not tests:
            print(f"No tests match -k {args.k!r}")
            return 0

    # --real_data selects the real source for EVERY roster-reading test via
    # the env flag; it is also forwarded to regress.py's own --real_data so
    # the choice is explicit there too. --save is regress.py-only.
    child_env = dict(os.environ)
    if args.real_data:
        child_env["W40K_TEST_REAL"] = "1"

    def _extra_args(fname):
        if fname != "regress.py":
            return []
        extra = []
        if args.real_data:
            extra.append("--real_data")
        if args.save:
            extra.append("--save")
        # In verbose mode, ask regress.py for its full digest too; run_all's
        # own -v then prints that captured output under the test.
        if args.verbose:
            extra.append("--verbose")
        return extra

    results = []
    for fname in tests:
        r = run_one(fname, extra_args=_extra_args(fname), env=child_env)
        results.append(r)
        # Live one-line progress so a long run isn't silent.
        colour, label = _STATUS_STYLE[r["status"]]
        print(f"{_c(colour, label):<5}  {r['name']}  ({r['seconds']:.2f}s)")

    _print_report(results, args.verbose)

    # Exit code = number of failing tests (0 when all pass).
    return sum(r["status"] in ("FAIL", "ERROR") for r in results)


if __name__ == "__main__":
    sys.exit(main())
