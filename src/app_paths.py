"""Where the program's files are, running from source or from a build.

Two folders that are the same thing while running from source and two
DIFFERENT things inside a PyInstaller one-file executable:

- :func:`app_dir` - the folder the user sees: the one holding the .exe,
  or the repository root when running from source. Roster files and a
  hand-edited keywords_config.json live here.
- :func:`bundle_dir` - where the files SHIPPED with the program are: the
  temporary folder the one-file build unpacks itself into
  (``sys._MEIPASS``), or ``src/`` when running from source.

Why this module exists at all: a one-file build unpacks into a
temporary folder with a different name on every run, and the frozen
modules' ``__file__`` points INSIDE it. Anything found relative to
``__file__`` therefore lands in a directory the user has never seen and
that is deleted on exit - so "drop your rosters next to the executable"
and "a keywords_config.json next to the executable wins" quietly stop
being true the moment the program is built, while continuing to work
perfectly in every test run from source. That is the kind of difference
no test catches by accident, which is why the two folders are named
apart here instead of being derived at each call site.
"""

import os
import sys

_SRC = os.path.dirname(os.path.abspath(__file__))


def frozen() -> bool:
    """Whether this is running inside a PyInstaller build. PyInstaller
    sets sys.frozen itself; nothing else in the suite writes it."""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> str:
    """The folder the user launches the program from: the one holding
    the executable when frozen, the repository root otherwise (src/ is
    one level below it)."""
    if frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(_SRC)


def bundle_dir() -> str:
    """The folder holding the files shipped with the program.

    ``sys._MEIPASS`` in a one-file build; in a one-directory build there
    is no _MEIPASS and the shipped files sit beside the executable, so
    that is the fallback rather than an error.
    """
    if frozen():
        return getattr(sys, "_MEIPASS", None) or app_dir()
    return _SRC


def resource(name) -> list:
    """The places a shipped but user-overridable file may be, in the
    order they must be tried: the user's own copy next to the program
    first, the bundled one second. Getting that order backwards would
    make the shipped file impossible to override."""
    return [os.path.join(app_dir(), name), os.path.join(bundle_dir(), name)]
