"""Pure (Tk-free) state of the roster file picker.

WHY THIS EXISTS AT ALL. ``filedialog.askopenfilenames()`` is not our
window: on Windows and macOS it IS the operating system's file dialog,
and on Linux it is GTK's or, failing that, Tk's own Tcl one. Its
selection semantics - a plain click REPLACES the selection, picking
several files needs Ctrl+click - belong to the toolkit and there is no
Tk option that changes them. The only way to get a click-to-toggle file
list is to draw the list ourselves, which is what roster_picker does and
what this module holds the state for.

Two things the state has to get right and a widget cannot:

- **The basket survives navigation.** Chosen files are kept as absolute
  paths, so walking into another folder does not lose them. The native
  dialog cannot do this at all: it hands back one folder's selection and
  forgets everything else.
- **Only the current folder answers to the file list.** Syncing the
  basket from that list is therefore a three-way operation - add what was
  ticked, drop what was unticked, leave every other folder's entries
  alone - and not an assignment. Writing it as an assignment is exactly
  the bug that would make the basket useless.

The last folder is remembered for the PROCESS only (like ui_prefs, and
for the same reason: a session records an analysis, not the shape of the
desk it was run on). The global is written by the GUI through
:func:`remember` rather than by the state, so a RosterPickerState built
with an explicit folder has no hidden input.
"""

import os

import app_paths

#: File extensions offered by default. Lower-case, dot included.
DEFAULT_EXTS = (".json",)

#: The row that walks one folder up. Not a real directory name, so it
#: cannot collide with one.
PARENT = ".."

#: Where rosters are looked for by default. Next to the program, which
#: in a build is NOT next to this file - see app_paths.
ROSTERS_DIR = "rosters"

_last_folder = None


def remember(folder) -> None:
    """Record 'folder' as the one the next picker should open in."""
    global _last_folder
    _last_folder = folder


def forget() -> None:
    """Drop the remembered folder (tests, and a fresh process)."""
    remember(None)


def last_folder():
    """The remembered folder, or None."""
    return _last_folder


def default_folder() -> str:
    """Where a picker opens when the caller names no folder: the last one
    used in this process, else the bundled ``rosters/``, else the working
    directory. Every candidate is checked to still exist, so a folder that
    was renamed between two loads does not open an empty window."""
    rosters = os.path.join(app_paths.app_dir(), ROSTERS_DIR)
    for candidate in (_last_folder, rosters):
        if candidate and os.path.isdir(candidate):
            return candidate
    return os.getcwd()


def size_label(nbytes) -> str:
    """Human-readable file size: '45 B', '812.0 KB', '4.8 MB'."""
    n = float(max(0, int(nbytes)))
    if n < 1024:
        return f"{n:.0f} B"
    for unit in ("KB", "MB", "GB"):
        n /= 1024.0
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"


