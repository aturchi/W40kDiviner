"""Shared path resolution for the headless test harness.

Importing this module puts the engine's ``src/`` directory on ``sys.path``
(so tests can ``import unit_model`` etc.) and resolves where roster JSON is
read from -- either a real ArmyFetcher tree or the bundled synthetic roster.

Design goals:
- No absolute paths baked into the tests.
- The engine dir is derived from this file's location -- ``tests/`` always
  sits directly under the repository root -- so the tests run from any
  current working directory.
- Tests default to the bundled **synthetic** roster in ``tests/synthetic/``.
  The real ArmyFetcher tree is used only when explicitly requested, via the
  ``W40K_TEST_REAL`` flag, an explicit ``W40K_TEST_DATA`` path, or
  ``--real_data`` on the command line (run_all.py sets the env flag for the
  whole suite; test_regress.py also parses the argument itself). Requesting
  real data that is absent falls back to synthetic AND says so on stderr --
  a silent fallback would let a run reported as real be entirely synthetic.
- Tests ask for a roster by bare name via :func:`roster` and stay agnostic
  to the on-disk layout: the real ArmyFetcher tree keeps its
  ``fetched_armies_40kapp/`` subdir, while the synthetic roster lives flat in
  ``tests/synthetic/``. This module hides that difference.
"""
import os
import sys
import json
import configparser

# tests/ sits directly under the repository root.
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_TESTS_DIR)
SRC_DIR = os.path.join(REPO_ROOT, "src")
_CONFIG_FILE = os.path.join(_TESTS_DIR, "test_config.ini")

# Make the engine importable for every test that imports this module.
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


# Synthetic roster shipped with the tests (see make_synthetic.py). Used when
# no real ArmyFetcher tree provides the expected roster, so the data-dependent
# tests run on a checkout without external data. Flat layout, no subdir.
SYNTHETIC_DIR = os.path.join(_TESTS_DIR, "synthetic")

# Subdirectory the real ArmyFetcher output nests roster JSON under.
_ARMYFETCHER_SUBDIR = "fetched_armies_40kapp"

# The roster used to probe whether a configured tree really has the data.
_PROBE_ROSTER = "space-marines.json"


def _configured_real_dir():
    """Absolute real-data root from env/ini (may or may not exist on disk).

    Precedence: ``W40K_TEST_DATA`` env var, then ``test_config.ini``
    ``data_dir``, then the built-in default ``ArmyFetcher``. Relative values
    are resolved against the repository root."""
    raw = os.environ.get("W40K_TEST_DATA")
    if not raw:
        cp = configparser.ConfigParser(interpolation=None)
        cp.read(_CONFIG_FILE)                    # silently ignored if absent
        raw = cp.get("paths", "data_dir", fallback="ArmyFetcher")
    return raw if os.path.isabs(raw) else os.path.normpath(
        os.path.join(REPO_ROOT, raw))


def _real_roster_path(real_dir, name):
    """Where roster *name* lives inside a real ArmyFetcher tree."""
    return os.path.join(real_dir, _ARMYFETCHER_SUBDIR, name)


def _truthy(value):
    """Interpret an env-var string as a boolean flag."""
    return str(value).strip().lower() in ("1", "true", "yes", "on")


#: Command-line spelling of the real-data request. run_all.py sets the
#: env flag for the whole suite and forwards this to test_regress.py, so
#: the two must mean the same thing.
_ARGV_FLAG = "--real_data"


def _argv_real():
    """Whether ``--real_data`` was passed on the command line.

    Without this, ``python3 test_x.py --real_data`` read the SYNTHETIC
    roster in silence: only test_regress.py parsed the flag, every other
    test ignored argv entirely, and the env flag run_all.py sets was the
    single real switch. Three tests sat broken against the real roster
    for exactly that reason - each of them passed when run by hand with
    the flag, because the flag did nothing.
    """
    return _ARGV_FLAG in sys.argv[1:]


def _real_requested():
    """Whether the real ArmyFetcher data was explicitly asked for, via
    the ``W40K_TEST_REAL`` flag, an explicit ``W40K_TEST_DATA`` path, or
    ``--real_data`` on the command line. Absent all three, the tests
    default to the synthetic roster."""
    if os.environ.get("W40K_TEST_DATA"):
        return True
    if _truthy(os.environ.get("W40K_TEST_REAL", "")):
        return True
    return _argv_real()


_warned_fallback = False


def _warn_fallback(real_dir):
    """Say so when real data was asked for and is not there.

    The fallback itself is deliberate - the suite has to run on a
    checkout with no ArmyFetcher tree - but falling back WITHOUT saying
    so means a run reported as '--real_data' can be entirely synthetic,
    which is the same class of silence this module now guards against on
    the argv side."""
    global _warned_fallback
    if _warned_fallback:
        return
    _warned_fallback = True
    print(f"testpaths: real data requested but {_PROBE_ROSTER} is not "
          f"under {real_dir!r} - falling back to the synthetic roster",
          file=sys.stderr)


def _resolve(force_real=None):
    """Decide between the real tree and the synthetic roster.

    Returns (data_dir, using_synthetic). Default is SYNTHETIC: the real
    tree is used only when explicitly requested (``force_real`` True, or
    the env flags via :func:`_real_requested`) AND it actually contains
    the probe roster -- otherwise it falls back to synthetic so the suite
    still runs, saying so on stderr. ``force_real`` overrides the env
    when not None."""
    want_real = _real_requested() if force_real is None else force_real
    if want_real:
        real = _configured_real_dir()
        if os.path.isfile(_real_roster_path(real, _PROBE_ROSTER)):
            return real, False
        _warn_fallback(real)
    return SYNTHETIC_DIR, True


DATA_DIR, USING_SYNTHETIC = _resolve()


def set_source(real):
    """Re-resolve the active data source at runtime (updates ``DATA_DIR``
    and ``USING_SYNTHETIC``). ``real=True`` forces the real ArmyFetcher
    tree (falling back to synthetic if absent); ``real=False`` forces the
    synthetic roster. Used by test_regress.py's --real_data flag, which is
    parsed after this module is imported."""
    global DATA_DIR, USING_SYNTHETIC
    DATA_DIR, USING_SYNTHETIC = _resolve(force_real=real)
    return DATA_DIR, USING_SYNTHETIC


def roster(name):
    """Absolute path to roster JSON *name* (e.g. ``"space-marines.json"``),
    resolved for whichever source is active. This is what tests should use
    so they stay agnostic to the real-vs-synthetic layout."""
    if USING_SYNTHETIC:
        return os.path.join(SYNTHETIC_DIR, name)
    return _real_roster_path(DATA_DIR, name)


def load_roster(name):
    """Load and parse roster JSON *name* from the active source."""
    with open(roster(name), encoding="utf-8") as fh:
        return json.load(fh)


# --- Backwards-compatible helpers (kept for any external caller) ---------

def data_path(*parts):
    """Join *parts* onto the active data root. Prefer :func:`roster`."""
    return os.path.join(DATA_DIR, *parts)


def load_native(relpath):
    """Load a roster by relative path under the data root. Prefer
    :func:`load_roster`."""
    with open(data_path(relpath), encoding="utf-8") as fh:
        return json.load(fh)
