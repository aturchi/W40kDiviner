"""Shared Tk setup panel: attack mode, context flags, manual modifiers
(rolls, re-rolls, characteristics) and the global-options dialog. Used
by both the attack analyzer (program 2) and the game assistant
(program 1) so the context semantics stay identical.

show_options_dialog() carries the font scale as well as the modifier
caps: two toolbar buttons for what is one "settings" idea was one button
too many, and the profile editor - which has no caps to set - opens the
same dialog with caps=False."""

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, simpledialog
import ui_utils as ui
from ui_utils import scrollable_listbox

import attack_math
import modifier_engine
import rules_config
import ui_prefs
import mod_presets

def _multi_select(parent, title, prompt, items, selected=(),
                  extra_check=None, note=None):
    """Modal multi-selection list. Returns the chosen items in the order
    of 'items', or None if cancelled. 'extra_check' is an optional
    (label, BooleanVar) checkbox shown under the list; 'note' an
    explanatory paragraph above it."""
    win = tk.Toplevel(parent)
    win.title(title)
    win.transient(parent)
    win.geometry("460x400")
    ttk.Label(win, text=prompt).pack(anchor=tk.W, padx=6, pady=(6, 0))
    if note:
        ttk.Label(win, text=note, wraplength=430,
                  foreground=ui.HINT_COLOR).pack(anchor=tk.W, padx=6,
                                                 pady=(2, 0))
    frame, listbox = scrollable_listbox(win, height=10,
                                        selectmode=tk.EXTENDED,
                                        exportselection=False)
    frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
    for i, name in enumerate(items):
        listbox.insert(tk.END, name)
        if name in selected:
            listbox.selection_set(i)
    ui.multi_select_hint(win).pack(anchor=tk.W, padx=6)
    if extra_check:
        ttk.Checkbutton(win, text=extra_check[0],
                        variable=extra_check[1]).pack(anchor=tk.W, padx=6,
                                                      pady=2)
    out = {"value": None}

    def ok():
        out["value"] = [items[i] for i in listbox.curselection()]
        win.destroy()

    row = ttk.Frame(win)
    row.pack(pady=6)
    ttk.Button(row, text="OK", command=ok).pack(side=tk.LEFT, padx=6)
    ttk.Button(row, text="Cancel",
               command=win.destroy).pack(side=tk.LEFT, padx=6)
    win.grab_set()
    parent.wait_window(win)
    return out["value"]


FLAGS = [("half_range", "Within half range"),
         ("attacker_stationary", "Attacker remained stationary"),
         ("charged", "Attacker charged"),
         # 11th ed.: the Benefit of Cover and Plunging Fire modify the
         # attacker's BS CHARACTERISTIC, not the hit roll - so they are
         # not subject to the +/-1 roll cap and stack with a hit-roll
         # modifier. Several sources of cover never stack with each
         # other: cover is a state, not a counter.
         # The signs below are written in the CHARACTERISTIC convention
         # used by the manual modifiers (a raw delta on the BS target
         # number, so +1 is worse), NOT in the rulebook's wording, which
         # calls the same penalty "-1 BS". The direction is spelled out
         # in words so the two readings cannot be confused. 'Damaged' is
         # a HIT ROLL modifier instead, where -1 is the penalty.
         ("cover", "Defender has the Benefit of Cover (BS +1, worse)"),
         ("plunging", "Plunging fire (BS -1, better)"),
         ("damaged", "Attacker damaged (-1 to hit roll)"),
         # Indirect shooting mode: only INDIRECT FIRE weapons are fired,
         # the target always counts as being in Cover, hit re-rolls are
         # lost and an unmodified 1-5 always fails ("spotter" relaxes
         # that to 1-3; tick it only when the unit also Remained
         # Stationary, which the rule requires on top of the spotter).
         ("indirect", "Indirect fire"),
         ("spotter", "  ...with spotter and stationary"),
         ("attacker_below_half", "Attacker below half strength"),
         ("defender_below_half", "Defender below half strength"),
         ("defender_below_full", "Defender below full strength"),
         # Board states an ability can be conditioned on. Without them
         # the objectiveRange / engagementRange conditions could never be
         # true, so an ability using one was silently dead.
         ("attacker_on_objective", "Attacker within range of an objective"),
         ("defender_on_objective", "Defender within range of an objective"),
         ("attacker_in_engagement", "Attacker within Engagement Range"),
         ("defender_in_engagement", "Defender within Engagement Range")]

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


