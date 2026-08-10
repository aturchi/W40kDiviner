"""Shared Tk setup panel: attack mode, context flags, manual modifiers
(rolls, re-rolls, characteristics) and the global-options dialog. Used
by both the attack analyzer (program 2) and the game assistant
(program 1) so the context semantics stay identical."""

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox
from ui_utils import scrollable_listbox

import rules_config

FLAGS = [("half_range", "Within half range"),
         ("stationary", "Attacker remained stationary"),
         ("charged", "Attacker charged"),
         ("cover", "Defender in cover (-1 to hit)"),
         ("plunging", "Plunging fire (+1 to hit)"),
         ("damaged", "Attacker damaged (-1 to hit)"),
         ("attacker_below_half", "Attacker below half strength"),
         ("defender_below_half", "Defender below half strength"),
         ("defender_below_full", "Defender below full strength")]

# Modifier targets: (label, kind, key)
MOD_TARGETS = [("Hit roll", "rolls", "hit"),
               ("Wound roll", "rolls", "wound"),
               ("Save roll", "rolls", "save"),
               ("Invuln roll", "rolls", "invuln"),
               ("FNP roll", "rolls", "fnp")] + \
    [(f"Weapon {c}", "weapon", c)
     for c in ("A", "BS", "WS", "S", "AP", "D", "RNG")] + \
    [(f"Attacker model {c}", "attacker_model", c)
     for c in ("M", "T", "Sv", "W", "LD", "OC")] + \
    [(f"Defender model {c}", "defender_model", c)
     for c in ("M", "T", "Sv", "W", "LD", "OC")] + \
    [(f"{lab} reroll 1s", "rerolls", (key, "1"))
     for lab, key in (("Hit", "hit"), ("Wound", "wound"), ("Save", "save"),
                      ("Invuln", "invuln"), ("FNP", "fnp"))] + \
    [(f"{lab} reroll failed", "rerolls", (key, "fails"))
     for lab, key in (("Hit", "hit"), ("Wound", "wound"), ("Save", "save"),
                      ("Invuln", "invuln"), ("FNP", "fnp"))]


