# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the W40kDiviner suite (Windows).

Builds three fully self-contained one-file executables (Python and all
dependencies embedded, nothing to install on the target machine):

    ProfileEditor.exe    - profile / abilities editor
    AttackAnalyzer.exe   - exact attack statistics
    GameAssistant.exe    - in-game dice resolution

Build (from the W40kDiviner folder, on Windows):
    pip install pyinstaller
    pyinstaller W40kDiviner.spec

The executables end up in dist/, one .exe each, with no shared folder
between them.

WHAT TO SHIP ALONGSIDE THEM. A one-file build unpacks itself into a
temporary folder that is deleted on exit, so nothing the user is meant
to touch can live inside it. Two things are therefore looked up NEXT TO
the executable (src/app_paths.py owns that distinction):

    rosters/                 the roster .json files - also the folder
                             the load dialog opens in by default;
    keywords_config.json     optional. The shipped copy is embedded, and
                             one placed next to the .exe takes
                             precedence - that is how the keyword
                             vocabularies are customised.

UPX is disabled on purpose: compressed one-file bootloaders trip some
antivirus heuristics, which matters when distributing to other people.
"""

import os

# The engine lives in src/: the three entry scripts add it to sys.path
# at RUNTIME, which the static analysis never sees, so it has to be
# named here as well or every 'import attack_math' comes out missing.
SRC = "src"

# Embedded at the root of the unpacked folder, which is where
# app_paths.bundle_dir() looks. The user-editable copy is the one next
# to the .exe and is not bundled - see the note above.
DATAS = [(os.path.join(SRC, "keywords_config.json"), ".")]

PROGRAMS = [("profile_editor.py", "ProfileEditor"),
            ("attack_analyzer.py", "AttackAnalyzer"),
            ("game_assistant.py", "GameAssistant")]


def build_exe(script, name, console=False):
    a = Analysis(
        [script],
        pathex=[SRC],
        binaries=[],
        datas=DATAS,
        hiddenimports=[],
        hookspath=[],
        runtime_hooks=[],
        # The test tree is never imported by the programs; excluding it
        # keeps a stray 'import tkstub' from pulling the stub toolkit
        # into a build.
        excludes=["tests", "tkstub", "testpaths", "viewstub"],
        noarchive=False,
    )
    # PYZ(a.pure) alone: the second positional argument of the older
    # templates (a.zipped_data) no longer exists in PyInstaller 6.
    pyz = PYZ(a.pure)
    return EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=name,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=console,
        disable_windowed_traceback=False,
    )


for _script, _name in PROGRAMS:
    build_exe(_script, _name)