# The manual-modifier value means two different things depending on the
# target, and the two read in OPPOSITE directions:
#   * a ROLL modifier is die-side, so +1 always makes the roll easier;
#   * a CHARACTERISTIC modifier is a raw delta on the stored value, so
#     it improves a target number (BS/WS/Sv/LD) or an AP - both stored
#     "lower is better" - only when it is NEGATIVE.
# The field therefore starts from whichever sign improves the selected
# target, and a hint spells the direction out. The direction itself is
# not repeated here: modifier_engine.improving_sign owns it.
_DEFENDER_ROLLS = ("save", "invuln", "fnp")


def mod_improving_sign(kind, key) -> int:
    """+1 or -1: the value that IMPROVES the selected target."""
    if kind == "rolls":
        return +1
    return modifier_engine.improving_sign(key)


def mod_default_value(kind, key) -> str:
    """What the value field starts from for that target."""
    return f"{mod_improving_sign(kind, key):+d}"


def mod_hint(kind, key) -> str:
    """One line under the field saying which way the value reads."""
    if kind == "rerolls":
        return "a re-roll takes no value"
    if kind == "rolls":
        who = "the defender rolls it" if key in _DEFENDER_ROLLS \
            else "the attacker rolls it"
        return f"+1 = easier to pass ({who})"
    if key == "AP":
        return "-1 = better AP (stored negative, 0 is the worst)"
    if mod_improving_sign(kind, key) < 0:
        return f"-1 = better {key} (target number, lower is better)"
    return f"+1 = better {key}"