class SetupPanel(ttk.LabelFrame):
    """Attack-setup column. on_mode_change is called when the attack
    mode radio changes (the host refreshes the melee weapon choices)."""

    def __init__(self, parent, on_mode_change=None):
        super().__init__(parent, text="Attack setup")
        self._on_mode_change = on_mode_change or (lambda: None)
        self.mode = tk.StringVar(value="ranged")
        for val, lab in [("ranged", "Ranged (all non-pistol)"),
                         ("pistol", "Pistols only"),
                         ("melee", "Melee")]:
            ttk.Radiobutton(self, text=lab, value=val, variable=self.mode,
                            command=self._on_mode_change).pack(
                anchor=tk.W, padx=4)
        ttk.Label(self, text="Melee weapon:").pack(anchor=tk.W, padx=4)
        self.melee_combo = ttk.Combobox(self, state="disabled", width=28)
        self.melee_combo.pack(padx=4, pady=2)

        ttk.Separator(self).pack(fill=tk.X, pady=4)
        self.flag_vars = {}
        self._flag_checks = {}       # key -> Checkbutton (for enabling)
        for key, label in FLAGS:
            var = tk.BooleanVar(value=False)
            cb = ttk.Checkbutton(self, text=label, variable=var)
            cb.pack(anchor=tk.W, padx=4)
            self.flag_vars[key] = var
            self._flag_checks[key] = cb

        ttk.Separator(self).pack(fill=tk.X, pady=4)
        # Manual modifiers: hit/wound roll modifiers are capped by
        # CAP_ROLL_MOD in the attack maths (save mods are uncapped per
        # 11th ed.); characteristic modifiers join the ability deltas
        # inside the combat views (uncapped, floored); re-rolls are
        # limited by CAP_REROLLS ('fails' supersedes '1s').
        ttk.Label(self, text="Manual modifiers:").pack(anchor=tk.W, padx=4)
        mrow = ttk.Frame(self)
        mrow.pack(anchor=tk.W, padx=4)
        self.mod_target = ttk.Combobox(
            mrow, state="readonly", width=20,
            values=[t[0] for t in MOD_TARGETS])
        self.mod_target.set(MOD_TARGETS[0][0])
        self.mod_target.grid(row=0, column=0)
        self.mod_value = ttk.Entry(mrow, width=3)
        self.mod_value.insert(0, "+1")
        self.mod_value.grid(row=0, column=1, padx=3)
        ttk.Button(mrow, text="Add", width=5,
                   command=self.cmd_add_mod).grid(row=0, column=2)
        self.mods = []               # [(label, kind, key, value)]
        mod_frame, self.mod_list = scrollable_listbox(
            self, height=5, exportselection=False)
        mod_frame.pack(fill=tk.X, padx=4, pady=2)
        ttk.Button(self, text="Remove",
                   command=self.cmd_remove_mod).pack(anchor=tk.W, padx=4)

    # ---------- manual modifiers ----------

    def cmd_add_mod(self):
        label = self.mod_target.get()
        kind, key = next((k, ky) for lab, k, ky in MOD_TARGETS
                         if lab == label)
        if kind == "rerolls":
            # the value field is not used: key is (roll, '1'|'fails')
            self.mods.append((label, kind, key, None))
            self.mod_list.insert(tk.END, label)
            return
        try:
            value = int(self.mod_value.get().replace("+", "").strip())
        except ValueError:
            messagebox.showerror("Modifier",
                                 "Value must be a signed integer (+/-N).")
            return
        if value == 0:
            return
        self.mods.append((label, kind, key, value))
        self.mod_list.insert(tk.END, f"{label}: {value:+d}")

    def cmd_remove_mod(self):
        sel = self.mod_list.curselection()
        if not sel:
            return
        del self.mods[sel[0]]
        self.mod_list.delete(sel[0])

    # ---------- accessors ----------

    def get_mode(self) -> str:
        """The selected attack mode ("ranged" or "melee")."""
        return self.mode.get()

    def get_melee(self):
        """The selected melee weapon choice, or None."""
        return self.melee_combo.get() or None

    def set_melee_choices(self, names):
        """Populate the melee-weapon selector with names (clear it when None)."""
        if self.mode.get() == "melee" and names is not None:
            self.melee_combo.configure(state="readonly", values=names)
            if names:
                self.melee_combo.set(names[0])
        else:
            self.melee_combo.set("")
            self.melee_combo.configure(state="disabled")

    def get_flags(self) -> dict:
        """The current context flags as a dict (in_cover, charged, etc.)."""
        return {k: v.get() for k, v in self.flag_vars.items()}

    def set_flag_enabled(self, key: str, enabled: bool):
        """Enable/disable one flag checkbox. When disabling, the flag is
        also reset to False so a stale tick cannot leak into the context.
        Used to gate 'damaged' on the selected attacker's damageable."""
        cb = self._flag_checks.get(key)
        if cb is None:
            return
        cb.configure(state=(tk.NORMAL if enabled else tk.DISABLED))
        if not enabled:
            self.flag_vars[key].set(False)

    def get_mods(self) -> dict:
        """Aggregate the modifier list into {'rolls'|'weapon'|
        'attacker_model'|'defender_model': {key: net value},
        'rerolls': {roll: '1'|'fails'}}. Numeric entries on the same
        target sum up; for re-rolls 'fails' supersedes '1s'."""
        out = {"rolls": {}, "weapon": {},
               "attacker_model": {}, "defender_model": {}, "rerolls": {}}
        for _label, kind, key, value in self.mods:
            if kind == "rerolls":
                roll, what = key
                cur = out["rerolls"].get(roll)
                out["rerolls"][roll] = "fails" \
                    if "fails" in (cur, what) else "1"
            else:
                out[kind][key] = out[kind].get(key, 0) + value
        return out


