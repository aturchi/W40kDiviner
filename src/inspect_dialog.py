"""Interactive inspect window (analyzer + game assistant).

Shows a unit's full profile and, below it, two editable sections:

- Abilities: one checkbox per ability toggling its 'enabled' flag. The
  ability NAME is always shown (many core/faction abilities carry no
  description at all), with the full description wrapped underneath -
  never truncated.
- Weapons: one spin box per weapon count, 0 meaning "weapon disabled"
  (the analyzer reports the weapon as skipped). Shown only when the
  caller asks for it: the game assistant edits the counts in its own
  table, so its inspect window keeps the abilities section alone.

Both sections act on the DICTS/objects passed in, so the caller decides
persistence:

- game assistant passes the roster's native dicts -> the change sticks
  for the session (rebuilt units re-read the same dicts), but is not
  saved to file;
- analyzer passes the loaded unit's live objects; weapon counts are
  mirrored into the native dict behind each weapon, so they also travel
  with a saved session.

Neither writes to disk: only the profile editor persists these fields.
"""

import tkinter as tk
from tkinter import ttk

import leader_core as lc
from leader_core import (iter_ability_dicts as _iter_ability_dicts,  # noqa: F401
                         ability_dicts_of_unit)  # noqa: F401
from unit_model import native_weapon_dict

_SECTION_H = 150            # px, visible height of a scrollable section
_DESC_PAD = 48              # px, wraplength margin inside a section
_GREY = "#555555"


# ---------------- weapon handles ----------------


class WeaponRef:
    """Editable handle on the count of one weapon of a LIVE Unit.

    Writing 'count' updates the Weapon object the analysis reads AND,
    when the weapon came from a loaded roster, the native dict behind
    it - so the edit also travels with a saved session.
    """

    def __init__(self, scope, weapon):
        self.scope = scope
        self.weapon = weapon
        self.native = native_weapon_dict(weapon)

    @property
    def label(self):
        """'[R] Fusion collider' - type initial plus weapon name."""
        return f"[{str(self.weapon.type or '?')[0]}] {self.weapon.name}"

    @property
    def count(self):
        try:
            return max(0, int(self.weapon.count))
        except (TypeError, ValueError):
            return 1

    @count.setter
    def count(self, n):
        n = max(0, int(n))
        self.weapon.count = n
        if self.native is not None:
            self.native["count"] = n


def weapon_refs_of_unit(unit):
    """WeaponRefs for every weapon of a Unit OBJECT, including those of
    an attached leader/support (Unit.models() spans them)."""
    return [WeaponRef(f"model: {m.name}", w)
            for m in unit.models() for w in m.weapons]


# ---------------- window ----------------


def open_inspect(parent, unit_obj, ability_dicts=None, on_toggle=None,
                 weapon_refs=None):
    """Open the inspect window for a Unit object.

    ability_dicts: native ability dicts (or (scope, dict) pairs) to show
        as enable/disable checkboxes; on_toggle() runs after each change.
    weapon_refs: WeaponRef list to show as editable counts (omit it where
        the caller already owns the counts, as the game assistant table
        does).
    """
    win = tk.Toplevel(parent)
    win.title(f"Inspect - {unit_obj.name}")

    txt = tk.Text(win, wrap=tk.WORD, width=86, height=22)
    txt.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

    def _render():
        """(Re)fill the profile panel; it prints the weapon counts, so it
        must follow an edit made in the weapons section."""
        txt.configure(state=tk.NORMAL)
        txt.delete("1.0", tk.END)
        txt.insert(tk.END, lc.unit_inspect_text(unit_obj))
        txt.configure(state=tk.DISABLED)

    _render()
    if ability_dicts:
        _abilities_section(win, ability_dicts, on_toggle)
    if weapon_refs:
        _weapons_section(win, weapon_refs, _render)
    return win


