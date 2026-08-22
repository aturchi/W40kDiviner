#!/usr/bin/env python3
"""Attack analyzer (program 2).

Exact mean/median statistics of one attacking unit against one or more
defender units (multiple result popups can stay open for comparison).

Each army panel is split into a small "Leaders & joined" list and the
unit TREE. Selecting a leader greys out the units it cannot lead;
with a leader and a compatible unit selected, "Join" replaces them
with the combined unit (shown as [JOINED], shared abilities active).
Re-clicking a selected row deselects it.

A unit row expands into its models, their weapons and its abilities:
"Mask / unmask selected" switches a weapon (count 0, not fired) or an
ability off for the next analysis, and a weapon count is edited by
double-clicking it - the same gesture as the game assistant's table.
A MODEL row or a UNIT row switches every weapon below it at once (the
sergeant who does not shoot, the unit that stays silent this phase);
they leave the abilities alone. Note that this SILENCES models, it does
not remove them: the unit still fields them, and as a defender it is
still that many models. Any row shows how many of its rows are
switched off.
"Inspect" shows the full profile of the last selected unit, read-only.

Run:  python3 attack_analyzer.py
"""

import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter import font as tkfont

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "src"))

import native_format          # noqa: E402
import analyzer_core          # noqa: E402
import leader_core as lc      # noqa: E402
import inspect_dialog         # noqa: E402
import dist_stats             # noqa: E402
import dist_view              # noqa: E402
import result_rows            # noqa: E402
import comparison             # noqa: E402
import audit                  # noqa: E402
import session_io             # noqa: E402
from unit_model import units_from_native  # noqa: E402
from setup_panel import SetupPanel, show_options_dialog, show_font_dialog  # noqa: E402
from search_widget import attach_search    # noqa: E402
from ui_utils import (scrollable_listbox, multi_select_hint,  # noqa: E402
                      save_text)
from army_load_dialog import ArmyLoadDialog  # noqa: E402
from unit_tree import UnitTree              # noqa: E402