# ---------- font scaling (accessibility) ----------

_BASE_FONT_SIZES = {}        # captured once, before any scaling
_CURRENT_SCALE = 1.0
_FONT_NAMES = ("TkDefaultFont", "TkTextFont", "TkFixedFont", "TkMenuFont",
               "TkHeadingFont", "TkTooltipFont", "TkIconFont",
               "TkCaptionFont", "TkSmallCaptionFont")


def _capture_base_sizes():
    if _BASE_FONT_SIZES:
        return
    for name in _FONT_NAMES:
        try:
            _BASE_FONT_SIZES[name] = abs(tkfont.nametofont(name).actual("size"))
        except tk.TclError:
            pass


def apply_font_scale(root, scale: float):
    """Scale every standard named Tk font by 'scale' relative to the
    original sizes (captured once), and grow the Treeview row height to
    match. Idempotent: always relative to the captured base, so repeated
    calls do not compound."""
    global _CURRENT_SCALE
    _capture_base_sizes()
    _CURRENT_SCALE = scale
    for name, base in _BASE_FONT_SIZES.items():
        try:
            tkfont.nametofont(name).configure(
                size=max(6, int(round(base * scale))))
        except tk.TclError:
            pass
    # Treeview rows must grow with the font or the text gets clipped.
    try:
        line = tkfont.nametofont("TkDefaultFont").metrics("linespace")
        ttk.Style(root).configure("Treeview", rowheight=line + 4)
    except tk.TclError:
        pass


def show_font_dialog(parent):
    """Small accessibility dialog to pick a global font size (percentage
    of the default). Applies to the whole application window."""
    win = tk.Toplevel(parent)
    win.title("Font size")
    win.transient(parent)
    ttk.Label(win, text="Font size (% of default):").grid(
        row=0, column=0, padx=8, pady=6, sticky=tk.W)
    var = tk.StringVar(value=str(int(round(_CURRENT_SCALE * 100))))
    ttk.Combobox(win, textvariable=var, state="readonly", width=8,
                 values=["80", "90", "100", "125", "150", "175", "200"]).grid(
        row=0, column=1, padx=8, pady=6)

    def apply():
        try:
            scale = max(50, min(300, int(var.get()))) / 100.0
        except ValueError:
            return
        apply_font_scale(parent.winfo_toplevel(), scale)
        win.destroy()

    ttk.Button(win, text="Apply", command=apply).grid(
        row=1, column=0, columnspan=2, pady=8)


def show_options_dialog(parent):
    """Global caps dialog (session-wide, via rules_config.set_caps)."""
    win = tk.Toplevel(parent)
    win.title("Global options")
    win.transient(parent)
    ttk.Label(win, text="Modifier caps (empty = no cap):").grid(
        row=0, column=0, columnspan=2, sticky=tk.W, padx=6, pady=4)
    entries = {}
    for r, (label, cur) in enumerate(
            [("Roll modifier cap (hit/wound)", rules_config.CAP_ROLL_MOD),
             ("Re-roll cap (per die)", rules_config.CAP_REROLLS)],
            start=1):
        ttk.Label(win, text=label).grid(row=r, column=0, sticky=tk.W,
                                        padx=6, pady=2)
        e = ttk.Entry(win, width=6)
        e.insert(0, "" if cur is None else str(cur))
        e.grid(row=r, column=1, padx=6)
        entries[label] = e

    def apply():
        try:
            vals = [None if not e.get().strip() else int(e.get())
                    for e in entries.values()]
            if vals[1] is None or vals[1] < 0:
                raise ValueError("re-roll cap must be an integer >= 0")
        except ValueError as exc:
            messagebox.showerror("Options", f"Invalid caps: {exc}")
            return
        rules_config.set_caps(roll=vals[0], rerolls=vals[1])
        win.destroy()

    ttk.Button(win, text="Apply",
               command=apply).grid(row=4, column=0, columnspan=2, pady=6)
