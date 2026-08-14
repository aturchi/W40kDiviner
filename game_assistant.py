#!/usr/bin/env python3
"""Game assistant (program 1).

Resolves attacks with real dice rolls during a game. Workflow:
load a JSON roster, pick the units of the two armies in the setup
popup (running points totals shown), then play: select attacker and
defender units in the two panels and press "Execute attack" - a popup
lists every damaging attack and the mortal wounds, so the player
allocates wounds to models manually.

Tracking aids: units, models and weapons (e.g. ONE SHOT) can be
masked (greyed out) and are then excluded from attack resolution; each
model row has an editable wounds box (double-click), initialised to
W x model count.

Run:  python3 game_assistant.py
"""

import os
import random
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "src"))

import native_format          # noqa: E402
import analyzer_core          # noqa: E402
import attack_math            # noqa: E402
import attack_resolve         # noqa: E402
from unit_model import units_from_native      # noqa: E402
from editor_widgets import PickerDialog       # noqa: E402
import leader_core as lc                      # noqa: E402
import inspect_dialog                         # noqa: E402
import session_io                             # noqa: E402
from search_widget import attach_search       # noqa: E402
from ui_utils import scrollable_listbox, multi_select_hint  # noqa: E402
from setup_panel import SetupPanel, show_options_dialog, show_font_dialog   # noqa: E402

MASK_TAG = "masked"
MASK_COLOR = "#999999"


class ArmySetupDialog(tk.Toplevel):
    """Pick the units of the two armies; shows running points totals.
    self.result = ([unit_dict, ...], [unit_dict, ...]) or None."""

    def __init__(self, parent, data):
        super().__init__(parent)
        self.title("Army setup")
        self.transient(parent)
        self.grab_set()
        self.result = None
        # picked[side] = list of (label, unit_dict), kept sorted by label.
        self.picked = {"A": [], "B": []}

        # Grid weights so the lists expand with the window (row 1 holds
        # the button bar and stays fixed).
        self.rowconfigure(0, weight=1)
        for c in (0, 1, 2):
            self.columnconfigure(c, weight=1)

        # ---- available units: a Treeview grouped by source army, each
        # army a collapsible node (useful with several armies in one
        # file). Armies and their units are shown alphabetically. ----
        src = ttk.LabelFrame(self, text="Available units")
        src.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=4, pady=4)
        self.src_tree = ttk.Treeview(src, show="tree", selectmode="extended",
                                     height=24)
        sb = ttk.Scrollbar(src, orient=tk.VERTICAL,
                           command=self.src_tree.yview)
        self.src_tree.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.src_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # "Add to A/B" takes the whole selection, so flag the modifier key.
        multi_select_hint(self, "Add to A/B takes every selected unit").grid(
            row=2, column=0, columnspan=3, sticky="w", padx=6, pady=(0, 4))
        self._tree_units = {}       # tree iid -> (label, unit_dict)
        for a in sorted(data["armies"], key=lambda x: str(x["name"]).lower()):
            parent_iid = self.src_tree.insert("", "end", text=a["name"],
                                              open=True)
            for u in sorted(a.get("units", []),
                            key=lambda x: str(x.get("name", "")).lower()):
                pts = u.get("points") or 0
                label = f"{a['name']} / {u['name']} ({pts} pts)"
                iid = self.src_tree.insert(parent_iid, "end",
                                           text=f"{u['name']} ({pts} pts)")
                self._tree_units[iid] = (label, u)

        self.dst_list, self.total_lbl = {}, {}
        for col, side in ((1, "A"), (2, "B")):
            frame = ttk.LabelFrame(self, text=f"Army {side}")
            frame.grid(row=0, column=col, sticky="nsew", padx=4, pady=4)
            ttk.Button(frame, text=f"Add to {side}",
                       command=lambda s=side: self.cmd_add(s)).pack(
                fill=tk.X, padx=3, pady=2)
            lb_frame, lb = scrollable_listbox(
                frame, width=40, height=18, exportselection=False)
            lb_frame.pack(fill=tk.BOTH, expand=True, padx=3)
            ttk.Button(frame, text="Remove",
                       command=lambda s=side: self.cmd_remove(s)).pack(
                fill=tk.X, padx=3, pady=2)
            lbl = ttk.Label(frame, text="Total: 0 pts",
                            font=("TkDefaultFont", 10, "bold"))
            lbl.pack(anchor=tk.W, padx=3, pady=2)
            self.dst_list[side], self.total_lbl[side] = lb, lbl

        bar = ttk.Frame(self)
        bar.grid(row=1, column=1, columnspan=2, sticky="e", padx=4, pady=4)
        ttk.Button(bar, text="OK", command=self.cmd_ok).pack(
            side=tk.RIGHT, padx=3)
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(
            side=tk.RIGHT)

    def _refresh(self, side):
        lb = self.dst_list[side]
        lb.delete(0, tk.END)
        total = 0
        for label, u in self.picked[side]:
            lb.insert(tk.END, label)
            total += u.get("points") or 0
        self.total_lbl[side].config(text=f"Total: {total} pts")

    def cmd_add(self, side):
        # A selected unit row is added directly; a selected army (parent)
        # row adds all its units. Picked units are kept alphabetical.
        for iid in self.src_tree.selection():
            if iid in self._tree_units:
                self.picked[side].append(self._tree_units[iid])
            else:
                for child in self.src_tree.get_children(iid):
                    self.picked[side].append(self._tree_units[child])
        self.picked[side].sort(key=lambda lu: lu[0].lower())
        self._refresh(side)

    def cmd_remove(self, side):
        sel = self.dst_list[side].curselection()
        if sel:
            del self.picked[side][sel[0]]
            self._refresh(side)

    def cmd_ok(self):
        if not self.picked["A"] or not self.picked["B"]:
            messagebox.showinfo("Army setup",
                                "Both armies need at least one unit.",
                                parent=self)
            return
        self.result = ([u for _label, u in self.picked["A"]],
                       [u for _label, u in self.picked["B"]])
        self.destroy()