class AnalyzerApp(tk.Tk):
    """Attacker-vs-defender damage analyzer window: load armies, pick an
    attacker and defender (optionally joining leaders/supports), choose the
    attack mode and context, and view the per-weapon damage breakdown."""
    def __init__(self):
        super().__init__()
        self.title("W40k Attack Analyzer")
        self.geometry("1020x620")
        self.data = None             # native dict currently loaded
        self.units = []              # Unit objects from the loaded file
        # per-panel state: leaders/others/joined Unit lists + widgets
        self.panels = {}
        self._pre_click = {}         # (listbox, index) for click-toggle
        self._last_panel = None      # last panel clicked (for Inspect)
        # Result pages pinned for comparison. They live for the session
        # only: a pin is a frozen copy of the numbers, not a document.
        self.pins = []
        self._build_widgets()

    # ---------- UI ----------

    def _build_widgets(self):
        bar = ttk.Frame(self)
        bar.pack(side=tk.TOP, fill=tk.X)
        ttk.Button(bar, text="Load JSON",
                   command=self.cmd_load).pack(side=tk.LEFT, padx=3, pady=3)
        ttk.Button(bar, text="Save / load session",
                   command=self.cmd_session).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="Analyze",
                   command=self.cmd_analyze).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="Mask / unmask selected",
                   command=self.cmd_mask).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="Inspect",
                   command=self.cmd_inspect).pack(side=tk.LEFT, padx=3)
        self.compare_btn = ttk.Button(bar, text="Compare (0)",
                                      command=self.cmd_compare)
        self.compare_btn.pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="Options",
                   command=lambda: show_options_dialog(self)).pack(
            side=tk.LEFT, padx=3)
        ttk.Button(bar, text="Font size",
                   command=lambda: show_font_dialog(self)).pack(
            side=tk.LEFT, padx=3)
        self.status = ttk.Label(bar, text="No file loaded")
        self.status.pack(side=tk.LEFT, padx=10)

        main = ttk.Frame(self)
        main.pack(fill=tk.BOTH, expand=True)
        for key, title, multi in (("att", "Attacker", False),
                                  ("def", "Defenders (multi-select)",
                                   True)):
            col = ttk.LabelFrame(main, text=title)
            col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                     padx=4, pady=4)
            army = ttk.Combobox(col, state="readonly")
            army.pack(fill=tk.X, padx=4, pady=2)
            army.bind("<<ComboboxSelected>>",
                      lambda e, k=key: self._rebuild_panel(k))
            ttk.Label(col, text="Leaders & supports:").pack(
                anchor=tk.W, padx=4)
            lead_frame, lead_lb = scrollable_listbox(
                col, height=6, exportselection=False,
                selectmode=tk.EXTENDED)
            lead_frame.pack(fill=tk.X, padx=4)
            # The helper list takes several selections at once (a unit
            # with two Leader slots can be filled in one Join).
            multi_select_hint(col).pack(anchor=tk.W, padx=4)
            btn_row = ttk.Frame(col)
            btn_row.pack(anchor=tk.W, padx=4, pady=2)
            join_btn = ttk.Button(btn_row, text="Join",
                                  command=lambda k=key: self.cmd_join(k),
                                  state=tk.DISABLED)
            join_btn.pack(side=tk.LEFT)
            split_btn = ttk.Button(btn_row, text="Un-join",
                                   command=lambda k=key:
                                   self.cmd_unjoin(k))
            # packed only while a [JOINED] entry is selected
            ttk.Label(col, text="Units:").pack(anchor=tk.W, padx=4)
            # Free leader/support slots of the SELECTED target; blank
            # while no single target is selected.
            slots_lbl = ttk.Label(col, text="", foreground="#666666")
            slots_lbl.pack(anchor=tk.W, padx=4)
            # A tree, not a list: a unit expands into its models,
            # weapons and abilities, and masking a row switches it off -
            # the same gesture as the game assistant's table, instead of
            # a second way of doing it inside the Inspect window.
            unit_tree = UnitTree(
                col, multi=multi, height=14,
                on_select=lambda k=key: self._tree_select(k),
                on_change=self._refresh_tree_states)
            unit_tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
            p = {"army": army, "lead_lb": lead_lb, "unit_tree": unit_tree,
                 "join_btn": join_btn, "split_btn": split_btn,
                 "slots_lbl": slots_lbl,
                 "leaders": [], "supports": [], "others": [], "joined": []}
            self.panels[key] = p
            # Only the helper LIST needs these: the unit tree brings its
            # own click-toggle and selection callback.
            lead_lb.bind("<Button-1>",
                         lambda e, b=lead_lb: self._click_press(e, b),
                         add="+")
            lead_lb.bind("<ButtonRelease-1>",
                         lambda e, b=lead_lb, k=key:
                         self._click_release(e, b, k), add="+")
            lead_lb.bind("<<ListboxSelect>>",
                         lambda e, k=key: self._on_select(k))

        self.setup = SetupPanel(main,
                                on_mode_change=self._refresh_melee_choices)
        # 'damaged' is enabled only when a damageable attacker is selected.
        self.setup.set_flag_enabled("damaged", False)
        self.setup.pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=4)
        attach_search(self, lambda: [w for p in self.panels.values()
                                     for w in (p["lead_lb"],
                                               p["unit_tree"].tree)])

    # ---------- click-toggle (second click deselects) ----------

    def _click_press(self, event, lb):
        i = lb.nearest(event.y)
        self._pre_click[str(lb)] = i if i in lb.curselection() else None

    def _click_release(self, event, lb, key):
        self._last_panel = key
        i = lb.nearest(event.y)
        if i >= 0 and i == self._pre_click.get(str(lb)):
            lb.selection_clear(i)
            self._on_select(key)

    # ---------- data ----------

    def cmd_load(self):
        """Load one or more native JSON files. With several armies available,
        open the load/join dialog so the user can pick a subset and
        optionally merge armies before importing."""
        paths = filedialog.askopenfilenames(
            title="Load native JSON (one or more)",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not paths:
            return
        try:
            singles = native_format.split_armies(paths)
        except Exception as exc:
            messagebox.showerror("Load failed", str(exc))
            return
        if not singles:
            messagebox.showinfo("Load", "No armies found in the selection.")
            return
        if len(singles) > 1:
            # More than one army available: let the user pick a subset and
            # optionally join some of them into a new army before importing.
            dlg = ArmyLoadDialog(self, singles)
            self.wait_window(dlg)
            if dlg.result is None:
                return                       # cancelled
            data = dlg.result
        else:
            data = singles[0]
        try:
            self.units = units_from_native(data)
        except Exception as exc:
            messagebox.showerror("Load failed", str(exc))
            return
        self.data = data             # kept for the session file
        armies = sorted({u.army for u in self.units if u.army})
        for p in self.panels.values():
            p["army"].configure(values=armies)
            if armies:
                p["army"].set(armies[0])
        for key in self.panels:
            self._rebuild_panel(key)
        loaded = (paths[0] if len(paths) == 1
                  else f"{len(paths)} files")
        self.status.config(text=f"{len(self.units)} units, "
                                f"{len(armies)} armies | {loaded}")

    def _rebuild_panel(self, key):
        """Repopulate one panel from its army (joins are reset)."""
        p = self.panels[key]
        units = sorted([u for u in self.units
                        if u.army == p["army"].get()],
                       key=lambda u: u.name.lower())
        p["leaders"], rest = lc.split_leaders(units)
        p["supports"], p["others"] = lc.split_supports(rest)
        p["joined"] = []
        self._refresh_lists(key)

    def _refresh_lists(self, key):
        """lead_lb holds only leaders [L] and supports [S] (persistent,
        reusable). the unit TREE holds the joined entries [JOINED] first, then
        plain units. A join reads a helper from lead_lb and a target (unit
        OR joined entry) from the tree - nothing is consumed (exploratory
        analyzer)."""
        p = self.panels[key]
        p["lead_lb"].delete(0, tk.END)
        for u in p["leaders"]:
            p["lead_lb"].insert(tk.END, f"[L] {u.name}")
        for u in p["supports"]:
            p["lead_lb"].insert(tk.END, f"[S] {u.name}")
        rows = [(f"[JOINED] {combined.name}", combined)
                for combined, _lds, _u, _sps in p["joined"]]
        rows += [(u.name, u) for u in p["others"]]
        p["unit_tree"].set_units(rows)
        self._on_select(key)

    # ---------- selection, greying, join ----------

    def _lead_picks(self, p):
        """lead_lb selections as [(kind, obj, idx), ...]; kind is 'leader'
        or 'support', idx is the index within that pool. Stack order:
        leaders then supports."""
        out = []
        nl = len(p["leaders"])
        for i in p["lead_lb"].curselection():
            if i < nl:
                out.append(("leader", p["leaders"][i], i))
            else:
                out.append(("support", p["supports"][i - nl], i - nl))
        return out

    def _lead_pick(self, p):
        """First lead_lb selection (kind, obj, idx) or (None, None, None)."""
        picks = self._lead_picks(p)
        return picks[0] if picks else (None, None, None)

    def _unit_pick(self, p):
        """The single unit-tree selection as (kind, obj, idx): kind is
        'joined' (obj = the combined Unit, idx into p['joined']) or 'unit'
        (obj = the plain Unit, idx into p['others']). (None, None, None)
        when not exactly one is selected. The tree stacks joined then
        others."""
        sel = p["unit_tree"].selected_indices()
        if len(sel) != 1:
            return None, None, None
        i = sel[0]
        nj = len(p["joined"])
        if i < nj:
            return "joined", p["joined"][i][0], i
        return "unit", p["others"][i - nj], i - nj

    @staticmethod
    def _target_unit(p, i):
        """The Unit a top-level tree row stands for: the combined unit
        of a [JOINED] row, or the plain unit; joined rows come first."""
        nj = len(p["joined"])
        return p["joined"][i][0] if i < nj else p["others"][i - nj]

    def _update_slots(self, p):
        """Show how many leaders/supports the selected target can still
        take. Only meaningful for a single selection, so the label is
        blank otherwise."""
        sel = p["unit_tree"].selected_indices()
        if len(sel) != 1:
            p["slots_lbl"].config(text="")
            return
        u = self._target_unit(p, sel[0])
        free_l = u.slot_capacity("leader") - len(u.attached_leaders)
        free_s = u.slot_capacity("support") - len(u.attached_supports)
        p["slots_lbl"].config(
            text=f"Free slots - leaders: {max(0, free_l)}   "
                 f"supports: {max(0, free_s)}")

    def _on_select(self, key):
        p = self.panels[key]
        # Grey the top-level rows incompatible with the selected
        # helpers; the tree stacks joined entries first, then units.
        # A [JOINED] row can take another helper while the combined unit
        # still has a free slot for it; can_attach/can_support answer
        # capacity, keywords and duplicates in one go. With several
        # helpers selected a target stays black if ANY of them fits.
        picks = self._lead_picks(p)
        flags = []
        for i in range(p["unit_tree"].size()):
            u = self._target_unit(p, i)
            flags.append(bool(picks) and not any(
                u.can_attach(o) if k == "leader" else u.can_support(o)
                for k, o, _i in picks))
        p["unit_tree"].set_incompatible(flags)
        # Join enabled: at least one helper + one compatible target.
        tkind, _tobj, _ti = self._unit_pick(p)
        usel = p["unit_tree"].selected_indices()
        # Enabled as soon as a helper and a single target are selected:
        # whether each helper actually fits is decided (and explained) by
        # cmd_join, so the button is never a silent dead end.
        p["join_btn"].config(
            state=tk.NORMAL if picks and tkind is not None
            and len(usel) == 1 else tk.DISABLED)
        # Split (un-join) shows when a joined entry is selected.
        if tkind == "joined":
            p["split_btn"].pack(side=tk.LEFT, padx=4)
        else:
            p["split_btn"].pack_forget()
        self._update_slots(p)
        if key == "att":
            self._refresh_melee_choices()

    def cmd_join(self, key):
        """Join the selected helpers (leaders/supports in lead_lb, several
        at once) onto the selected target in the unit tree. It may be a
        plain unit (-> a new joined entry) or an existing joined entry
        with a free slot (-> the helpers are added to it), so a unit with
        two Leader slots is filled in one go or in two steps. Helpers that
        do not fit are skipped. Nothing is consumed: leaders, supports and
        units stay listed and reusable."""
        p = self.panels[key]
        picks = self._lead_picks(p)
        if not picks:
            return
        tkind, _tobj, ti = self._unit_pick(p)
        if tkind == "joined":
            combined, leaders, unit, supports = p["joined"][ti]
        elif tkind == "unit":
            combined, unit = p["others"][ti], p["others"][ti]
            leaders, supports = [], []
        else:
            return
        leaders, supports = list(leaders), list(supports)
        combined, taken, refused = lc.attach_all(
            combined, [(k, o) for k, o, _i in picks])
        for slot, obj in taken:
            (leaders if slot == "leader" else supports).append(obj)
        if refused:
            # Never fail silently: say which helper did not fit and why.
            messagebox.showinfo(
                "Join", "Not joined:\n- " + "\n- ".join(
                    f"{u.name}: {why}" for u, why in refused), parent=self)
        if not taken:
            return
        entry = (combined, leaders, unit, supports)
        if tkind == "joined":
            p["joined"][ti] = entry
        else:
            p["joined"].append(entry)
        self._refresh_lists(key)

    def cmd_unjoin(self, key):
        """Remove the selected [JOINED] entry. Its parts
        were never removed from the source lists, so just drop the combined
        entry."""
        p = self.panels[key]
        tkind, _obj, ti = self._unit_pick(p)
        if tkind != "joined":
            return
        p["joined"].pop(ti)
        self._refresh_lists(key)

    def _panel_selection(self, key):
        """The units this panel contributes to the analysis: EVERY row
        selected in the unit tree (joined combined units and plain units
        alike). The defender panel is multi-select, so more than one may
        come back; the attacker panel is BROWSE and yields at most one.
        The lead_lb helper is only an ingredient for joining, so it is
        used only as a fallback when no tree row is selected."""
        p = self.panels[key]
        sel = p["unit_tree"].selected_indices()
        if sel:
            return [self._target_unit(p, i) for i in sel]
        _k, u, _idx = self._lead_pick(p)
        return [u] if u is not None else []

    def _refresh_melee_choices(self):
        sel = self._panel_selection("att")
        att = sel[0] if sel else None
        # The "damaged" context flag only applies to units with a Damaged
        # bracket (damageable): enable the checkbox accordingly.
        self.setup.set_flag_enabled("damaged",
                                    bool(att and att.damageable))
        if self.setup.get_mode() == "melee" and att is not None:
            self.setup.set_melee_choices(
                analyzer_core.melee_choices(att.against(None)))
        else:
            self.setup.set_melee_choices(None)

    # ---------- masking ----------

    def cmd_mask(self):
        """Mask/unmask the selected rows in either panel. A weapon
        masked is a weapon not fired (count 0); an ability masked is
        switched off for the next analysis; a model or unit row does
        every weapon below it in one go, abilities excluded."""
        moved = sum(p["unit_tree"].toggle_selected()
                    for p in self.panels.values())
        if not moved:
            messagebox.showinfo(
                "Mask", "Nothing to switch off in the selected rows.\n\n"
                        "Select a weapon or an ability row (expand a unit "
                        "with the arrow on its left), or a model or unit "
                        "row to switch all its weapons at once.")

    def _refresh_tree_states(self):
        """After any masking, refresh BOTH panels: a joined unit is built
        on the very same weapon and ability objects as the plain unit it
        came from, so one change can show up in several rows - and the
        two panels may well hold the same army."""
        for p in self.panels.values():
            p["unit_tree"].refresh_states()

    def _tree_select(self, key):
        """A unit tree changed selection: remember the panel (Inspect
        follows it) and re-run the panel's own selection logic."""
        self._last_panel = key
        self._on_select(key)

    # ---------- inspect ----------

    def cmd_inspect(self):
        """Open the ability-inspect dialog for the selected unit (its combined
        form when a leader/support is joined)."""
        for key in ([self._last_panel] if self._last_panel else []) \
                + [k for k in ("att", "def") if k != self._last_panel]:
            sel = self._panel_selection(key)
            if sel:
                # Read-only, like the game assistant's: abilities and
                # weapon counts are now owned by the unit tree, and a
                # second editing path would fight with it.
                inspect_dialog.open_inspect(self, sel[0])
                return
        messagebox.showinfo("Inspect", "Select a unit first.")

    # ---------- session save / load ----------

    def cmd_session(self):
        """Single Save/load button: store the loaded armies, the army
        chosen in each panel and the joins already built, or restore a
        previously saved session."""
        session_io.run(self, "attack_analyzer", self._session_state,
                       self._apply_session, "Analyzer session")

    def _session_state(self):
        """State written to the session file (None aborts the save)."""
        if self.data is None:
            messagebox.showinfo("Session", "Load a roster first.")
            return None
        return {"data": self.data,
                # Named modifier bundles: they are typed in once and
                # reused every evening, so they belong to the session
                # and not to a single analysis.
                "mod_presets": self.setup.presets.to_json(),
                "panels": {key: {"army": p["army"].get(),
                                 "joined": session_io.joined_records(
                                     p["joined"])}
                           for key, p in self.panels.items()}}

    def _apply_session(self, state):
        """Rebuild the units from the embedded roster, then restore each
        panel's army and joins. Joins whose parts no longer exist (or no
        longer fit) are reported and skipped."""
        data = state.get("data")
        units = units_from_native(data)
        self.data, self.units = data, units
        # Absent in sessions written before presets existed: an empty
        # store is the right answer, not an error.
        self.setup.set_presets(state.get("mod_presets") or {})
        armies = sorted({u.army for u in self.units if u.army})
        panels = state.get("panels") or {}
        missing = []
        for key, p in self.panels.items():
            saved = panels.get(key) or {}
            p["army"].configure(values=armies)
            want = saved.get("army")
            p["army"].set(want if want in armies
                          else (armies[0] if armies else ""))
            self._rebuild_panel(key)          # resets the joined list
            p["joined"], gone = session_io.rebuild_joins(
                saved.get("joined"), p["leaders"], p["others"],
                p["supports"])
            missing += gone
            self._refresh_lists(key)
        self.status.config(text=f"{len(self.units)} units, "
                                f"{len(armies)} armies | session")
        if missing:
            messagebox.showwarning(
                "Session", "These joins could not be restored:\n"
                           + "\n".join(sorted(set(missing))))

    # ---------- analysis ----------

    def cmd_analyze(self):
        """Run the damage analysis for the selected attacker vs defender and
        show the per-weapon results."""
        a_sel = self._panel_selection("att")
        if not a_sel:
            messagebox.showinfo("Analyze", "Select an attacking unit.")
            return
        att = a_sel[0]
        d_units = self._panel_selection("def")
        if not d_units:
            messagebox.showinfo("Analyze", "Select at least one defender.")
            return
        mode = self.setup.get_mode()
        melee_name = self.setup.get_melee()
        if mode == "melee" and not melee_name:
            messagebox.showinfo("Analyze", "Select the melee weapon.")
            return
        flags = self.setup.get_flags()
        mods = self.setup.get_mods()
        for defender in d_units:
            self._analyze_one(att, defender, flags, mode, melee_name, mods)

    def _analyze_one(self, att, defender, flags, mode, melee_name, mods):
        """Analyze the attack against EVERY distinct defensive profile of
        the defender unit (a combined unit mixes bodyguard, leader and
        support models with different stats/keywords): one result page per
        profile, so no reference model has to be picked."""
        aview, dview = analyzer_core.build_views(att, defender, flags, mods)
        entries = []
        for label, ref in analyzer_core.reference_options(dview):
            results = analyzer_core.run_analysis(aview, dview, ref, flags,
                                                 mode, melee_name, mods)
            if not results["weapons"]:
                # The weapon selection does not depend on the reference,
                # so one empty result means all of them are empty.
                messagebox.showinfo("Analyze",
                                    f"No weapons match the '{mode}' "
                                    "selection.")
                return
            entries.append((label, ref, results))
        if entries:
            # What, besides the two units, shaped these numbers. Pinned
            # for the comparison window, where two analyses run under
            # different flags would otherwise look comparable.
            ctx = comparison.context_signature(flags, mods, mode)
            self._show_results(att, defender, entries, ctx)

    # ---------- results popup ----------

    def _show_results(self, att, defender, entries, context=""):
        """Result window for one defender. entries = [(label, ref,
        results)], one per distinct defensive profile. A single profile
        keeps the plain layout; several are stacked in a notebook with one
        tab per profile."""
        win = tk.Toplevel(self)
        win.title(f"{att.name}  vs  {defender.name}")
        win.geometry("980x520")
        heading = f"{att.name} vs {defender.name}"
        if len(entries) == 1:
            label, ref, results = entries[0]
            self._result_page(win, label, ref, results, heading, context)
            return
        ttk.Label(win, text=f"{defender.name}: {len(entries)} distinct "
                            "model profiles - one tab each (attack "
                            "resolved against that model)").pack(
            anchor=tk.W, padx=6, pady=(4, 0))
        nb = ttk.Notebook(win)
        nb.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        used = {}
        for label, ref, results in entries:
            # Tab title = model name (the part before the stat block),
            # numbered if two profiles share the same model name.
            short = label.split("  (")[0].strip() or "model"
            used[short] = used.get(short, 0) + 1
            if used[short] > 1:
                short = f"{short} #{used[short]}"
            page = ttk.Frame(nb)
            nb.add(page, text=short)
            self._result_page(page, label, ref, results, heading, context)

    def _result_page(self, parent, label, ref, results, heading="",
                     context=""):
        """Per-weapon table for one defensive profile, closed by a
        totals row. The rows themselves are built by result_rows, which
        knows what may be summed and what may not."""
        t = results["totals"]
        unit_w = max(1, int(ref.get("W") or 1) * int(ref.get("models") or 1))
        ttk.Label(parent, text=f"Defender profile: {label}  |  values are "
                               "exact (analytic)").pack(anchor=tk.W,
                                                        padx=6, pady=4)
        ttk.Label(parent, foreground="#666666", wraplength=940,
                  text="Effective = attacks that dealt damage (past the "
                       "save/invuln and FNP), not wound rolls.  Inflicted "
                       "= wounds actually taken off the unit, waste "
                       "deducted.  On a weapon row Inflicted and Kills "
                       "are that weapon ALONE against a full-strength "
                       "unit, so they do not add up to the totals, which "
                       "chain the weapons into the same unit.  Double-"
                       "click a weapon for its distribution."
                  ).pack(anchor=tk.W, padx=6, pady=(0, 4))

        tree = ttk.Treeview(parent, columns=result_rows.KEYS,
                            show="tree headings", height=11)
        tree.heading("#0", text="Weapon")
        tree.column("#0", width=230)
        for key, head, width in result_rows.COLUMNS:
            tree.heading(key, text=head)
            tree.column(key, width=width, anchor=tk.E)
        pmfs = {}                      # tree row -> that weapon's result
        for r in results["weapons"]:
            iid = tree.insert("", tk.END, text=r["name"],
                              values=result_rows.weapon_row(r))
            pmfs[iid] = r
        # Weapons excluded by the attack setup (indirect fire) are shown
        # greyed out with the reason instead of disappearing.
        tree.tag_configure("skipped", foreground="#888888")
        for r in results.get("skipped", []):
            tree.insert("", tk.END, text=r["name"], tags=("skipped",),
                        values=result_rows.skipped_row(r))
        base = tkfont.nametofont("TkDefaultFont")
        tree.tag_configure("totals", background="#eef2f7",
                           font=(base.cget("family"), base.cget("size"),
                                 "bold"))
        tree.insert("", tk.END, tags=("totals",),
                    text=result_rows.totals_label(results),
                    values=result_rows.totals_row(results))
        tree.pack(fill=tk.BOTH, expand=True, padx=6)

        note = (f"Target: {ref.get('models')} model(s) x W{ref.get('W')} "
                f"= {unit_w} wounds on this profile. Models killed assume "
                f"standard allocation (one model at a time, spilling "
                f"mortal wounds spent last): no precision, no visibility "
                f"rules, no opponent's choices.")
        self._totals_block(parent, t, unit_w, heading, label, note,
                           results, context)
        tree.bind("<Double-1>",
                  lambda e: self._open_weapon_dist(e, tree, pmfs, unit_w,
                                                   ref, heading, label,
                                                   note))
        if results["warnings"]:
            ttk.Label(parent, foreground="#a40",
                      text="Not modelled: "
                           + "; ".join(results["warnings"])[:300],
                      wraplength=940).pack(anchor=tk.W, padx=6, pady=2)

    def _totals_block(self, parent, t, unit_w, heading, label, note,
                      results=None, context=""):
        """What the totals row cannot hold: the spread of the wounds
        inflicted, the odds of wiping the unit out, and the way in."""
        eff = t.get("removed_pmf") or t["damage_net_pmf"]
        st = dist_stats.stats(eff)
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, padx=6, pady=(4, 2))
        ttk.Label(row, font=("TkDefaultFont", 10, "bold"), text=(
            f"Wounds inflicted  p10 {st['p10']}  |  median "
            f"{st['median']}  |  p90 {st['p90']}      "
            f"P(>= {unit_w}, the whole unit) = "
            f"{dist_stats.tail_prob(eff, unit_w) * 100:.1f}%")).pack(
            side=tk.LEFT)
        series = dist_view.result_series(eff, t["damage_pmf"],
                                         t.get("kills_pmf"), unit_w,
                                         t.get("models"))
        ttk.Button(row, text="Distribution...",
                   command=lambda: dist_view.open_distribution(
                       self, f"{heading} - all weapons", series,
                       note=f"{label}\n{note}")).pack(side=tk.RIGHT)
        if results is not None:
            ttk.Button(row, text="Export CSV...",
                       command=lambda: self._export_table(
                           f"{heading} - {label}", results)).pack(
                side=tk.RIGHT, padx=6)
            ttk.Button(row, text="Audit...",
                       command=lambda: self._open_audit(
                           f"{heading} - {label}", results)).pack(
                side=tk.RIGHT, padx=6)
            pin_btn = ttk.Button(row, text="Pin for comparison")
            pin_btn.configure(command=lambda: self._pin(
                f"{heading} [{label.split('(')[0].strip()}]", results,
                context, pin_btn))
            pin_btn.pack(side=tk.RIGHT, padx=6)
        if t.get("kills_pmf"):
            k = t["kills"]
            ttk.Label(parent, foreground="#25541f", text=(
                f"Models killed: median {k['median']}   |   "
                f"P(unit destroyed) = {t['p_wipe'] * 100:.1f}%"),
                font=("TkDefaultFont", 10, "bold")).pack(anchor=tk.W,
                                                         padx=6, pady=2)
            self._order_hint(parent, t)

    @staticmethod
    def _order_hint(parent, t):
        """Firing order: a weapon fires into the unit the previous ones
        left behind, so the order changes how much damage is wasted.
        Only shown when reordering is actually worth something."""
        if t.get("order_gain", 0.0) < 0.005 or not t.get("order"):
            return
        ttk.Label(parent, foreground="#7a4a00", wraplength=940, text=(
            f"Firing order: +{t['order_gain']:.2f} models by firing "
            + " -> ".join(t["order"])
            + "  (heuristic, not necessarily the best order)")).pack(
            anchor=tk.W, padx=6, pady=(0, 2))

    def _open_audit(self, title, results):
        """Why the numbers are what they are: the target numbers, the
        probabilities and the abilities that actually took part, weapon
        by weapon. Read-only, and copyable - the point is to be able to
        check it against the datasheet."""
        win = tk.Toplevel(self)
        win.title(f"Audit - {title}")
        win.geometry("860x560")
        ttk.Label(win, text=title,
                  font=("TkDefaultFont", 10, "bold")).pack(anchor=tk.W,
                                                           padx=6,
                                                           pady=(6, 0))
        ttk.Label(win, foreground="#666666", wraplength=820,
                  text="These are the numbers the analysis actually "
                       "used, not a re-derivation: if a flag is still "
                       "ticked from an earlier run, it shows up here."
                  ).pack(anchor=tk.W, padx=6, pady=(0, 4))
        frame = ttk.Frame(win)
        frame.pack(fill=tk.BOTH, expand=True, padx=6)
        text = tk.Text(frame, wrap=tk.NONE, height=24,
                       font=("TkFixedFont",))
        bar_y = ttk.Scrollbar(frame, orient=tk.VERTICAL,
                              command=text.yview)
        bar_x = ttk.Scrollbar(win, orient=tk.HORIZONTAL,
                              command=text.xview)
        text.configure(yscrollcommand=bar_y.set, xscrollcommand=bar_x.set)
        bar_y.pack(side=tk.RIGHT, fill=tk.Y)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        bar_x.pack(fill=tk.X, padx=6)
        body = audit.report(results) or "No weapon in this analysis."
        text.insert("1.0", body)
        text.configure(state=tk.DISABLED)
        row = ttk.Frame(win)
        row.pack(fill=tk.X, padx=6, pady=6)
        ttk.Button(row, text="Copy to clipboard",
                   command=lambda: self._copy(body)).pack(side=tk.LEFT)
        ttk.Button(row, text="Close",
                   command=win.destroy).pack(side=tk.RIGHT)

    def _export_table(self, title, results):
        """The table exactly as shown, as CSV. result_rows owns what a
        row contains and what the totals row may sum, so the file and
        the window cannot disagree."""
        name = "".join(ch if (ch.isalnum() or ch in "-_") else "_"
                       for ch in title).strip("_") or "analysis"
        save_text(self, result_rows.to_csv(results), title="Export table",
                  filetypes=[("CSV", "*.csv"), ("All files", "*.*")],
                  initialfile=name[:80] + ".csv")

    def _copy(self, body):
        self.clipboard_clear()
        self.clipboard_append(body)

    # ---------- pinning and comparison ----------

    def _pin(self, name, results, context, button=None):
        """Freeze this result page for the comparison window."""
        self.pins.append(comparison.make_pin(name, results, context))
        self._refresh_compare_btn()
        if button is not None:
            button.configure(text=f"Pinned (#{len(self.pins)})",
                             state=tk.DISABLED)

    def _refresh_compare_btn(self):
        self.compare_btn.configure(text=f"Compare ({len(self.pins)})")

    def cmd_compare(self):
        """Open the side-by-side comparison of the pinned analyses."""
        if len(self.pins) < 2:
            messagebox.showinfo(
                "Compare",
                "Pin at least two result pages first: run an analysis and "
                "use 'Pin for comparison' at the bottom of the result "
                "window.")
            return
        ComparisonWindow(self, self.pins, self._clear_pins)

    def _clear_pins(self):
        self.pins = []
        self._refresh_compare_btn()

    def _open_weapon_dist(self, event, tree, pmfs, unit_w, ref, heading,
                          label, note):
        """Distribution window for the double-clicked weapon row. The row
        is read from the click itself, so a double-click on the header or
        on empty space does nothing; skipped weapons carry no PMF and are
        ignored the same way."""
        r = pmfs.get(tree.identify_row(event.y))
        if not r:
            return
        series = dist_view.result_series(
            r.get("removed_pmf") or r["damage_net_pmf"], r["damage_pmf"],
            r.get("kills_pmf"), unit_w, ref.get("models"))
        dist_view.open_distribution(
            self, f"{heading} - {r['name']}", series,
            note=f"{label}\n{note}\nThis weapon alone, against a target "
                 f"unit at full strength.")


