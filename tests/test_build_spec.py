"""The PyInstaller spec names files that exist.

A .spec is Python that PyInstaller executes, so nothing checks it until
someone runs a build - and a build is the one thing that is never run in
this suite. It had drifted: its DATAS still pointed at a
keywords_config.json that had moved into src/, so the build would have
died on the first file it looked for, and it still declared an
executable for a program that no longer exists.

Executed here against stand-ins for Analysis/PYZ/EXE. That proves the
spec parses, that every script and data file it names is really there,
and that the list of programs matches the suite.
"""
import os

import testpaths                                          # noqa: F401

REPO = testpaths.REPO_ROOT
SPEC = os.path.join(REPO, "W40kDiviner.spec")

built = []
analysed = []


class FakeAnalysis:
    def __init__(self, scripts, pathex=(), binaries=(), datas=(),
                 hiddenimports=(), hookspath=(), runtime_hooks=(),
                 excludes=(), noarchive=False, **kw):
        analysed.append(self)
        self.scripts = list(scripts)
        self.pathex = list(pathex)
        self.binaries = list(binaries)
        self.datas = list(datas)
        self.excludes = list(excludes)
        self.pure = []


def FakePYZ(*a, **kw):
    return object()


def FakeEXE(pyz, scripts, binaries, datas, extra, name=None, console=True,
            upx=True, **kw):
    built.append({"name": name, "console": console, "upx": upx,
                  "scripts": scripts})
    return object()


ns = {"Analysis": FakeAnalysis, "PYZ": FakePYZ, "EXE": FakeEXE,
      "__file__": SPEC}
with open(SPEC, encoding="utf-8") as fh:
    exec(compile(fh.read(), SPEC, "exec"), ns)       # noqa: S102

names = [e["name"] for e in built]
assert names == ["ProfileEditor", "AttackAnalyzer", "GameAssistant"], names
print("the spec builds exactly the three programs:", names)

# A GUI program with console=True opens a terminal window behind it on
# Windows; UPX compression trips antivirus heuristics on one-file
# bootloaders. Both are deliberate and both are easy to lose in an edit.
for entry in built:
    assert entry["console"] is False, entry
    assert entry["upx"] is False, entry

# Every script it names must exist, and be one of the three programs.
for script, _name in ns["PROGRAMS"]:
    assert os.path.isfile(os.path.join(REPO, script)), script
assert not os.path.exists(os.path.join(REPO, "join_armies.py")), \
    "the CLI was removed; nothing may declare a build for it"

# Every embedded data file must exist. This is the check that would have
# caught the drift: the path was still the old one.
for source, _dest in ns["DATAS"]:
    assert os.path.isfile(os.path.join(REPO, source)), source
print("every script and data file named by the spec exists:",
      [s for s, _d in ns["DATAS"]])

# src/ has to reach Analysis on pathex: the entry scripts add it to
# sys.path at RUNTIME, which the static analysis never sees, so without
# it every engine import comes out missing from the build. Asserted on
# what Analysis was actually given, not on the constant it came from.
assert ns["SRC"] == "src" and os.path.isdir(os.path.join(REPO, ns["SRC"]))
assert len(analysed) == len(built) == 3, (len(analysed), len(built))
for a in analysed:
    assert ns["SRC"] in a.pathex, a.pathex
    assert a.datas == ns["DATAS"], a.datas
print("every program is analysed with src/ on the search path")
print("ALL BUILD SPEC TESTS PASS")
