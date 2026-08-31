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
from tkinter import ttk, messagebox

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "src"))

import native_format          # noqa: E402
import analyzer_core          # noqa: E402
import ability_ids                            # noqa: E402
import leader_core as lc                      # noqa: E402
import tree_ids                               # noqa: E402
import inspect_dialog                         # noqa: E402
import session_io                             # noqa: E402
import attack_log                             # noqa: E402
import log_view                               # noqa: E402
import undo_stack                             # noqa: E402
import alloc_groups                            # noqa: E402
import attack_session                          # noqa: E402
import attack_session_view                     # noqa: E402
import defender_models                         # noqa: E402
import hazard_close                            # noqa: E402
import hazard_view                             # noqa: E402
from search_widget import attach_search       # noqa: E402
from roster_picker import ask_roster_files    # noqa: E402
from ui_utils import scrollable_listbox, multi_select_hint  # noqa: E402
import ui_utils as ui                          # noqa: E402
from setup_panel import (SetupPanel, show_options_dialog,   # noqa: E402
                         FLAGS)

MASK_TAG = "masked"
MASK_COLOR = "#999999"


class ArmySetupDialog(tk.Toplevel):
    """Pick the units of the two armies; shows running points totals.
    self.result = ([unit_dict, ...], [unit_dict, ...]) or None."""

    def __init__(self, parent, data):
        super().__init__(parent)
        self.title("Army setup")
        self.transient(parent)
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
            ui.tip(ttk.Button(frame, text=f"Add to {side}",
                              command=lambda s=side: self.cmd_add(s)),
                   f"Put every unit selected on the left into army {side}"
                   ).pack(fill=tk.X, padx=3, pady=2)
            lb_frame, lb = scrollable_listbox(
                frame, width=40, height=18, exportselection=False)
            lb_frame.pack(fill=tk.BOTH, expand=True, padx=3)
            ui.tip(ttk.Button(frame, text="Remove",
                              command=lambda s=side: self.cmd_remove(s)),
                   "Take the selected units out of this army"
                   ).pack(fill=tk.X, padx=3, pady=2)
            lbl = ttk.Label(frame, text="Total: 0 pts",
                            font=ui.bold_font())
            lbl.pack(anchor=tk.W, padx=3, pady=2)
            self.dst_list[side], self.total_lbl[side] = lb, lbl

        bar = ttk.Frame(self)
        bar.grid(row=1, column=1, columnspan=2, sticky="e", padx=4, pady=4)
        ttk.Button(bar, text="OK", command=self.cmd_ok).pack(
            side=tk.RIGHT, padx=3)
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(
            side=tk.RIGHT)
        ui.modal_grab(self)

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
        # History of the attacks resolved this game (see attack_log):
        # written by cmd_attack, saved with the session.
        self.log = attack_log.AttackLog()
        self.log_win = None
        # Undo history of the table edits (masking, wounds/count cells).
        # Not saved with the session: see undo_stack.
        self.undo = undo_stack.UndoStack()
        self._build_widgets()

    # ---------- UI ----------

    def _build_widgets(self):
        bar = ttk.Frame(self)
        bar.pack(side=tk.TOP, fill=tk.X)
        ui.tip(ttk.Button(bar, text="Load JSON", command=self.cmd_load),
               "Pick one or more roster JSON files, then choose the units "
               "of the two armies"
               ).pack(side=tk.LEFT, padx=3, pady=3)
        ui.tip(ttk.Button(bar, text="Save / load session",
                          command=self.cmd_session),
               "Store or restore the whole game: rosters, wounds, masking "
               "and the attack log"
               ).pack(side=tk.LEFT, padx=3)
        ui.tip(ttk.Button(bar, text="Options",
                          command=lambda: show_options_dialog(self)),
               "Font scale and the caps on modifiers and re-rolls, for "
               "this session").pack(side=tk.LEFT, padx=3)
        ui.tip(ttk.Button(bar, text="Execute attack",
                          command=self.cmd_attack),
               "Roll the selected attacker against the selected defender, "
               "one weapon at a time"
               ).pack(side=tk.LEFT, padx=3)
        ui.tip(ttk.Button(bar, text="Mask / unmask selected",
                          command=self.cmd_mask),
               "Switch the selected models, weapons or abilities off: "
               "casualties, spent one-use weapons, abilities already used"
               ).pack(side=tk.LEFT, padx=3)
        ui.tip(ttk.Button(bar, text="Inspect", command=self.cmd_inspect),
               "Read-only full profile of the selected unit, with the "
               "printable cheat sheet").pack(side=tk.LEFT, padx=3)
        self.log_btn = ttk.Button(bar, text="Attack log (0)",
                                  command=self.cmd_log)
        ui.tip(self.log_btn,
               "Every attack of the game, by turn, with export to CSV or "
               "text")
        self.log_btn.pack(side=tk.LEFT, padx=3)
        ttk.Label(bar, text="Attacking army:").pack(side=tk.LEFT, padx=6)
        self.att_side = tk.StringVar(value="A")
        for s in ("A", "B"):
            ttk.Radiobutton(bar, text=s, value=s, variable=self.att_side,
                            command=self._refresh_melee).pack(side=tk.LEFT)
        self.status = ttk.Label(bar, text="No armies loaded")
        self.status.pack(side=tk.LEFT, padx=10)
        # Undo/redo on the right, so the label growing with the name of
        # the pending action cannot push the status text around.
        self.redo_btn = ttk.Button(bar, text="Redo", state=tk.DISABLED,
                                   command=self.cmd_redo)
        ui.tip(self.redo_btn, "Put back the change just undone (Ctrl-Y)")
        self.redo_btn.pack(side=tk.RIGHT, padx=3, pady=3)
        self.undo_btn = ttk.Button(bar, text="Undo", state=tk.DISABLED,
                                   command=self.cmd_undo)
        ui.tip(self.undo_btn,
               "Take back the last change to wounds or masking (Ctrl-Z); "
               "the label to the left names it")
        self.undo_btn.pack(side=tk.RIGHT, padx=3)
        self.undo_lbl = ttk.Label(bar, foreground="#888888", text="")
        self.undo_lbl.pack(side=tk.RIGHT, padx=3)
        # Bound on the window, not with bind_all: a Ctrl-Z pressed in the
        # log window or in a results popup must not silently rewrite the
        # table behind it.
        self.bind("<Control-z>", self.cmd_undo)
        self.bind("<Control-Z>", self.cmd_redo)      # Ctrl-Shift-Z
        self.bind("<Control-y>", self.cmd_redo)

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
        paths = ask_roster_files(
            self, title="Load native JSON (one or more)")
        if not paths:
            return
        try:
            data = native_format.load_many(paths)
        except Exception as exc:
            messagebox.showerror("Load failed", str(exc))
            return
        # Stamp the missing (or colliding) ability ids in memory: the
        # table's ability rows key on them, and files merged from
        # several sources are only unique per source. Nothing is written
        # back to disk - only the profile editor saves ids.
        ability_ids.normalize(data)
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
        # The rows were just rebuilt: the recorded ids no longer point at
        # the same things, so the history goes with them.
        self.undo.clear()
        self._refresh_undo()
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
            uid = tree.insert("", tk.END, iid=tree_ids.unit_iid(ui),
                              text=f"{lc.entry_label(entry)} "
                                   f"({lc.entry_points(entry)} pts)",
                              open=False)
            for mi, m in lc.entry_models(entry):
                count = m.get("model_count") or 1
                mid = tree.insert(uid, tk.END,
                                  iid=tree_ids.model_iid(ui, mi),
                                  text=f"{m['name']} x{count}")
                for wi, w in enumerate(m.get("weapons", [])):
                    one = " [ONE SHOT]" if any(
                        k.upper() == "ONE SHOT"
                        for k in w.get("keywords", [])) else ""
                    tree.insert(mid, tk.END,
                                iid=tree_ids.weapon_iid(ui, mi, wi),
                                text=f"[{w['type'][0]}] {w['name']}{one}",
                                values=(w.get("count", 1),))
                # visual separator between the weapons and the models
                if m.get("weapons"):
                    tree.insert(mid, tk.END,
                                iid=tree_ids.models_sep_iid(ui, mi),
                                text="\u2500" * 8 + " models "
                                     + "\u2500" * 8,
                                tags=("sep",))
                # one selectable row per physical model: masking a copy
                # lowers the effective model_count by one (and the
                # weapon counts are scaled accordingly at resolution)
                for ci in range(count):
                    tree.insert(mid, tk.END,
                                iid=tree_ids.copy_iid(ui, mi, ci),
                                text=f"Model {ci + 1}",
                                values=(m.get("W") or 0,))
            self._fill_abilities(tree, ui, entry, uid)

    def _fill_abilities(self, tree, ui, entry, uid):
        """One row per ability of the entry (unit, leader and support
        parts alike), under the unit row. Masking a row switches the
        ability off, exactly as masking a model copy removes it. The row
        id carries the ability's key (its own id where available), so a
        row keeps pointing at its ability whatever else changes."""
        abilities = lc.entry_ability_keys(entry)
        if not abilities:
            return
        tree.insert(uid, tk.END, iid=tree_ids.abilities_sep_iid(ui),
                    text="\u2500" * 8 + " abilities " + "\u2500" * 8,
                    tags=("sep",))
        for key, scope, ab in abilities:
            # The flag on the roster dict is the single source of truth:
            # the row only mirrors it, so a session reload shows the
            # abilities exactly as they were switched.
            tags = () if ab.get("enabled", True) else (MASK_TAG,)
            tree.insert(uid, tk.END, iid=tree_ids.ability_iid(ui, key),
                        text=lc.entry_ability_label(scope, ab), tags=tags)

    @staticmethod
    def _parse_iid(iid):
        """'u3m1w2' / 'u3m1c0' -> (ui, mi, wi, ci), None where absent;
        all None for the rows that are not model-side (separators and
        ability rows). See tree_ids for the full grammar."""
        return tree_ids.parse(iid)

    # ---------- masking and wounds ----------

    def cmd_mask(self):
        """Toggle the removed/masked state of the selected rows: a model
        group or copy no longer contributes to the unit, a weapon is not
        fired, an ability is switched off (its 'enabled' flag).

        The whole selection is ONE undo step: masking five models is one
        gesture, and unwinding it row by row would be five Ctrl-Z for
        something the player did once."""
        changes, masked, touched = [], 0, []
        for side in ("A", "B"):
            for iid in self.trees[side].selection():
                if tree_ids.is_separator(iid):
                    continue                # separators are decoration
                new = not self._is_masked(side, iid)
                changes.append(undo_stack.change(side, iid, "masked",
                                                 not new, new))
                self._set_cell(side, iid, "masked", new)
                masked += 1 if new else 0
                ui = self._parse_iid(iid)[0]
                if new and ui is not None and (side, ui) not in touched:
                    touched.append((side, ui))
        if not changes:
            return
        verb = "mask" if masked * 2 >= len(changes) else "unmask"
        # Masking the last copy by hand is masking the unit, and it
        # belongs to the same gesture: one Ctrl-Z, not two. Only masking
        # is followed up - unmasking a copy of a dead unit is the
        # player putting a model back, and they say so themselves.
        for side, ui in touched:
            changes.extend(self._apply_derived_masks(side, ui))
        self.undo.push_changes(undo_stack.rows_label(verb, len(changes)),
                               changes)
        self._refresh_undo()

    def _set_cell(self, side, iid, field, value):
        """Write one table cell, returning False when the row is gone.

        The single path used both by the direct edits and by undo/redo,
        so the two cannot diverge - in particular an ability row must
        always write its 'enabled' flag onto the roster dict, whichever
        of the two moved it."""
        tree = self.trees.get(side)
        if tree is None or not tree.exists(iid):
            return False
        if field == "masked":
            tags = set(tree.item(iid, "tags"))
            tags = (tags | {MASK_TAG}) if value else (tags - {MASK_TAG})
            tree.item(iid, tags=tuple(tags))
            # An ability row masks nothing by itself: it carries the
            # 'enabled' flag of the roster dict, so the flag is written
            # here rather than read back at resolution time.
            ui, key = tree_ids.parse_ability(iid)
            if ui is not None and ui < len(self.rosters[side]):
                lc.set_entry_ability_enabled(self.rosters[side][ui], key,
                                             not value)
        elif field == "wounds":
            tree.set(iid, "wounds", value)
        else:
            return False
        return True

    # ---------- undo / redo ----------

    def cmd_undo(self, _event=None):
        self._move_history(undo=True)

    def cmd_redo(self, _event=None):
        self._move_history(undo=False)

    def _move_history(self, undo):
        """Apply one step of the history and show what it moved."""
        # A cell editor is open: Ctrl-Z belongs to the text being typed
        # (or to the search box), not to the table underneath it.
        if isinstance(self.focus_get(), tk.Entry):
            return
        act = self.undo.undo() if undo else self.undo.redo()
        if act is None:
            return
        touched = undo_stack.apply_action(act, self._set_cell, undo=undo)
        self._refresh_undo()
        for side in ("A", "B"):
            iids = [iid for s, iid in touched if s == side]
            if iids:
                self.trees[side].selection_set(iids)
                self.trees[side].see(iids[0])

    def _refresh_undo(self):
        """Button states and the name of the next action to be undone."""
        self.undo_btn.configure(
            state=(tk.NORMAL if self.undo.can_undo() else tk.DISABLED))
        self.redo_btn.configure(
            state=(tk.NORMAL if self.undo.can_redo() else tk.DISABLED))
        label = self.undo.undo_label()
        self.undo_lbl.configure(text=f"undo: {label}" if label else "")

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
        old = str(tree.set(iid, "wounds"))
        entry = tk.Entry(tree, width=8)
        entry.insert(0, old)
        entry.place(x=x, y=y, width=w, height=h)
        entry.focus_set()
        # Return commits and destroys the box, which then fires FocusOut:
        # without this guard the commit would run twice, the second time
        # on a widget that no longer exists.
        done = {"yet": False}

        def commit(_e=None):
            if done["yet"]:
                return
            done["yet"] = True
            val = entry.get().strip()
            if is_weapon:
                try:
                    val = str(max(0, int(val)))
                except ValueError:
                    entry.destroy()
                    return                  # invalid count: keep old value
            entry.destroy()
            if val == old:
                return
            self._set_cell(side, iid, "wounds", val)
            changes = [undo_stack.change(side, iid, "wounds", old, val)]
            # Typing 0 into a model copy's wounds is how a player
            # removes a model without going to the mask command, and
            # until now the model went on shooting. The mask rides in
            # the same undo action as the edit that implied it.
            #
            # Not gated on the row being a model copy: _derived_masks is
            # the one place that decides which rows the rule looks at,
            # and a second guard here would be a duplicate of that
            # decision - one that could disagree with it later.
            changes.extend(self._apply_derived_masks(side, ui))
            self.undo.push_changes(
                f"edit {tree.item(iid, 'text')}", changes)
            self._refresh_undo()
        entry.bind("<Return>", commit)
        entry.bind("<FocusOut>", commit)

    def cmd_inspect(self):
        """Full profile popup of the unit selected in either panel
        (joined entries are shown combined, masks ignored). Read-only:
        weapon counts and ability flags are edited in the table."""
        for side in ("A", "B"):
            ui = self._selected_unit(side)
            if ui is None:
                continue
            entry = self.rosters[side][ui]
            unit = lc.build_entry_unit(entry, {}, set(), {}, self.fmt)
            # Read-only here on purpose: the table owns both the weapon
            # counts (its cells act as overrides) and the ability flags
            # (one maskable row per ability), so a second editing path
            # would fight with them.
            inspect_dialog.open_inspect(self, unit)
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
            # An ability row carries its state on the roster dict, which
            # the session restores separately; write it again from the
            # restored tag so the two can never disagree (a session
            # saved before the ability rows existed has no flag at all).
            ui, key = tree_ids.parse_ability(iid)
            if ui is not None:
                lc.set_entry_ability_enabled(self.rosters[side][ui], key,
                                             not rec.get("masked"))

    def _session_state(self):
        """State written to the session file (None aborts the save)."""
        if not self.rosters["A"] and not self.rosters["B"]:
            messagebox.showinfo("Session", "Set up the armies first.")
            return None
        return {"fmt": self.fmt,
                "attacking_side": self.att_side.get(),
                "rosters": self.rosters,
                # Named modifier bundles, same store the analyzer keeps
                # (see mod_presets): typed in once, reused every game.
                "mod_presets": self.setup.presets.to_json(),
                # The attack history belongs to the game, not to the
                # window: reopening a session mid-game must not lose it.
                "attack_log": self.log.to_json(),
                "table": {s: self._table_state(s) for s in ("A", "B")}}

    def _apply_session(self, state):
        """Restore both rosters and the table state."""
        self.fmt = state.get("fmt", self.fmt)
        # Absent in sessions written before presets existed: an empty
        # store is the right answer, not an error.
        self.setup.set_presets(state.get("mod_presets") or {})
        # Absent in sessions written before the log existed: an empty
        # log, same as for the presets above.
        self.log = attack_log.AttackLog(state.get("attack_log"))
        self._sync_log_window()
        rosters = state.get("rosters") or {}
        for side in ("A", "B"):
            self.rosters[side] = list(rosters.get(side) or [])
            self._fill_tree(side)
            self._restore_table(side, (state.get("table") or {}).get(side))
        self.undo.clear()                   # rebuilt table, see cmd_load
        self._refresh_undo()
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
        """Roster index of the selected unit, whatever kind of row of it
        is selected (unit, model, weapon, copy or ability)."""
        sel = self.trees[side].selection()
        if not sel:
            return None
        return tree_ids.entry_index(sel[0])

    # ---------- masks that follow from the table ----------

    def _copy_is_gone(self, side, iid) -> bool:
        """A model copy whose wounds cell says it is destroyed.

        The cell holds FREE TEXT for model copies - a player may write
        "fled" or "-" in it - so only a cell that reads as a number is
        judged. Anything else is left alone: guessing that "gone?" means
        zero would remove a model the player still has on the board.
        """
        try:
            return int(self.trees[side].set(iid, "wounds")) <= 0
        except ValueError:
            return False

    def _derived_masks(self, side, ui) -> list:
        """The masks that FOLLOW from the table rather than from a
        gesture, as undo changes the caller appends to its own action.

        Two rules, and both are one-way:

          * a model copy at zero wounds is a model that has been
            removed, and until now it went on shooting - _masks_for
            reads the mask, not the wounds cell, so a squad wiped out by
            hand kept its full firepower;
          * a unit with no model copy left standing is a unit that is
            gone, and its own row is masked so that cmd_attack refuses
            to let it fight.

        NOT symmetric, by decision: raising the wounds above zero again
        does not bring the model back. Undoing the edit does, because
        the derived change rides in the SAME undo action as the edit
        that caused it - which is also why this cannot live in
        _set_cell, the one path undo itself replays.

        "No model left" is evaluated the way _masks_for evaluates it: a
        masked model GROUP takes all of its copies with it, so a squad
        masked at group level counts as destroyed here too.
        """
        tree = self.trees[side]
        unit_iid = tree_ids.unit_iid(ui)
        if not tree.exists(unit_iid):
            return []
        changes, standing, copies_seen = [], 0, 0
        for mid in tree.get_children(unit_iid):
            _u, mi, _w, _c = self._parse_iid(mid)
            if mi is None:
                continue
            group_masked = self._is_masked(side, mid)
            for cid in tree.get_children(mid):
                if self._parse_iid(cid)[3] is None:
                    continue                # a weapon or an ability row
                copies_seen += 1
                if group_masked or self._is_masked(side, cid):
                    continue
                if self._copy_is_gone(side, cid):
                    changes.append(undo_stack.change(
                        side, cid, "masked", False, True))
                else:
                    standing += 1
        if copies_seen and not standing and not self._is_masked(
                side, unit_iid):
            changes.append(undo_stack.change(side, unit_iid, "masked",
                                             False, True))
        return changes

    def _apply_derived_masks(self, side, ui) -> list:
        """_derived_masks, applied. The changes come back so the caller
        can put them in the same push_changes as whatever caused
        them."""
        changes = self._derived_masks(side, ui)
        for ch in changes:
            self._set_cell(side, ch["iid"], "masked", True)
        return changes

    def _masks_for(self, side, ui):
        """Table state for one unit: (masked_copies {mi: n},
        masked_weapons {(mi, wi)}, weapon_counts {(mi, wi): n}).
        A weapon-count cell is an override ONLY when it differs from
        the native count; untouched cells leave the proportional
        scaling (effective model count) to filter_native_unit."""
        tree = self.trees[side]
        masked_copies, masked_weapons, weapon_counts = {}, set(), {}
        entry_models = dict(lc.entry_models(self.rosters[side][ui]))
        for mid in tree.get_children(tree_ids.unit_iid(ui)):
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
        if self._is_masked(a_side, tree_ids.unit_iid(a_ui)) \
                or self._is_masked(d_side, tree_ids.unit_iid(d_ui)):
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
        # No reference model is chosen any more. Toughness is what the
        # UNIT fixes and the rules fix it for us (highest among the
        # bodyguard models); the Save, the invulnerable and Feel No Pain
        # belong to the model each attack is allocated to, and are read
        # off that model when its save is rolled. The popup that used to
        # ask for one profile asked the wrong question.
        unit_ref = defender_models.unit_reference(dview)
        rows, unreadable = self._unit_rows(d_side, d_ui)
        if not rows:
            messagebox.showinfo("Attack", "No defending model left to "
                                "allocate to (every model row is "
                                "masked, or their wounds cells hold "
                                "free text).")
            return
        if unreadable:
            messagebox.showinfo(
                "Attack",
                f"{unreadable} model rows hold free text instead of a "
                "number and are left out of the attack - allocate "
                "those by hand.")
        records, join = defender_models.records(
            rows, self.rosters[d_side][d_ui], dview)
        if join:
            messagebox.showwarning(
                "Attack", "The table and the combat view do not line "
                f"up ({join}). The defending profiles are taken from "
                "the datasheet, so any combat modifier on the defender "
                "is NOT applied.")

        weapons, skipped = analyzer_core.select_weapons_split(
            aview, mode, melee_name, bool(flags.get("indirect")))
        if not weapons:
            messagebox.showinfo("Attack",
                                f"No weapons match the '{mode}' selection.")
            return
        ctx = {k: flags.get(k) for k in ("half_range", "charged", "cover",
                                         "plunging", "damaged",
                                         "indirect",
                                         "overwatch", "overwatch_value")}
        # The ctx key has no side prefix, the flag behind it does.
        ctx["stationary"] = flags.get("attacker_stationary")
        # The indirect floor drops to 4+ only with the spotter AND the
        # attacker stationary; the rule is shared with the analyzer so
        # the two programs cannot drift apart on it.
        ctx["spotter"] = analyzer_core.spotter_ctx(flags)
        # Close quarters: only a MONSTER/VEHICLE attacker takes the -1,
        # and only with weapons that are not CLOSE-QUARTERS.
        ctx["close_quarters_penalty"] = (
            mode == "close_quarters"
            and analyzer_core.close_quarters_attacker(aview))
        attack_type = "Melee" if mode == "melee" else "Ranged"
        haz_damage = analyzer_core.hazardous_damage(aview)
        pairs, skipped = [], list(skipped)
        for w in weapons:
            mech = analyzer_core.mechanics_for_attack(w, dview, attack_type,
                                                      mods, flags, aview)
            # HUNTER X: the weapon may only be fired at units carrying
            # the named keyword (the restriction can come from the
            # datasheet or from an ability, so it is checked here).
            why = analyzer_core.hunter_skip_reason(mech, dview)
            if why:
                skipped.append((w, why))
                continue
            pairs.append((w, mech))
        if not pairs:
            messagebox.showinfo("Attack", "Every weapon was ruled out "
                                "by the attack setup.")
            return
        session = attack_session.AttackSession(
            [{"weapon": w, "mech": m} for w, m in pairs], unit_ref, ctx,
            records, self.rng, haz_damage,
            order=self._firing_order(pairs, unit_ref, records, ctx))
        attack_session_view.AttackSessionWindow(
            self, session, defender.name,
            lambda applied, hazardous: self._finish_attack(
                d_side, d_ui, session, applied, hazardous, attacker,
                defender, unit_ref, records, skipped, mode, melee_name,
                flags, (a_side, a_ui, aview)),
            skipped=[(f"{w.name} x{w.count}", why) for w, why in skipped],
            attacker_name=attacker.name)

    def _firing_order(self, pairs, unit_ref, records, ctx):
        """The order the weapons are offered in, best first.

        The chain behind the suggestion works on ONE (W, models) target,
        so it is given the first allocation group: the one that will
        actually absorb the damage. A suggestion only - the player
        reorders the queue, before the attack and between weapons - so
        the approximation never reaches a die. Falls back to the roster
        order if the analytic run fails: a worse order is a nuisance, a
        crashed attack is not.
        """
        try:
            groups = alloc_groups.build_groups(records)
            order = alloc_groups.default_order(groups, records)
            ref = dict(unit_ref)
            if groups:
                ref.update(groups[order[0]]["ref"])
            ref["models"] = sum(1 for r in records
                                if int(r.get("wounds") or 0) > 0)
            return analyzer_core.suggested_firing_order(pairs, ref, ctx)
        except Exception:                        # noqa: BLE001
            return list(range(len(pairs)))

    def _finish_attack(self, side, ui, session, applied, hazardous,
                       attacker, defender, unit_ref, records, skipped,
                       mode, melee_name, flags, source):
        """Everything that happens once the player is done: the table,
        the log, and what the attacking unit still owes."""
        name = lc.entry_label(self.rosters[side][ui])
        self._apply_allocation(side, ui, applied, name)
        entry = self._record_attack(
            attacker, defender, self._log_reference(unit_ref, records),
            self._log_results(session), self._log_skipped(session, skipped),
            mode, melee_name, flags)
        if applied and self.log.set_allocation(
                entry.get("seq"), attack_log.allocation_record(
                    [dict(r, after=r["wounds"]) for r in applied])):
            self._sync_log_window()
        if hazardous:
            self._close_hazardous(source, session, attacker,
                                  entry.get("seq"))

    def _close_hazardous(self, source, session, attacker, seq):
        """The HAZARDOUS step, once the attack itself is settled.

        Its own window and its own undo step, not a continuation of the
        allocation: the wounds land on the OTHER unit, and the player
        may reasonably accept the damage they dealt and still refuse -
        or defer - the damage they took.
        """
        a_side, a_ui, aview = source
        entry = self.rosters[a_side][a_ui]
        rows, _unreadable = self._unit_rows(a_side, a_ui)
        models, _join = defender_models.records(rows, entry, aview)
        if not models:
            messagebox.showinfo(
                "Hazardous",
                f"{attacker.name} owes {session.self_damage()} mortal "
                "wounds from HAZARDOUS, but it has no model row left to "
                "take them - allocate them by hand.")
            return
        surviving = []
        for row in rows:
            if row["mi"] not in surviving:
                surviving.append(row["mi"])
        by_index, _problem = defender_models.view_by_model_index(
            surviving, entry, aview)
        bearer_of, _lost = hazard_close.bearers(session.weapons, by_index)
        items = hazard_close.owed(session.records(), session.weapons,
                                  bearer_of, models)
        name = lc.entry_label(entry)
        hazard_view.HazardWindow(
            self, items, models, name,
            lambda hurt, record: self._apply_hazardous(
                a_side, a_ui, hurt, record, name, seq))

    def _apply_hazardous(self, side, ui, rows, record, name, seq):
        """Write the closing step back, and log it either way.

        'rows' is empty when the player skipped: the table is left
        alone, but the log still says what the tests cost, because the
        history is a record of the attack and not of what the player
        chose to do about it.
        """
        if rows:
            self._apply_allocation(side, ui, rows,
                                   f"{name} (hazardous)")
        if self.log.set_hazardous(seq, dict(record, applied=bool(rows))):
            self._sync_log_window()

    @staticmethod
    def _log_results(session):
        """The session's activations in the shape the log reads. The
        records already carry what a resolve result carries, so nothing
        is converted - only picked out."""
        out = []
        for rec in session.records():
            entry = session.weapons[rec["index"]]
            out.append((entry["weapon"], entry["hazardous"],
                        {"attacks": rec["attacks"],
                         "events": rec["events"],
                         "self_damage": rec["self_damage"],
                         "warnings": rec["warnings"]}))
        return out

    @staticmethod
    def _log_skipped(session, skipped):
        """The weapons the setup ruled out, plus the ones the player
        simply never fired: a log that showed only the first would read
        as though the whole unit had shot."""
        out = list(skipped)
        for index in session.queue():
            out.append((session.weapons[index]["weapon"], "not fired"))
        return out

    @staticmethod
    def _log_reference(unit_ref, records):
        """What to record as the profile attacked. Toughness is exact -
        the unit fixes it - but there is no single Save any more, so the
        FIRST allocation group's is recorded: the profile most of the
        attacks were resolved against. The per-model truth is in the
        allocation rows."""
        groups = alloc_groups.build_groups(records)
        ref = dict(unit_ref)
        if groups:
            ref.update(groups[alloc_groups.default_order(
                groups, records)[0]]["ref"])
        return ref

    # ---------- attack log ----------

    def _record_attack(self, attacker, defender, ref, results, skipped,
                       mode, melee_name, flags):
        """Append the attack just resolved to the game log. The context
        is recorded as words (the ticked flags and the modifier list, in
        the panel's own wording) because a log that only kept the
        numbers could not be argued with two turns later.

        Returns the entry: its 'seq' is what the results window carries
        so that an allocation applied later lands on the right attack."""
        entry = self.log.record(
            attacker.name, defender.name, ref, results,
            skipped=skipped, mode=mode,
            melee=melee_name if mode == "melee" else None,
            context=attack_log.context_lines(
                flags, self.setup.mods, dict(FLAGS)))
        self._sync_log_window()
        return entry

    def _refresh_log_btn(self):
        self.log_btn.configure(text=f"Attack log ({len(self.log)})")

    def _sync_log_window(self):
        """Refresh the button caption and the log window if it is open:
        both mirror the same log, and an open window must not go stale
        while attacks are resolved behind it."""
        self._refresh_log_btn()
        if self.log_win is not None and self.log_win.winfo_exists():
            self.log_win.log = self.log
            self.log_win.refresh()

    def cmd_log(self):
        """Open (or raise) the attack log window."""
        self.log_win = log_view.open_log(self, self.log,
                                         self._refresh_log_btn,
                                         self.log_win)

    def _unit_rows(self, side, ui):
        """The model copies of a unit still on the table, in table
        order: ([{'key', 'mi', 'label', 'wounds'}], unreadable).

        Either side: the defender, whose models the attack is allocated
        to, and the attacker, whose models the HAZARDOUS closing step
        lands on. Nothing here was ever specific to the defender.

        'key' is the tree row id, which is what comes back when the
        damage is written. Masked rows are models already removed and
        are left out; a wounds cell holding free text cannot be
        allocated to and is COUNTED, not silently dropped - otherwise
        the attack would quietly spread over fewer models than the unit
        has. What the profiles ARE is not decided here: that is the join
        with the combat view, and it lives in defender_models.
        """
        tree = self.trees[side]
        models = dict(lc.entry_models(self.rosters[side][ui]))
        out, unreadable = [], 0
        for mid in tree.get_children(tree_ids.unit_iid(ui)):
            _u, mi, _w, _c = self._parse_iid(mid)
            if mi is None or self._is_masked(side, mid) or mi not in models:
                continue
            for child in tree.get_children(mid):
                _u2, _m2, _wi, ci = self._parse_iid(child)
                if ci is None or self._is_masked(side, child):
                    continue
                try:
                    wounds = max(0, int(tree.set(child, "wounds")))
                except ValueError:
                    unreadable += 1
                    continue
                out.append({"key": child, "mi": mi, "wounds": wounds,
                            "label": f"{models[mi]['name']} - "
                                     f"{tree.item(child, 'text')}"})
        return out, unreadable

    def _apply_allocation(self, side, ui, rows, name):
        """Write the accepted allocation into the table: the new wounds,
        and the mask that removes a destroyed model. One undo step for
        the lot - a misapplied attack is exactly what Ctrl-Z is for.

        The same rows go into the attack log, which is how the running
        summary can say what was REMOVED and not only what was rolled.
        Ctrl-Z puts the table back but does NOT rewrite the log: the
        history says what was applied at the table, and correcting it
        is a deliberate act (delete the attack in the log window)."""
        tree, changes = self.trees[side], []
        for r in rows:
            iid = r.get("key")
            if not iid or not tree.exists(iid):
                continue
            old = str(tree.set(iid, "wounds"))
            new = str(r["wounds"])
            if new != old:
                changes.append(undo_stack.change(side, iid, "wounds",
                                                 old, new))
                self._set_cell(side, iid, "wounds", new)
        # The rows carry 'dead', but the wounds just written say the
        # same thing - a destroyed model is a model at zero - and the
        # unit row is nobody's row at all: only the table as a whole
        # says whether anything is left standing. So the masks are
        # derived from the table once, here, rather than half from the
        # rows and half from the table with two rules to keep in step.
        changes.extend(self._apply_derived_masks(side, ui))
        if changes:
            self.undo.push_changes(f"apply damage to {name}", changes)
            self._refresh_undo()


if __name__ == "__main__":
    GameAssistantApp().mainloop()