class ComparisonWindow(tk.Toplevel):
    """Pinned analyses side by side.

    Rows are metrics, columns are pins, and every column past the first
    carries its difference against the first - because the question is
    almost never 'how much damage' but 'what did that change do'. The
    context of each pin is shown above the numbers and flagged when it
    differs from the first, so a comparison between analyses run under
    different flags cannot pass unnoticed.
    """

    PMF_CHOICES = (("inflicted", "wounds inflicted"),
                   ("kills", "models killed"),
                   ("damage", "gross damage"))

    def __init__(self, parent, pins, on_clear=None):
        super().__init__(parent)
        self.pins, self._on_clear = list(pins), on_clear
        self.title(f"Comparison - {len(self.pins)} analyses")
        self.geometry("980x620")
        self._which = tk.StringVar(value="inflicted")
        self._build()

    def _build(self):
        ttk.Label(self, text="Every column past the first shows its "
                             "difference against the first one.",
                  foreground="#666666").pack(anchor=tk.W, padx=6, pady=(6, 2))
        cols = tuple(f"c{i}" for i in range(len(self.pins)))
        tree = ttk.Treeview(self, columns=cols, show="tree headings",
                            height=16)
        tree.heading("#0", text="Metric")
        tree.column("#0", width=190)
        for i, pin in enumerate(self.pins):
            tree.heading(cols[i], text=f"#{i + 1}")
            tree.column(cols[i], width=180, anchor=tk.W)
        base = tkfont.nametofont("TkDefaultFont")
        tree.tag_configure("head", background="#eef2f7",
                           font=(base.cget("family"), base.cget("size"),
                                 "bold"))
        tree.tag_configure("warn", foreground="#a40")
        for label, cells in comparison.context_rows(self.pins):
            tag = "warn" if (label == "vs first"
                             and "DIFFERENT" in cells) else "head"
            tree.insert("", tk.END, text=label, values=cells, tags=(tag,))
        for label, cells in comparison.matrix(self.pins):
            tree.insert("", tk.END, text=label, values=cells)
        tree.pack(fill=tk.BOTH, expand=True, padx=6)

        row = ttk.Frame(self)
        row.pack(fill=tk.X, padx=6, pady=4)
        ttk.Label(row, text="Curves:").pack(side=tk.LEFT)
        for key, text in self.PMF_CHOICES:
            ttk.Radiobutton(row, text=text, value=key,
                            variable=self._which,
                            command=self._refresh).pack(side=tk.LEFT,
                                                        padx=(2, 8))
        ttk.Button(row, text="Close", command=self.destroy).pack(
            side=tk.RIGHT, padx=3)
        ttk.Button(row, text="Clear pins",
                   command=self._clear).pack(side=tk.RIGHT, padx=3)
        ttk.Button(row, text="Export CSV...",
                   command=self._export).pack(side=tk.RIGHT, padx=3)

        self.canvas = dist_view.OverlayCanvas(self, height=200)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 6))
        self._refresh()

    def _refresh(self):
        key = self._which.get()
        series = comparison.overlay_series(self.pins, key)
        # The threshold only means something for the wounds curve: it is
        # the wounds of the first pin's target unit.
        thr = self.pins[0].get("unit_wounds") or None
        self.canvas.set_data(series, thr if key == "inflicted" else None)

    def _clear(self):
        if self._on_clear:
            self._on_clear()
        self.destroy()

    def _export(self):
        save_text(self, comparison.to_csv(self.pins),
                  title="Export comparison",
                  filetypes=[("CSV", "*.csv"), ("All files", "*.*")],
                  initialfile="comparison.csv")


if __name__ == "__main__":
    AnalyzerApp().mainloop()