class GameAssistantApp(tk.Tk):
    """Two-army game assistant window: set up both armies (with a unified
    leader/support join dialog), track per-model masking as models are
    removed, and resolve attacks between selected units."""
    def __init__(self):
        super().__init__()
        self.title("W40k Game Assistant")
        self.geometry("1180x640")
        self.rng = random.Random()
        self.fmt = "w40k-sim/4"
        self.rosters = {"A": [], "B": []}   # native unit dicts
        self.trees = {}
        self._pre_click = {}                # click-toggle bookkeeping
        self._build_widgets()

    # ---------- UI ----------

    def _build_widgets(self):
        bar = ttk.Frame(self)
        bar.pack(side=tk.TOP, fill=tk.X)
        ttk.Button(bar, text="Load JSON",
                   command=self.cmd_load).pack(side=tk.LEFT, padx=3, pady=3)
        ttk.Button(bar, text="Save / load session",
                   command=self.cmd_session).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="Options",
                   command=lambda: show_options_dialog(self)).pack(
            side=tk.LEFT, padx=3)
        ttk.Button(bar, text="Font size",
                   command=lambda: show_font_dialog(self)).pack(
            side=tk.LEFT, padx=3)
        ttk.Button(bar, text="Execute attack",
                   command=self.cmd_attack).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="Mask / unmask selected",
                   command=self.cmd_mask).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="Inspect",
                   command=self.cmd_inspect).pack(side=tk.LEFT, padx=3)
        ttk.Label(bar, text="Attacking army:").pack(side=tk.LEFT, padx=6)
        self.att_side = tk.StringVar(value="A")
        for s in ("A", "B"):
            ttk.Radiobutton(bar, text=s, value=s, variable=self.att_side,
                            command=self._refresh_melee).pack(side=tk.LEFT)
        self.status = ttk.Label(bar, text="No armies loaded")
        self.status.pack(side=tk.LEFT, padx=10)

        main = ttk.Frame(self)
        main.pack(fill=tk.BOTH, expand=True)
        for side in ("A", "B"):
            frame = ttk.LabelFrame(main, text=f"Army {side}")
            frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                       padx=4, pady=4)
            tree = ttk.Treeview(frame, columns=("wounds",),
                                show="tree headings")
            tree.heading("#0", text="Unit / model / weapon")
            tree.heading("wounds", text="Count/W")
            tree.column("#0", width=320)
            tree.column("wounds", width=80, anchor=tk.E)
            tree.tag_configure(MASK_TAG, foreground=MASK_COLOR)
            tree.tag_configure("sep", foreground="#bbbbbb")
            tree.pack(fill=tk.BOTH, expand=True)
            tree.bind("<Double-1>",
                      lambda e, s=side: self._edit_cell(e, s))
            tree.bind("<Button-1>",
                      lambda e, s=side: self._click_press(e, s), add="+")
            tree.bind("<ButtonRelease-1>",
                      lambda e, s=side: self._click_release(e, s),
                      add="+")
            tree.bind("<<TreeviewSelect>>",
                      lambda e, s=side: self._on_select(s))
            self.trees[side] = tree

        self.setup = SetupPanel(main, on_mode_change=self._refresh_melee)
        # 'damaged' is enabled only when a damageable attacker is selected.
        self.setup.set_flag_enabled("damaged", False)
        self.setup.pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=4)
        attach_search(self, lambda: list(self.trees.values()))

    # ---------- loading and trees ----------

    def cmd_load(self):
        """Load army files, run the two-army setup and join dialog, and build
        both rosters from the result."""
        paths = filedialog.askopenfilenames(
            title="Load native JSON (one or more)",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not paths:
            return
        try:
            data = native_format.load_many(paths)
        except Exception as exc:
            messagebox.showerror("Load failed", str(exc))
            return
        self.fmt = data.get("format", "w40k-sim/4")
        dlg = ArmySetupDialog(self, data)
        self.wait_window(dlg)
        if dlg.result is None:
            return
        import copy
        from leader_dialog import TwoArmyJoinDialog
        data_a = copy.deepcopy(dlg.result[0])
        data_b = copy.deepcopy(dlg.result[1])
        jd = TwoArmyJoinDialog(self, data_a, data_b, self.fmt)
        self.wait_window(jd)
        if jd.result is not None:
            self.rosters["A"], self.rosters["B"] = jd.result
        else:
            # dialog cancelled: no joins, every unit stands alone
            self.rosters["A"] = [lc.make_entry(u) for u in data_a]
            self.rosters["B"] = [lc.make_entry(u) for u in data_b]
        # Show units alphabetically; the roster list order defines the
        # tree iids, so sorting the list here keeps every index consistent.
        for side in ("A", "B"):
            self.rosters[side].sort(key=lambda e: lc.entry_label(e).lower())
        for side in ("A", "B"):
            self._fill_tree(side)
        pts = {s: sum(lc.entry_points(e) for e in self.rosters[s])
               for s in ("A", "B")}
        self.status.config(text=f"Army A: {len(self.rosters['A'])} units, "
                                f"{pts['A']} pts | Army B: "
                                f"{len(self.rosters['B'])} units, "
                                f"{pts['B']} pts")

    def _fill_tree(self, side):
        tree = self.trees[side]
        tree.delete(*tree.get_children())
        for ui, entry in enumerate(self.rosters[side]):
            uid = tree.insert("", tk.END, iid=f"u{ui}",
                              text=f"{lc.entry_label(entry)} "
                                   f"({lc.entry_points(entry)} pts)",
                              open=False)
            for mi, m in lc.entry_models(entry):
                count = m.get("model_count") or 1
                mid = tree.insert(uid, tk.END, iid=f"u{ui}m{mi}",
                                  text=f"{m['name']} x{count}")
                for wi, w in enumerate(m.get("weapons", [])):
                    one = " [ONE SHOT]" if any(
                        k.upper() == "ONE SHOT"
                        for k in w.get("keywords", [])) else ""
                    tree.insert(mid, tk.END, iid=f"u{ui}m{mi}w{wi}",
                                text=f"[{w['type'][0]}] {w['name']}{one}",
                                values=(w.get("count", 1),))
                # visual separator between the weapons and the models
                if m.get("weapons"):
                    tree.insert(mid, tk.END, iid=f"u{ui}m{mi}sep",
                                text="\u2500" * 8 + " models "
                                     + "\u2500" * 8,
                                tags=("sep",))
                # one selectable row per physical model: masking a copy
                # lowers the effective model_count by one (and the
                # weapon counts are scaled accordingly at resolution)
                for ci in range(count):
                    tree.insert(mid, tk.END, iid=f"u{ui}m{mi}c{ci}",
                                text=f"Model {ci + 1}",
                                values=(m.get("W") or 0,))

    @staticmethod
    def _parse_iid(iid):
        """'u3m1w2' / 'u3m1c0' -> (ui, mi, wi, ci), None where absent;
        all None for non-structural rows (separators)."""
        import re
        m = re.fullmatch(r"u(\d+)(?:m(\d+))?(?:w(\d+))?(?:c(\d+))?", iid)
        if m is None:
            return (None, None, None, None)
        return tuple(None if g is None else int(g) for g in m.groups())

    # ---------- masking and wounds ----------

    def cmd_mask(self):
        """Toggle the removed/masked state of the selected model group so it
        no longer contributes to the units output."""
        for side in ("A", "B"):
            tree = self.trees[side]
            for iid in tree.selection():
                if iid.endswith("sep"):
                    continue                # separators are decoration
                tags = set(tree.item(iid, "tags"))
                tags ^= {MASK_TAG}
                tree.item(iid, tags=tuple(tags))

    def _is_masked(self, side, iid):
        return MASK_TAG in self.trees[side].item(iid, "tags")

    # Treeview keeps a clicked row selected forever: re-clicking an
    # already-selected row deselects it (so single units can be
    # masked/unmasked without dragging a partner selection along).
    def _click_press(self, event, side):
        tree = self.trees[side]
        iid = tree.identify_row(event.y)
        self._pre_click[side] = iid if iid in tree.selection() else None

    def _click_release(self, event, side):
        tree = self.trees[side]
        iid = tree.identify_row(event.y)
        if iid and iid == self._pre_click.get(side):
            tree.selection_remove(iid)

    def _edit_cell(self, event, side):
        """Double-click on the value column edits a model copy's wounds
        (free text) or a weapon's count (non-negative integer)."""
        tree = self.trees[side]
        iid = tree.identify_row(event.y)
        if not iid or tree.identify_column(event.x) != "#1":
            return
        ui, mi, wi, ci = self._parse_iid(iid)
        is_weapon = wi is not None
        if ci is None and not is_weapon:
            return                          # unit / model-entry rows
        x, y, w, h = tree.bbox(iid, "#1")
        entry = tk.Entry(tree, width=8)
        entry.insert(0, str(tree.set(iid, "wounds")))
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set()

        def commit(_e=None):
            val = entry.get().strip()
            if is_weapon:
                try:
                    val = max(0, int(val))
                except ValueError:
                    entry.destroy()
                    return                  # invalid count: keep old value
            tree.set(iid, "wounds", val)
            entry.destroy()
        entry.bind("<Return>", commit)
        entry.bind("<FocusOut>", commit)

    def cmd_inspect(self):
        """Full profile popup of the unit selected in either panel
        (joined entries are shown combined, masks ignored). Abilities
        can be toggled on/off for the session via checkboxes."""
        for side in ("A", "B"):
            ui = self._selected_unit(side)
            if ui is None:
                continue
            entry = self.rosters[side][ui]
            unit = lc.build_entry_unit(entry, {}, set(), {}, self.fmt)
            # collect the native ability dicts of all parts (unit, leader,
            # support) so toggles act on the roster (session-persistent)
            pairs = [(scope, ab)
                     for scope, ab in lc.entry_ability_dicts(entry)]
            inspect_dialog.open_inspect(self, unit, ability_dicts=pairs)
            return
        messagebox.showinfo("Inspect", "Select a unit first.")

    # ---------- session save / load ----------

    def cmd_session(self):
        """Single Save/load button: store both rosters (joins, ability
        toggles) together with the table state - masked models/weapons
        and the edited wounds/count cells - or restore a saved session."""
        session_io.run(self, "game_assistant", self._session_state,
                       self._apply_session, "Game session")

    def _table_state(self, side):
        """{row iid: {'masked': True, 'wounds': text}} for every row that
        carries either. The iids are rebuilt identically by _fill_tree
        from the same roster, so they are stable keys."""
        tree = self.trees[side]
        out = {}

        def walk(parent):
            for iid in tree.get_children(parent):
                rec = {}
                if self._is_masked(side, iid):
                    rec["masked"] = True
                value = str(tree.set(iid, "wounds"))
                if value:
                    rec["wounds"] = value
                if rec:
                    out[iid] = rec
                walk(iid)

        walk("")
        return out

    def _restore_table(self, side, table):
        tree = self.trees[side]
        for iid, rec in (table or {}).items():
            if not tree.exists(iid):
                continue                    # roster changed: skip the row
            if rec.get("masked"):
                tree.item(iid, tags=tuple(set(tree.item(iid, "tags"))
                                          | {MASK_TAG}))
            if "wounds" in rec:
                tree.set(iid, "wounds", rec["wounds"])

    def _session_state(self):
        """State written to the session file (None aborts the save)."""
        if not self.rosters["A"] and not self.rosters["B"]:
            messagebox.showinfo("Session", "Set up the armies first.")
            return None
        return {"fmt": self.fmt,
                "attacking_side": self.att_side.get(),
                "rosters": self.rosters,
                "table": {s: self._table_state(s) for s in ("A", "B")}}

    def _apply_session(self, state):
        """Restore both rosters and the table state."""
        self.fmt = state.get("fmt", self.fmt)
        rosters = state.get("rosters") or {}
        for side in ("A", "B"):
            self.rosters[side] = list(rosters.get(side) or [])
            self._fill_tree(side)
            self._restore_table(side, (state.get("table") or {}).get(side))
        side = state.get("attacking_side")
        if side in ("A", "B"):
            self.att_side.set(side)
        self._refresh_melee()
        pts = {s: sum(lc.entry_points(e) for e in self.rosters[s])
               for s in ("A", "B")}
        self.status.config(text=f"Army A: {len(self.rosters['A'])} units, "
                                f"{pts['A']} pts | Army B: "
                                f"{len(self.rosters['B'])} units, "
                                f"{pts['B']} pts | session")

    # ---------- attack resolution ----------

    def _selected_unit(self, side):
        sel = self.trees[side].selection()
        if not sel:
            return None
        return self._parse_iid(sel[0])[0]

    def _masks_for(self, side, ui):
        """Table state for one unit: (masked_copies {mi: n},
        masked_weapons {(mi, wi)}, weapon_counts {(mi, wi): n}).
        A weapon-count cell is an override ONLY when it differs from
        the native count; untouched cells leave the proportional
        scaling (effective model count) to filter_native_unit."""
        tree = self.trees[side]
        masked_copies, masked_weapons, weapon_counts = {}, set(), {}
        entry_models = dict(lc.entry_models(self.rosters[side][ui]))
        for mid in tree.get_children(f"u{ui}"):
            _u, mi, _w, _c = self._parse_iid(mid)
            if mi is None:
                continue
            entry_masked = self._is_masked(side, mid)
            for child in tree.get_children(mid):
                _u2, _m2, wi, ci = self._parse_iid(child)
                if wi is not None:
                    if entry_masked or self._is_masked(side, child):
                        masked_weapons.add((mi, wi))
                        continue
                    try:
                        v = max(0, int(tree.set(child, "wounds")))
                    except ValueError:
                        continue            # free text: keep native count
                    native = entry_models[mi]["weapons"][wi] \
                        .get("count", 1)
                    if v != native:
                        weapon_counts[(mi, wi)] = v
                elif ci is not None and (entry_masked
                                         or self._is_masked(side, child)):
                    masked_copies[mi] = masked_copies.get(mi, 0) + 1
        return masked_copies, masked_weapons, weapon_counts

    def _build_unit(self, side, ui):
        """Unit object from the roster entry with masked parts removed
        (leader re-attached when both halves survive); None if nothing
        is left."""
        return lc.build_entry_unit(self.rosters[side][ui],
                                   *self._masks_for(side, ui), self.fmt)

    def _refresh_melee(self):
        side = self.att_side.get()
        ui = self._selected_unit(side)
        unit = self._build_unit(side, ui) if ui is not None else None
        # The "damaged" context flag is only meaningful for units with a
        # Damaged bracket (damageable): enable the checkbox accordingly.
        self.setup.set_flag_enabled("damaged",
                                    bool(unit and unit.damageable))
        if self.setup.get_mode() != "melee" or unit is None:
            self.setup.set_melee_choices(None)
            return
        names = analyzer_core.melee_choices(unit.against(None))
        self.setup.set_melee_choices(names)

    def _on_select(self, side):
        if side == self.att_side.get():
            self._refresh_melee()

    def cmd_attack(self):
        """Resolve an attack from the selected attacker onto the selected
        defender and display the outcome."""
        a_side = self.att_side.get()
        d_side = "B" if a_side == "A" else "A"
        a_ui = self._selected_unit(a_side)
        d_ui = self._selected_unit(d_side)
        if a_ui is None or d_ui is None:
            messagebox.showinfo("Attack", "Select the attacking unit in "
                                f"Army {a_side} and the defender in "
                                f"Army {d_side}.")
            return
        if self._is_masked(a_side, f"u{a_ui}") \
                or self._is_masked(d_side, f"u{d_ui}"):
            messagebox.showinfo("Attack", "A masked unit cannot take "
                                "part in an attack.")
            return
        attacker = self._build_unit(a_side, a_ui)
        defender = self._build_unit(d_side, d_ui)
        if attacker is None or defender is None:
            messagebox.showinfo("Attack", "All models of one unit are "
                                "masked.")
            return
        mode = self.setup.get_mode()
        melee_name = self.setup.get_melee()
        if mode == "melee" and not melee_name:
            messagebox.showinfo("Attack", "Select the melee weapon.")
            return
        flags, mods = self.setup.get_flags(), self.setup.get_mods()

        aview, dview = analyzer_core.build_views(attacker, defender,
                                                 flags, mods)
        opts = analyzer_core.reference_options(dview)
        if len(opts) > 1:
            # Only UNMASKED models reach this point (the defender is built
            # by _build_unit, which drops masked copies and never attaches
            # a fully masked leader/support). The profile the rules fix for
            # the wound roll - highest Toughness among the bodyguard models
            # - is shown in bold, but any profile can be chosen.
            sugg = analyzer_core.suggested_references(dview, opts)
            dlg = PickerDialog(self, f"Reference model in {defender.name}"
                               " (bold = rules default for the wound roll)",
                               opts, bold=[opts[i][1] for i in sugg])
            self.wait_window(dlg)
            if dlg.choice is None:
                return
            ref = dlg.choice
        else:
            ref = opts[0][1]

        weapons, skipped = analyzer_core.select_weapons_split(
            aview, mode, melee_name, bool(flags.get("indirect")))
        if not weapons:
            messagebox.showinfo("Attack",
                                f"No weapons match the '{mode}' selection.")
            return
        ctx = {k: flags.get(k) for k in ("half_range", "stationary",
                                         "charged", "cover",
                                         "plunging", "damaged",
                                         "indirect", "spotter")}
        attack_type = "Melee" if mode == "melee" else "Ranged"
        haz_damage = attack_math.hazardous_damage_per_fail(attacker.keywords)
        results = []
        for w in weapons:
            mech = analyzer_core.mechanics_for_attack(w, dview, attack_type,
                                                      mods, flags)
            hazardous = mech.hazardous and messagebox.askyesno(
                "Hazardous", f"Use the HAZARDOUS profile for {w.name}?")
            res = attack_resolve.resolve_weapon(w, ref, ctx, mech,
                                                self.rng, hazardous,
                                                haz_damage)
            results.append((w, hazardous, res))
        self._show_results(attacker, defender, ref, results, skipped)

    # ---------- results popup ----------

    def _show_results(self, attacker, defender, ref, results, skipped=()):
        win = tk.Toplevel(self)
        win.title(f"{attacker.name}  vs  {defender.name}")
        win.geometry("560x440")
        txt = tk.Text(win, wrap=tk.WORD)
        txt.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        txt.tag_configure("h", font=("TkDefaultFont", 10, "bold"))
        txt.tag_configure("mw", foreground="#a00000")
        inv = f" inv{ref['invuln']}+" if ref.get("invuln") else ""
        fnp = f" fnp{ref['fnp']}+" if ref.get("fnp") else ""
        txt.insert(tk.END, f"Reference defender: T{ref['T']} "
                           f"Sv{ref['Sv']}+ W{ref['W']}{inv}{fnp}\n\n")
        txt.tag_configure("skip", foreground="#888888")
        for w, why in skipped or ():
            # Not fired under the current attack setup (indirect fire):
            # listed anyway so the whole unit is accounted for.
            txt.insert(tk.END, f"{w.name} x{w.count} - {why}\n", "skip")
        if skipped:
            txt.insert(tk.END, "\n")
        warnings = set()
        for w, hazardous, res in results:
            label = w.name + (" [HAZARDOUS]" if hazardous else "")
            txt.insert(tk.END, f"{label} x{w.count} - "
                               f"{res['attacks']} attacks\n", "h")
            if not res["events"]:
                txt.insert(tk.END, "  no damage\n")
            for e in res["events"]:
                if e["kind"] == "mortal":
                    txt.insert(tk.END,
                               f"  MORTAL WOUNDS: {e['amount']}\n", "mw")
                else:
                    txt.insert(tk.END, f"  damage: {e['amount']}\n")
            if hazardous:
                txt.insert(tk.END, f"  Hazardous self-damage: "
                                   f"{res['self_damage']}\n",
                           "mw" if res["self_damage"] else None)
            txt.insert(tk.END, "\n")
            warnings |= set(res["warnings"])
        tot = sum(e["amount"] for _w, _h, r in results for e in r["events"])
        n_ev = sum(len(r["events"]) for _w, _h, r in results)
        txt.insert(tk.END, f"TOTAL: {n_ev} damaging attacks, "
                           f"{tot} damage to allocate\n", "h")
        if warnings:
            txt.insert(tk.END, "\nNot modelled: " + "; ".join(
                sorted(warnings)), "mw")
        txt.configure(state=tk.DISABLED)


if __name__ == "__main__":
    GameAssistantApp().mainloop()