def _abilities_section(win, ability_dicts, on_toggle):
    inner, canvas = _scroll_area(
        win, "Abilities (uncheck to disable for this session)")
    labels = []
    for scope, ab in _iter_ability_dicts_from_list(ability_dicts):
        var = tk.BooleanVar(value=bool(ab.get("enabled", True)))

        def _cb(a=ab, v=var):
            a["enabled"] = bool(v.get())
            if on_toggle is not None:
                on_toggle()

        # The NAME identifies the ability; the description is optional
        # (core/faction abilities are usually stored without one) and is
        # shown in full underneath, wrapped to the section width.
        name = (ab.get("name") or "").strip() or "<unnamed ability>"
        ttk.Checkbutton(inner, variable=var, text=f"[{scope}] {name}",
                        command=_cb).pack(anchor=tk.W, padx=4)
        desc = (ab.get("description") or "").strip()
        if desc:
            lab = ttk.Label(inner, text=desc, justify=tk.LEFT,
                            foreground=_GREY)
            lab.pack(anchor=tk.W, padx=(26, 4), pady=(0, 3), fill=tk.X)
            labels.append(lab)
    _bind_wrap(canvas, labels)


def _weapons_section(win, refs, render):
    inner, _canvas = _scroll_area(win, "Weapons (count, 0 = disabled)")
    for ref in refs:
        row = ttk.Frame(inner)
        row.pack(fill=tk.X, padx=4, pady=1)
        var = tk.StringVar(value=str(ref.count))

        def _apply(*_a, r=ref, v=var):
            try:
                n = max(0, int(v.get()))
            except ValueError:
                return                  # empty/partial input: keep old value
            if n != r.count:
                r.count = n
                render()        # the profile panel prints the counts

        var.trace_add("write", _apply)
        ttk.Spinbox(row, from_=0, to=999, width=4,
                    textvariable=var).pack(side=tk.LEFT)
        ttk.Label(row, text=f"[{ref.scope}] {ref.label}").pack(
            side=tk.LEFT, padx=6)


# ---------------- small widgets ----------------


def _scroll_area(win, title, height=_SECTION_H):
    """LabelFrame holding a vertically scrollable frame; returns
    (inner_frame, canvas). The inner frame is kept as wide as the canvas
    so wrapped labels can use the whole width."""
    frame = ttk.LabelFrame(win, text=title)
    frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
    canvas = tk.Canvas(frame, height=height, highlightthickness=0)
    sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=canvas.yview)
    inner = ttk.Frame(canvas)
    wid = canvas.create_window((0, 0), window=inner, anchor="nw")
    inner.bind("<Configure>",
               lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>",
                lambda e: canvas.itemconfigure(wid, width=e.width))
    canvas.configure(yscrollcommand=sb.set)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    sb.pack(side=tk.RIGHT, fill=tk.Y)
    _bind_wheel(canvas, frame)
    return inner, canvas


_WHEEL_SEQS = ("<MouseWheel>", "<Button-4>", "<Button-5>")


def _bind_wheel(canvas, frame):
    """Mouse-wheel scrolling while the pointer is over this section
    (Windows/macOS send <MouseWheel>, X11 sends Button-4/5). The global
    binding is installed on enter and removed on leave, so two sections
    in the same window never fight over the wheel."""
    def _wheel(e):
        step = -1 if getattr(e, "num", 0) == 4 or getattr(e, "delta", 0) > 0 \
            else 1
        canvas.yview_scroll(step, "units")

    def _on(_e):
        for seq in _WHEEL_SEQS:
            canvas.bind_all(seq, _wheel)

    def _off(e):
        # Moving onto a child widget also fires <Leave> on the frame
        # (NotifyInferior): the pointer is still inside the section.
        if str(getattr(e, "detail", "")) != "NotifyInferior":
            for seq in _WHEEL_SEQS:
                canvas.unbind_all(seq)

    frame.bind("<Enter>", _on)
    frame.bind("<Leave>", _off)


def _bind_wrap(canvas, labels):
    """Keep the description labels wrapped to the current section width."""
    def _resize(e):
        for lab in labels:
            lab.configure(wraplength=max(200, e.width - _DESC_PAD))
    canvas.bind("<Configure>", _resize, add="+")


def _iter_ability_dicts_from_list(ability_dicts):
    """ability_dicts may be a native unit dict or a pre-built list of
    (scope, dict) pairs; normalise to pairs."""
    if isinstance(ability_dicts, dict):
        yield from _iter_ability_dicts(ability_dicts)
    else:
        for item in ability_dicts:
            if isinstance(item, tuple):
                yield item
            else:
                yield ("ability", item)