class RosterPickerState:
    """Folder being browsed + the basket of files chosen for loading.

    Paths in the basket are absolute, so they stay valid whatever the
    current folder becomes. Order is the order they were chosen in, which
    is the order the caller will load them in - native_format.split_armies
    walks the paths as given, so it decides the order of the army list.
    """

    def __init__(self, folder=None, exts=DEFAULT_EXTS):
        self.exts = tuple(str(e).lower() for e in exts)
        self.filter = ""
        self.folder = ""
        self._basket = []
        self.set_folder(folder if folder else default_folder())

    # ---------- navigation ----------

    def set_folder(self, path) -> None:
        """Browse 'path'. Raises OSError if it cannot be listed, WITHOUT
        touching the current folder: the probe comes before the assignment
        precisely so a mistyped path leaves a usable window behind."""
        path = os.path.abspath(os.path.expanduser(str(path)))
        os.listdir(path)                     # probe; raises on failure
        self.folder = path

    def parent(self):
        """The folder above the current one, or None at the filesystem
        root (where dirname() returns the path itself)."""
        up = os.path.dirname(self.folder)
        return up if up and up != self.folder else None

    def enter(self, name) -> bool:
        """Walk into subdirectory 'name', or up when it is PARENT.
        Returns whether the folder changed; raises OSError like
        set_folder if the target cannot be listed."""
        target = (self.parent() if name == PARENT
                  else os.path.join(self.folder, str(name)))
        if not target:
            return False
        before = self.folder
        self.set_folder(target)
        return self.folder != before

    # ---------- listing ----------

    def _scan(self):
        """(subdirectories, matching files) of the current folder, both
        sorted case-insensitively, hidden entries skipped. A folder that
        vanished under us reads as empty rather than raising: set_folder
        already validated it, and the window must stay usable."""
        try:
            names = os.listdir(self.folder)
        except OSError:
            return [], []
        dirs, files = [], []
        for name in names:
            if name.startswith("."):
                continue
            full = os.path.join(self.folder, name)
            if os.path.isdir(full):
                dirs.append(name)
            elif os.path.splitext(name)[1].lower() in self.exts:
                files.append(name)
        return sorted(dirs, key=str.lower), sorted(files, key=str.lower)

    def _size(self, name) -> int:
        try:
            return os.path.getsize(os.path.join(self.folder, name))
        except OSError:
            return 0

    def rows(self):
        """Display rows of the file list: ``[(kind, name, label)]`` with
        'kind' either ``"dir"`` or ``"file"``, directories first.

        The filter text matches FILE NAMES ONLY - a filter that also hid
        folders would make it impossible to navigate while one is typed,
        and the box is there to find a roster, not a folder.
        """
        dirs, files = self._scan()
        text = self.filter.strip().lower()
        rows = []
        if self.parent() is not None:
            rows.append(("dir", PARENT, "[..]"))
        rows.extend(("dir", name, f"[{name}]") for name in dirs)
        for name in files:
            if text and text not in name.lower():
                continue
            rows.append(("file", name,
                         f"{name}   ({size_label(self._size(name))})"))
        return rows

    # ---------- basket ----------

    def basket(self):
        """The chosen paths, in the order they were chosen."""
        return tuple(self._basket)

    def add(self, paths) -> int:
        """Append 'paths' (absolute-ised) to the basket, skipping the ones
        already in it. Returns how many were actually added."""
        added = 0
        for path in paths:
            full = os.path.abspath(os.path.expanduser(str(path)))
            if full not in self._basket:
                self._basket.append(full)
                added += 1
        return added

    def remove(self, paths) -> int:
        """Drop 'paths' from the basket. Returns how many were dropped."""
        drop = {os.path.abspath(os.path.expanduser(str(p))) for p in paths}
        before = len(self._basket)
        self._basket = [p for p in self._basket if p not in drop]
        return before - len(self._basket)

    def clear(self) -> int:
        """Empty the basket; returns how many entries were in it."""
        gone = len(self._basket)
        self._basket = []
        return gone

    def in_folder(self):
        """Basket entries living in the CURRENT folder, as bare names -
        the rows the file list has to show as ticked."""
        return [os.path.basename(p) for p in self._basket
                if os.path.dirname(p) == self.folder]

    def set_folder_selection(self, names) -> None:
        """Make the basket agree with 'names' being the files ticked in the
        current folder.

        Entries from OTHER folders are left exactly as they were, which is
        what lets a selection be assembled across several folders. Newly
        ticked files are appended in the order given; the rest keep their
        position, so re-ticking one file does not reshuffle the list.
        """
        keep = {str(n) for n in names}
        here = self.folder
        self._basket = [p for p in self._basket
                        if os.path.dirname(p) != here
                        or os.path.basename(p) in keep]
        self.add(os.path.join(here, str(n)) for n in names)

    def label(self, path) -> str:
        """Display text of one basket entry: the bare file name, plus the
        folder it came from WHEN another entry shares that name. Two files
        called 'space-marines.json' from different folders are the whole
        point of a basket that spans folders, so they must be told apart -
        and printing the folder for every entry when there is nothing to
        disambiguate only makes the list unreadable."""
        name = os.path.basename(path)
        clash = sum(1 for p in self._basket
                    if os.path.basename(p) == name) > 1
        return f"{name}   ({os.path.dirname(path)})" if clash else name

    def labels(self):
        """Display text of every basket entry, in basket order."""
        return [self.label(p) for p in self._basket]

    def summary(self) -> str:
        """One line for the count label under the basket."""
        n = len(self._basket)
        if not n:
            return "no file selected"
        return "1 file selected" if n == 1 else f"{n} files selected"
