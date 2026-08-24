"""The inspect window (analyzer + game assistant).

The full profile of a unit, read-only, plus "Save cheat sheet...": the
printable one-page version of the unit as the program will play it
(see :mod:`cheat_sheet`).

It used to carry two editable sections - a checkbox per ability and a
spin box per weapon count - because the analyzer had nowhere else to
put them. It now has: both programs switch abilities and weapon counts
off by masking a row of their own table (`unit_tree` in the analyzer,
the model table in the game assistant), which is one gesture instead of
two. The sections were removed with their callers.

Nothing here writes to the roster: only the profile editor persists
these fields.
"""

import tkinter as tk
from tkinter import ttk

import cheat_sheet
import leader_core as lc
import ui_utils as ui


# ---------------- window ----------------


def open_inspect(parent, unit_obj):
    """Open the read-only inspect window for a Unit object."""
    win = tk.Toplevel(parent)
    win.title(f"Inspect - {unit_obj.name}")

    # The bar goes in FIRST, against the bottom: pack() satisfies
    # requested sizes in packing order, and a 22-line Text asks for more
    # than a short window has - packed last, the bar is squeezed to a
    # few pixels and its buttons lose their captions.
    # The printable version of what is above: the unit as the program
    # will play it, leader included and disabled abilities marked.
    bar = ttk.Frame(win)
    bar.pack(side=tk.BOTTOM, fill=tk.X, padx=6, pady=(0, 6))
    ttk.Button(bar, text="Save cheat sheet...",
               command=lambda: _save_sheet(win, unit_obj)).pack(side=tk.LEFT)
    ttk.Button(bar, text="Close", command=win.destroy).pack(side=tk.RIGHT)

    body = ttk.Frame(win)
    body.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
    txt = tk.Text(body, wrap=tk.WORD, width=86, height=22)
    scroll = ttk.Scrollbar(body, orient=tk.VERTICAL, command=txt.yview)
    txt.configure(yscrollcommand=scroll.set)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)
    txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    txt.insert(tk.END, lc.unit_inspect_text(unit_obj))
    txt.configure(state=tk.DISABLED)
    return win


def _save_sheet(win, unit_obj):
    """HTML by default - it prints cleanly from any browser, which is
    cheaper than depending on a PDF library - or plain text when the
    file name says .txt."""
    ui.save_text(win, lambda path: cheat_sheet.render(unit_obj, path),
                 title=f"Cheat sheet - {unit_obj.name}",
                 defaultextension=".html",
                 filetypes=[("HTML (printable)", "*.html"),
                            ("Text", "*.txt")],
                 initialfile=cheat_sheet.default_filename(unit_obj))