class SetupPanel(ttk.LabelFrame):
    """Attack-setup column. on_mode_change is called when the attack
    mode radio changes (the host refreshes the melee weapon choices).

    The controls do not live in the LabelFrame itself but in '.body', a
    ui_utils.ScrollableFrame content area, so the column stays usable on a
    screen too short to show all of it. Anything added to the panel later
    must go into 'self.body' and be passed to 'self._scroll.bind_wheel()',
    or it will be built outside the scrolling region."""

    def __init__(self, parent, on_mode_change=None):
        super().__init__(parent, text="Attack setup")
        self._on_mode_change = on_mode_change or (lambda: None)
        # The column is taller than a 768-line screen once every flag,
        # the modifier list and the presets are in it, and a LabelFrame
        # simply clips whatever does not fit - the bottom rows were
        # unreachable, not just unreadable. Everything therefore goes
        # into a scrolling body; the scrollbar hides itself on a screen
        # tall enough, so nothing changes there.
        self._scroll = ui.ScrollableFrame(self)
        self._scroll.pack(fill=tk.BOTH, expand=True)
        body = self.body = self._scroll.body
        self.mode = tk.StringVar(value="ranged")
        for val, lab in [("ranged", "Ranged"),
                         # Close-quarters shooting (11th ed.): firing at
                         # the enemy unit this one is engaged with. Being
                         # engaged is the user's call - the program
                         # cannot see the table. PISTOL is the 10th-ed.
                         # spelling of CLOSE-QUARTERS, so there is no
                         # separate pistol mode any more.
                         ("close_quarters", "Close quarters"),
                         ("melee", "Melee")]:
            ttk.Radiobutton(body, text=lab, value=val, variable=self.mode,
                            command=self._on_mode_change).pack(
                anchor=tk.W, padx=4)
        ttk.Label(body, text="Melee weapon:").pack(anchor=tk.W, padx=4)
        self.melee_combo = ttk.Combobox(body, state="disabled", width=28)
        self.melee_combo.pack(padx=4, pady=2)

        ttk.Separator(body).pack(fill=tk.X, pady=4)
        self.flag_vars = {}
        self._flag_checks = {}       # key -> Checkbutton (for enabling)
        for key, label in FLAGS:
            var = tk.BooleanVar(value=False)
            cb = ttk.Checkbutton(body, text=label, variable=var)
            cb.pack(anchor=tk.W, padx=4)
            self.flag_vars[key] = var
            self._flag_checks[key] = cb
        # The spotter clause only exists inside indirect fire, so its box
        # stays greyed out (and unticked) until 'indirect' is selected.
        self.flag_vars["indirect"].trace_add(
            "write", lambda *a: self._sync_spotter())
        self._sync_spotter()

        # Overwatch: a tick plus the unmodified roll it needs. The field
        # is only meaningful while the tick is on, so it follows it.
        row = ttk.Frame(body)
        row.pack(anchor=tk.W, padx=4)
        self.flag_vars["overwatch"] = tk.BooleanVar()
        ttk.Checkbutton(row, text="Overwatch: hits on",
                        variable=self.flag_vars["overwatch"]).pack(
            side=tk.LEFT)
        lo, hi = attack_math.OVERWATCH_RANGE
        self.overwatch_value = tk.StringVar(
            value=str(attack_math.OVERWATCH_DEFAULT))
        self.overwatch_spin = ttk.Spinbox(
            row, from_=lo, to=hi, width=3, textvariable=self.overwatch_value)
        self.overwatch_spin.pack(side=tk.LEFT, padx=3)
        ttk.Label(row, text="+").pack(side=tk.LEFT)
        self.flag_vars["overwatch"].trace_add(
            "write", lambda *a: self._sync_overwatch())
        self._sync_overwatch()

        # Battle round: a number, not a tick, so it has no entry in
        # FLAGS. It is always meaningful - every attack happens in some
        # round - which is why it has no checkbox to gate it and why it
        # starts at 1 rather than at "unset". It exists for the
        # battleRound ability condition and for nothing else: none of
        # the maths reads it.
        row = ttk.Frame(body)
        row.pack(anchor=tk.W, padx=4)
        ttk.Label(row, text="Battle round:").pack(side=tk.LEFT)
        lo, hi = rules_config.BATTLE_ROUND_RANGE
        self.battle_round = tk.StringVar(
            value=str(rules_config.BATTLE_ROUND_DEFAULT))
        ttk.Spinbox(row, from_=lo, to=hi, width=3,
                    textvariable=self.battle_round).pack(side=tk.LEFT,
                                                         padx=3)

        ttk.Separator(body).pack(fill=tk.X, pady=4)
        # Manual modifiers: only the HIT and WOUND roll modifiers are
        # capped (CAP_ROLL_MOD) in the attack maths - save, invuln and
        # FNP modifiers apply in full. Characteristic modifiers join the
        # ability deltas inside the combat views and are uncapped, bound
        # only by the absolute limits (BS/WS 2+..6+, Sv 2+, AP <= 0);
        # re-rolls are limited by CAP_REROLLS ('fails' supersedes '1s').
        ttk.Label(body, text="Manual modifiers:").pack(anchor=tk.W, padx=4)
        mrow = ttk.Frame(body)
        mrow.pack(anchor=tk.W, padx=4)
        self.mod_target = ttk.Combobox(
            mrow, state="readonly", width=20,
            values=[t[0] for t in MOD_TARGETS])
        self.mod_target.set(MOD_TARGETS[0][0])
        self.mod_target.grid(row=0, column=0)
        self.mod_value = ttk.Entry(mrow, width=3)
        self.mod_value.grid(row=0, column=1, padx=3)
        ttk.Button(mrow, text="Add", width=5,
                   command=self.cmd_add_mod).grid(row=0, column=2)
        self.mod_hint_label = ttk.Label(body, text="",
                                        foreground=ui.HINT_COLOR)
        self.mod_hint_label.pack(anchor=tk.W, padx=4)
        self.mod_target.bind("<<ComboboxSelected>>",
                             lambda e: self._sync_mod_value())
        self._sync_mod_value()      # fills the value field and the hint
        self.mods = []               # [(label, kind, key, value)]
        mod_frame, self.mod_list = scrollable_listbox(
            body, height=5, exportselection=False)
        mod_frame.pack(fill=tk.X, padx=4, pady=2)
        ttk.Button(body, text="Remove",
                   command=self.cmd_remove_mod).pack(anchor=tk.W, padx=4)

        # Named bundles of the modifiers above, saved with the session.
        self.presets = mod_presets.PresetStore()
        prow = ttk.Frame(body)
        prow.pack(fill=tk.X, padx=4, pady=(4, 0))
        ttk.Label(prow, text="Preset:").pack(side=tk.LEFT)
        self.preset_box = ttk.Combobox(prow, state="readonly", width=18,
                                       values=[])
        self.preset_box.pack(side=tk.LEFT, padx=3)
        ttk.Button(prow, text="Apply", width=6,
                   command=self.cmd_apply_preset).pack(side=tk.LEFT)
        ttk.Button(prow, text="Save as...", width=10,
                   command=self.cmd_save_preset).pack(side=tk.LEFT, padx=3)
        ttk.Button(prow, text="Delete", width=7,
                   command=self.cmd_delete_preset).pack(side=tk.LEFT)
        self.preset_hint = ttk.Label(body, text="", foreground=ui.HINT_COLOR)
        self.preset_hint.pack(anchor=tk.W, padx=4)
        self.preset_box.bind("<<ComboboxSelected>>",
                             lambda _e: self._sync_preset_hint())

        ttk.Separator(body).pack(fill=tk.X, pady=4)
        # Ability selection: which of the attacker's optional abilities
        # are used, and which extra ones every attack gets.
        self.disabled_abilities = []      # switched off for this attack
        self.extra_abilities = []         # added to EVERY attack
        self.optimise_abilities = tk.BooleanVar(value=True)
        arow = ttk.Frame(body)
        arow.pack(anchor=tk.W, padx=4, pady=2)
        ttk.Button(arow, text="Attack abilities...",
                   command=self.cmd_pick_abilities).pack(side=tk.LEFT)
        ttk.Button(arow, text="Extra abilities...",
                   command=self.cmd_pick_extra).pack(side=tk.LEFT, padx=4)
        self.ability_label = ttk.Label(body, text="all abilities used",
                                       foreground=ui.HINT_COLOR)
        self.ability_label.pack(anchor=tk.W, padx=4)
        # Fills the preset combo and its hint ("no preset saved" until
        # the first one is stored).
        self._refresh_presets()
        # Last, once every child exists: the wheel has to be bound on the
        # widgets themselves, not on the container (see ScrollableFrame).
        self._scroll.bind_wheel()

    # ---------- manual modifiers ----------

    def _mod_target(self, label=None):
        """(kind, key) of a modifier target label, (None, None) when the
        label is not one of them."""
        label = self.mod_target.get() if label is None else label
        return next(((k, ky) for lab, k, ky in MOD_TARGETS if lab == label),
                    (None, None))

    def _mod_kind(self, label=None):
        """The kind ('rolls'|'rerolls'|'weapon'|...) of a modifier target
        label, or None when the label is not one of them."""
        return self._mod_target(label)[0]

    def _sync_mod_value(self):
        """Follow the selected target: re-rolls take no value, every
        other target starts from the sign that IMPROVES it. The field is
        reset on every change of target on purpose - the same number
        means the opposite thing on a roll and on a target number, so
        carrying it over would be worse than losing it."""
        kind, key = self._mod_target()
        self.mod_hint_label.config(text=mod_hint(kind, key))
        # The field must be enabled to be rewritten, so it is blanked
        # first and only then greyed out again.
        self.mod_value.config(state=tk.NORMAL)
        self.mod_value.delete(0, tk.END)
        if kind == "rerolls":
            self.mod_value.config(state=tk.DISABLED)
        else:
            self.mod_value.insert(0, mod_default_value(kind, key))

    def cmd_add_mod(self):
        label = self.mod_target.get()
        kind, key = next((k, ky) for lab, k, ky in MOD_TARGETS
                         if lab == label)
        if kind == "rerolls":
            # the value field is not used: key is (roll, '1'|'fails')
            mod = (label, kind, key, None)
            self.mods.append(mod)
            self.mod_list.insert(tk.END, mod_presets.describe(mod))
            return
        try:
            value = int(self.mod_value.get().replace("+", "").strip())
        except ValueError:
            messagebox.showerror("Modifier",
                                 "Value must be a signed integer (+/-N).")
            return
        if value == 0:
            return
        mod = (label, kind, key, value)
        self.mods.append(mod)
        self.mod_list.insert(tk.END, mod_presets.describe(mod))

    # ---------- modifier presets ----------

    def _refresh_mod_list(self):
        """Redraw the modifier listbox from self.mods."""
        self.mod_list.delete(0, tk.END)
        for mod in self.mods:
            self.mod_list.insert(tk.END, mod_presets.describe(mod))

    def _refresh_presets(self, select=None):
        names = self.presets.names()
        self.preset_box.configure(values=names)
        if select and select in names:
            self.preset_box.set(select)
        elif self.preset_box.get() not in names:
            self.preset_box.set(names[0] if names else "")
        self._sync_preset_hint()

    def _sync_preset_hint(self):
        name = self.preset_box.get()
        self.preset_hint.config(
            text=(mod_presets.summary(self.presets.get(name))
                  if name in self.presets else
                  "no preset saved" if not len(self.presets) else ""))

    def set_presets(self, data):
        """Replace the whole store (used when a session is loaded)."""
        self.presets = mod_presets.PresetStore(data)
        self._refresh_presets()

    def cmd_apply_preset(self):
        """Add the selected preset to the modifiers already listed."""
        name = self.preset_box.get()
        if name not in self.presets:
            return
        self.mods, added, skipped = mod_presets.apply_to(
            self.mods, self.presets.get(name))
        self._refresh_mod_list()
        if skipped and not added:
            messagebox.showinfo("Preset", f"'{name}' is already applied.")
        elif skipped:
            messagebox.showinfo(
                "Preset",
                f"Added {added} modifier(s); {skipped} were already "
                "in the list and were not added twice.")

    def cmd_save_preset(self):
        """Store the current modifier list under a name."""
        if not self.mods:
            messagebox.showinfo("Preset",
                                "Add some modifiers first, then save "
                                "them under a name.")
            return
        name = simpledialog.askstring("Save preset", "Preset name:",
                                      parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        if name in self.presets and not messagebox.askyesno(
                "Save preset", f"Overwrite '{name}'?"):
            return
        self.presets.save(name, self.mods)
        self._refresh_presets(select=name)

    def cmd_delete_preset(self):
        name = self.preset_box.get()
        if name not in self.presets:
            return
        if messagebox.askyesno("Delete preset", f"Delete '{name}'?"):
            self.presets.delete(name)
            self._refresh_presets()

    def cmd_remove_mod(self):
        sel = self.mod_list.curselection()
        if not sel:
            return
        del self.mods[sel[0]]
        self.mod_list.delete(sel[0])

    def get_battle_round(self) -> int:
        """The battle round as a number, clamped to the legal range.

        The Spinbox is editable by hand, so it can hold "", "abc" or 99;
        a condition asking "round >= 3" must not be decided by whatever
        the user was halfway through typing."""
        lo, hi = rules_config.BATTLE_ROUND_RANGE
        try:
            return max(lo, min(hi, int(self.battle_round.get())))
        except (TypeError, ValueError):
            return rules_config.BATTLE_ROUND_DEFAULT

    def _sync_overwatch(self):
        """The roll field is editable only while Overwatch is ticked."""
        self.overwatch_spin.configure(
            state=(tk.NORMAL if self.flag_vars["overwatch"].get()
                   else tk.DISABLED))

    def _sync_spotter(self):
        """Enable the spotter box only while indirect fire is selected."""
        self.set_flag_enabled("spotter", bool(self.flag_vars["indirect"]
                                              .get()))

    # ---------- ability selection ----------

    def _refresh_ability_label(self):
        bits = []
        if self.disabled_abilities:
            bits.append("off: " + ", ".join(self.disabled_abilities))
        if self.extra_abilities:
            bits.append("added: " + ", ".join(self.extra_abilities))
        if not self.optimise_abilities.get():
            bits.append("literal selection")
        self.ability_label.configure(
            text="; ".join(bits) if bits else "all abilities used")

    def cmd_pick_abilities(self):
        """Which of the attacker's optional abilities to use. Everything
        is used by default; unselect to switch an ability off."""
        chosen = _multi_select(
            self, "Attack abilities",
            "Abilities in use (unselect to switch off):",
            list(attack_math.OPTIONAL_ABILITIES),
            selected=[a for a in attack_math.OPTIONAL_ABILITIES
                      if a not in self.disabled_abilities],
            extra_check=("Optimise: decline an optional ability when it "
                         "costs damage", self.optimise_abilities),
            note="Lethal Hits and Devastating Wounds are competing: a "
                 "Lethal auto-wound is not a critical wound, so with "
                 "both in use Devastating never triggers. With Optimise "
                 "on, the better of the two is taken and reported.")
        if chosen is None:
            return
        self.disabled_abilities = [a for a in attack_math.OPTIONAL_ABILITIES
                                   if a not in chosen]
        self._refresh_ability_label()

    def cmd_pick_extra(self):
        """Abilities granted to EVERY attack (stratagems, auras, what-if)."""
        chosen = _multi_select(
            self, "Extra abilities",
            "Give these to every attack:",
            list(attack_math.ADDABLE_ABILITIES),
            selected=self.extra_abilities)
        if chosen is None:
            return
        self.extra_abilities = chosen
        self._refresh_ability_label()

    # ---------- accessors ----------

    def get_mode(self) -> str:
        """The selected attack mode: 'ranged', 'pistol', 'close_quarters'
        or 'melee'."""
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
        """The current context flags as a dict (in_cover, charged, etc.),
        plus the ability selection (see analyzer_core.ability_selection)."""
        out = {k: v.get() for k, v in self.flag_vars.items()}
        out["overwatch_value"] = self.overwatch_value.get()
        out["battle_round"] = self.get_battle_round()
        out["disabled_abilities"] = list(self.disabled_abilities)
        out["extra_abilities"] = list(self.extra_abilities)
        out["optimise_abilities"] = bool(self.optimise_abilities.get())
        return out

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


# Offered percentages, and the range a hand-set value is clamped to.
# The list is the control; the bounds exist because the value used to be
# typed and are kept as the guard on a value that reaches apply_font_scale
# from anywhere else.
FONT_SCALE_CHOICES = ("80", "90", "100", "125", "150", "175", "200")
FONT_SCALE_MIN, FONT_SCALE_MAX = 50, 300


def show_options_dialog(parent, caps=True, charts=False):
    """Global options: the font scale (accessibility), the session-wide
    modifier caps where the program actually computes attacks, and the
    chart placement where it draws any.

    'caps' is False in the profile editor. rules_config is process-wide
    state read by the attack maths, and the editor never runs any: a cap
    set there would be a control that silently does nothing. 'charts' is
    True in the analyzer alone, for the same reason."""
    win = tk.Toplevel(parent)
    win.title("Options")
    win.transient(parent)
    row = 0
    # Font size: applies to the whole application window, not to this
    # dialog's own settings, hence its place above the separator.
    ttk.Label(win, text="Font size (% of default):").grid(
        row=row, column=0, sticky=tk.W, padx=6, pady=(6, 2))
    font_var = tk.StringVar(value=str(int(round(_CURRENT_SCALE * 100))))
    ttk.Combobox(win, textvariable=font_var, state="readonly", width=6,
                 values=list(FONT_SCALE_CHOICES)).grid(
        row=row, column=1, padx=6, pady=(6, 2))
    row += 1

    embed = tk.BooleanVar(value=ui_prefs.EMBED_DISTRIBUTION)
    if charts:
        ttk.Checkbutton(
            win, variable=embed,
            text="Show the combined distribution in the result "
                 "window").grid(row=row, column=0, columnspan=2,
                                sticky=tk.W, padx=6, pady=2)
        row += 1
        ttk.Label(win, foreground=ui.HINT_COLOR, wraplength=320,
                  text="Off: double-click the TOTAL row for it.").grid(
            row=row, column=0, columnspan=2, sticky=tk.W, padx=6)
        row += 1

    entries = {}
    if caps:
        ttk.Separator(win, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky=tk.EW, padx=6, pady=6)
        row += 1
        ttk.Label(win, text="Modifier caps (empty = no cap):").grid(
            row=row, column=0, columnspan=2, sticky=tk.W, padx=6, pady=2)
        row += 1
        # Only the HIT and WOUND roll modifiers are capped in 11th ed.
        # Saves, invulns and FNP take their modifiers in full, and
        # characteristics are bounded by absolute limits, not by a cap.
        for label, cur in [("Hit/wound roll modifier cap",
                            rules_config.CAP_ROLL_MOD),
                           ("Re-roll cap (per die)",
                            rules_config.CAP_REROLLS)]:
            ttk.Label(win, text=label).grid(row=row, column=0, sticky=tk.W,
                                            padx=6, pady=2)
            e = ttk.Entry(win, width=6)
            e.insert(0, "" if cur is None else str(cur))
            e.grid(row=row, column=1, padx=6)
            entries[label] = e
            row += 1

    def apply():
        # Caps first: they are the part that can be rejected, and the
        # font must not have been rescaled under a dialog the user is
        # about to be sent back to.
        if caps:
            try:
                vals = [None if not e.get().strip() else int(e.get())
                        for e in entries.values()]
                if vals[1] is None or vals[1] < 0:
                    raise ValueError("re-roll cap must be an integer >= 0")
            except ValueError as exc:
                messagebox.showerror("Options", f"Invalid caps: {exc}")
                return
            rules_config.set_caps(roll=vals[0], rerolls=vals[1])
        if charts:
            ui_prefs.set_prefs(embed_distribution=embed.get())
        try:
            scale = max(FONT_SCALE_MIN,
                        min(FONT_SCALE_MAX, int(font_var.get()))) / 100.0
        except ValueError:              # readonly combobox: unreachable
            scale = None
        if scale is not None:
            apply_font_scale(parent.winfo_toplevel(), scale)
        win.destroy()

    ttk.Button(win, text="Apply", command=apply).grid(
        row=row, column=0, columnspan=2, pady=8)
