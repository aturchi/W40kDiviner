# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the W40kDiviner suite (Windows).

Builds four fully self-contained one-file executables (Python and all
dependencies embedded, nothing to install on the target machine):

    ProfileEditor.exe    - profile / abilities editor (GUI)
    AttackAnalyzer.exe   - exact attack statistics (GUI)
    GameAssistant.exe    - in-game dice resolution (GUI)
    JoinArmies.exe       - multi-army JSON merger (command line)

Build (from the W40kDiviner folder, on Windows):
    pip install pyinstaller
    pyinstaller W40kDiviner.spec

The executables end up in dist/. keywords_config.json is embedded, but
a copy placed NEXT TO the .exe takes precedence (user-customisable
vocabularies). Ship your roster .json files (e.g. tau_native.json)
alongside the executables; they are loaded through the file dialogs.

UPX is disabled on purpose: compressed one-file bootloaders trip some
antivirus heuristics, which matters when distributing to other people.
"""

DATAS = [("keywords_config.json", ".")]
PATHEX = ["src"]


def build_exe(script, name, console):
    a = Analysis(
        [script],
        pathex=PATHEX,
        binaries=[],
        datas=DATAS,
        hiddenimports=[],
        hookspath=[],
        runtime_hooks=[],
        excludes=[],
        noarchive=False,
    )
    pyz = PYZ(a.pure, a.zipped_data)
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


build_exe("profile_editor.py", "ProfileEditor", console=False)
build_exe("attack_analyzer.py", "AttackAnalyzer", console=False)
build_exe("game_assistant.py", "GameAssistant", console=False)
build_exe("join_armies.py", "JoinArmies", console=True)
