#!/usr/bin/env python3
"""Attack analyzer (program 2).

Exact mean/median statistics of one attacking unit against one or more
defender units (multiple result popups can stay open for comparison).

Each army panel is split into a small "Leaders & joined" list and the
units list. Selecting a leader greys out the units it cannot lead;
with a leader and a compatible unit selected, "Join" replaces them
with the combined unit (shown in the leaders list as [JOINED], shared
abilities active). Re-clicking a selected row deselects it; "Inspect"
shows the full profile of the last selected unit.

Run:  python3 attack_analyzer.py
"""

import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "src"))

import native_format          # noqa: E402
import analyzer_core          # noqa: E402
import leader_core as lc      # noqa: E402
import inspect_dialog         # noqa: E402
import session_io             # noqa: E402
from unit_model import units_from_native  # noqa: E402
from setup_panel import SetupPanel, show_options_dialog, show_font_dialog  # noqa: E402
from search_widget import attach_search    # noqa: E402
from ui_utils import scrollable_listbox     # noqa: E402
from army_load_dialog import ArmyLoadDialog  # noqa: E402

_GREY = "#aaaaaa"


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
        ttk.Button(bar, text="Inspect",
                   command=self.cmd_inspect).pack(side=tk.LEFT, padx=3)
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
            unit_frame, unit_lb = scrollable_listbox(
                col, height=14, exportselection=False,
                selectmode=tk.EXTENDED if multi else tk.BROWSE)
            unit_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)
            p = {"army": army, "lead_lb": lead_lb, "unit_lb": unit_lb,
                 "join_btn": join_btn, "split_btn": split_btn,
                 "leaders": [], "supports": [], "others": [], "joined": []}
            self.panels[key] = p
            for lb in (lead_lb, unit_lb):
                lb.bind("<Button-1>",
                        lambda e, b=lb: self._click_press(e, b), add="+")
                lb.bind("<ButtonRelease-1>",
                        lambda e, b=lb, k=key:
                        self._click_release(e, b, k), add="+")
                lb.bind("<<ListboxSelect>>",
                        lambda e, k=key: self._on_select(k))

        self.setup = SetupPanel(main,
                                on_mode_change=self._refresh_melee_choices)
        # 'damaged' is enabled only when a damageable attacker is selected.
        self.setup.set_flag_enabled("damaged", False)
        self.setup.pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=4)
        attach_search(self, lambda: [w for p in self.panels.values()
                                     for w in (p["lead_lb"],
                                               p["unit_lb"])])

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
        reusable). unit_lb holds the joined entries [JOINED] first, then the
        plain units. A join reads a helper from lead_lb and a target (unit
        OR joined entry) from unit_lb - nothing is consumed (exploratory
        analyzer)."""
        p = self.panels[key]
        p["lead_lb"].delete(0, tk.END)
        for u in p["leaders"]:
            p["lead_lb"].insert(tk.END, f"[L] {u.name}")
        for u in p["supports"]:
            p["lead_lb"].insert(tk.END, f"[S] {u.name}")
        p["unit_lb"].delete(0, tk.END)
        for combined, _l, _u, _s in p["joined"]:
            p["unit_lb"].insert(tk.END, f"[JOINED] {combined.name}")
        for u in p["others"]:
            p["unit_lb"].insert(tk.END, u.name)
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
        """The single unit_lb selection as (kind, obj, idx): kind is
        'joined' (obj = the combined Unit, idx into p['joined']) or 'unit'
        (obj = the plain Unit, idx into p['others']). (None, None, None)
        when not exactly one is selected. unit_lb stacks joined then
        others."""
        sel = p["unit_lb"].curselection()
        if len(sel) != 1:
            return None, None, None
        i = sel[0]
        nj = len(p["joined"])
        if i < nj:
            return "joined", p["joined"][i][0], i
        return "unit", p["others"][i - nj], i - nj

    def _on_select(self, key):
        p = self.panels[key]
        kind, obj, _idx = self._lead_pick(p)
        # Grey unit_lb rows incompatible with the selected helper. unit_lb
        # is joined entries first, then plain units; a joined row is a valid
        # target only if the helper's slot is free and compatible.
        njoined = len(p["joined"])
        for i in range(p["unit_lb"].size()):
            if i < njoined:
                combined, ld, unit, sup = p["joined"][i]
                if kind == "leader":
                    ok = ld is None and unit.can_attach(obj)
                elif kind == "support":
                    ok = sup is None and unit.can_support(obj)
                else:
                    ok = True
            else:
                u = p["others"][i - njoined]
                ok = (u.can_attach(obj) if kind == "leader"
                      else u.can_support(obj) if kind == "support"
                      else True)
            p["unit_lb"].itemconfig(i, foreground="" if ok else _GREY)
        # Join enabled: one helper + one compatible target selected.
        tkind, _tobj, _ti = self._unit_pick(p)
        usel = p["unit_lb"].curselection()
        target_ok = (tkind is not None and len(usel) == 1
                     and p["unit_lb"].itemcget(usel[0], "foreground")
                     != _GREY)
        p["join_btn"].config(
            state=tk.NORMAL if kind is not None and target_ok
            else tk.DISABLED)
        # Split (un-join) shows when a joined entry is selected in unit_lb.
        if tkind == "joined":
            p["split_btn"].pack(side=tk.LEFT, padx=4)
        else:
            p["split_btn"].pack_forget()
        if key == "att":
            self._refresh_melee_choices()

    def cmd_join(self, key):
        """Join the selected helper (leader/support in lead_lb) onto the
        selected target in unit_lb. Target may be a plain unit (-> new
        joined entry) or an existing joined entry with the matching slot
        free (-> add the helper to it). Nothing is consumed: leaders,
        supports and units stay listed and reusable."""
        p = self.panels[key]
        kind, obj, _idx = self._lead_pick(p)
        if kind not in ("leader", "support"):
            return
        tkind, _tobj, ti = self._unit_pick(p)
        if tkind == "joined":
            combined, ld, unit, sup = p["joined"][ti]
            if kind == "leader" and ld is None and unit.can_attach(obj):
                p["joined"][ti] = (combined.attach_leader(obj), obj, unit,
                                   sup)
            elif kind == "support" and sup is None \
                    and unit.can_support(obj):
                p["joined"][ti] = (combined.attach_support(obj), ld, unit,
                                   obj)
            else:
                return
        elif tkind == "unit":
            unit = p["others"][ti]
            if kind == "leader" and unit.can_attach(obj):
                p["joined"].append((unit.attach_leader(obj), obj, unit,
                                    None))
            elif kind == "support" and unit.can_support(obj):
                p["joined"].append((unit.attach_support(obj), None, unit,
                                    obj))
            else:
                return
        else:
            return
        self._refresh_lists(key)

    def cmd_unjoin(self, key):
        """Remove the selected [JOINED] entry (now in unit_lb). Its parts
        were never removed from the source lists, so just drop the combined
        entry."""
        p = self.panels[key]
        tkind, _obj, ti = self._unit_pick(p)
        if tkind != "joined":
            return
        p["joined"].pop(ti)
        self._refresh_lists(key)

    def _panel_selection(self, key):
        """The unit this panel contributes to the analysis: the selected
        target in unit_lb (a joined combined unit, or a plain unit). The
        lead_lb helper is only an ingredient for joining, so it is used
        only as a fallback when no unit_lb row is selected."""
        p = self.panels[key]
        tkind, tobj, _ti = self._unit_pick(p)
        if tobj is not None:
            return [tobj]
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

    # ---------- inspect ----------

    def cmd_inspect(self):
        """Open the ability-inspect dialog for the selected unit (its combined
        form when a leader/support is joined)."""
        for key in ([self._last_panel] if self._last_panel else []) \
                + [k for k in ("att", "def") if k != self._last_panel]:
            sel = self._panel_selection(key)
            if sel:
                pairs = inspect_dialog.ability_dicts_of_unit(sel[0])
                inspect_dialog.open_inspect(self, sel[0],
                                            ability_dicts=pairs)
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
            self._show_results(att, defender, entries)

    # ---------- results popup ----------

    def _show_results(self, att, defender, entries):
        """Result window for one defender. entries = [(label, ref,
        results)], one per distinct defensive profile. A single profile
        keeps the plain layout; several are stacked in a notebook with one
        tab per profile."""
        win = tk.Toplevel(self)
        win.title(f"{att.name}  vs  {defender.name}")
        win.geometry("780x470")
        if len(entries) == 1:
            label, ref, results = entries[0]
            self._result_page(win, label, ref, results)
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
            self._result_page(page, label, ref, results)

    def _result_page(self, parent, label, ref, results):
        """Per-weapon table plus totals for one defensive profile."""
        ttk.Label(parent, text=f"Defender profile: {label}  |  values are "
                               "exact (analytic)").pack(anchor=tk.W,
                                                        padx=6, pady=4)
        cols = ("count", "att_m", "w_mean", "w_med", "d_mean", "d_med",
                "self")
        heads = ("xN", "Attacks μ", "Wounds μ", "Wounds med",
                 "Damage μ", "Damage med", "Self-dmg μ")
        tree = ttk.Treeview(parent, columns=cols, show="tree headings",
                            height=10)
        tree.heading("#0", text="Weapon")
        tree.column("#0", width=240)
        for c, h in zip(cols, heads):
            tree.heading(c, text=h)
            tree.column(c, width=72, anchor=tk.E)
        for r in results["weapons"]:
            tree.insert("", tk.END, text=r["name"], values=(
                r["count"], f"{r['attacks']['mean']:.2f}",
                f"{r['wounds']['mean']:.2f}", r["wounds"]["median"],
                f"{r['damage']['mean']:.2f}", r["damage"]["median"],
                "" if r["self_damage_mean"] is None
                else f"{r['self_damage_mean']:.2f}"))
        tree.pack(fill=tk.BOTH, expand=True, padx=6)

        t = results["totals"]
        ttk.Label(parent, text=(
            f"TOTAL gross damage: mean {t['damage']['mean']:.2f}, "
            f"median {t['damage']['median']}   |   "
            f"net (per wound capped at W={ref['W']}): "
            f"mean {t['damage_net']['mean']:.2f}, "
            f"median {t['damage_net']['median']}"),
            font=("TkDefaultFont", 10, "bold")).pack(anchor=tk.W,
                                                     padx=6, pady=4)
        if results["warnings"]:
            ttk.Label(parent, foreground="#a40",
                      text="Not modelled: "
                           + "; ".join(results["warnings"])[:300],
                      wraplength=720).pack(anchor=tk.W, padx=6, pady=2)


if __name__ == "__main__":
    AnalyzerApp().mainloop()
