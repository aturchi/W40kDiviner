"""Where the program looks for its files, from source and from a build.

A PyInstaller one-file executable unpacks itself into a temporary folder
and points the frozen modules' __file__ inside it. Everything the user
is meant to touch - the rosters, a hand-edited keywords_config.json -
therefore has to be found relative to the EXECUTABLE, not to __file__,
or it lands in a directory that never existed for the user and is
deleted on exit.

Nothing in a source run can notice that: run from the repository the two
folders coincide, and every test passes either way. So the frozen state
is set up here the way PyInstaller sets it up - sys.frozen and
sys._MEIPASS - and both layouts are asserted.
"""
import json
import os
import shutil
import sys
import tempfile

import testpaths                                          # noqa: F401
import app_paths
import keywords_config
import roster_picker_core as rp

REPO = os.path.dirname(os.path.dirname(os.path.abspath(app_paths.__file__)))
SRC = os.path.dirname(os.path.abspath(app_paths.__file__))


class Frozen:
    """PyInstaller's own markers, put in place for the duration of a
    block and taken away again. sys.frozen and sys._MEIPASS are exactly
    what a build sets, so this drives the real mechanism rather than a
    stand-in for it."""

    def __init__(self, exe_dir, meipass=None):
        self.exe = os.path.join(exe_dir, "AttackAnalyzer.exe")
        self.meipass = meipass

    def __enter__(self):
        self._saved = (getattr(sys, "frozen", None), sys.executable,
                       getattr(sys, "_MEIPASS", None))
        sys.frozen = True
        sys.executable = self.exe
        if self.meipass is None:
            if hasattr(sys, "_MEIPASS"):
                del sys._MEIPASS
        else:
            sys._MEIPASS = self.meipass
        return self

    def __exit__(self, *exc):
        was_frozen, executable, meipass = self._saved
        if was_frozen is None:
            del sys.frozen
        else:
            sys.frozen = was_frozen
        sys.executable = executable
        if meipass is None:
            if hasattr(sys, "_MEIPASS"):
                del sys._MEIPASS
        else:
            sys._MEIPASS = meipass
        return False


# --- running from source ----------------------------------------------

assert app_paths.frozen() is False
assert app_paths.app_dir() == REPO, app_paths.app_dir()
assert app_paths.bundle_dir() == SRC, app_paths.bundle_dir()
assert app_paths.resource("x.json") == [os.path.join(REPO, "x.json"),
                                        os.path.join(SRC, "x.json")]
print("from source: app dir is the repository, bundle dir is src/")


# --- a one-file build -------------------------------------------------

TMP = tempfile.mkdtemp(prefix="w40k_paths_")
EXE_DIR = os.path.join(TMP, "dist")
MEI = os.path.join(TMP, "_MEI123456")
os.makedirs(EXE_DIR)
os.makedirs(MEI)

with Frozen(EXE_DIR, MEI):
    assert app_paths.frozen() is True
    assert app_paths.app_dir() == EXE_DIR, app_paths.app_dir()
    assert app_paths.bundle_dir() == MEI, app_paths.bundle_dir()
    # The user's copy is tried FIRST: a bundled file that could not be
    # overridden would make the config file pointless.
    assert app_paths.resource("k.json") == [os.path.join(EXE_DIR, "k.json"),
                                            os.path.join(MEI, "k.json")]
print("one-file build: app dir is the .exe folder, bundle dir is _MEIPASS")

# A one-directory build has no _MEIPASS; the shipped files sit beside
# the executable, so that is the fallback rather than a crash.
with Frozen(EXE_DIR):
    assert app_paths.bundle_dir() == EXE_DIR, app_paths.bundle_dir()
print("one-directory build: the bundle falls back to the .exe folder")


# --- keywords_config follows the same two folders ---------------------

def write_cfg(folder, word):
    path = os.path.join(folder, keywords_config.FILENAME)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"unit_keywords": [word], "model_keywords": [],
                   "weapon_keywords": []}, fh)
    return path


write_cfg(MEI, "SHIPPED")
with Frozen(EXE_DIR, MEI):
    assert keywords_config.load()["unit_keywords"] == ["SHIPPED"]
    write_cfg(EXE_DIR, "MINE")
    assert keywords_config.load()["unit_keywords"] == ["MINE"], \
        "a copy next to the executable must win over the bundled one"
print("keywords_config: the copy next to the program wins")

# The real shipped file is still found in a source run.
assert len(keywords_config.all_keywords()) > 0, \
    "the bundled keywords_config.json must be found from source too"


# --- the picker opens next to the program -----------------------------

rp.forget()
rosters = os.path.join(EXE_DIR, rp.ROSTERS_DIR)
os.makedirs(rosters)
with Frozen(EXE_DIR, MEI):
    assert rp.default_folder() == rosters, rp.default_folder()
print("the picker opens in the rosters/ folder next to the program")

# Back from source, it is the repository's own rosters/ again - and the
# remembered folder still comes first when there is one.
assert rp.default_folder() == os.path.join(REPO, rp.ROSTERS_DIR), \
    rp.default_folder()
rp.remember(TMP)
assert rp.default_folder() == TMP
rp.forget()

shutil.rmtree(TMP, ignore_errors=True)
print("ALL APP PATH TESTS PASS")
