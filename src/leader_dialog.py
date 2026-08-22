"""Leader / support association dialog (game assistant).

Shown once per army per pass after army setup, when at least one helper
(leader or support) exists AND at least one unit is compatible with some
helper. Selecting a helper greys out the incompatible units; "Join" pairs
the two selections, "Remove" splits a pair back.

The dialog is parametric in 'mode':
  * mode="leader"  -> fills the leader slot (native_can_attach)
  * mode="support" -> fills the support slot (native_can_support)
It operates on leader_core ENTRIES so the two passes chain: the leader
pass produces entries, the support pass adds a support to those entries.
self.result = list of leader_core entries.
"""

import tkinter as tk
from tkinter import ttk, messagebox

import leader_core as lc
from ui_utils import scrollable_listbox, multi_select_hint

_GREY = "#aaaaaa"


class JoinDialog(tk.Toplevel):
    """Generic helper-assignment dialog. 'helpers' and 'targets' are
    leader_core entries; a helper entry is one whose base unit can lead
    (mode='leader') or support (mode='support'). Joining sets the helper's
    base unit into the matching slot of the target entry."""

    def __init__(self, parent, army_name, helpers, targets, fmt,
                 mode="leader"):
        super().__init__(parent)
        self.mode = mode
        self.slot = mode                    # 'leader' | 'support'
        self.fmt = fmt
        title_word = mode.capitalize()
        self.title(f"{title_word} assignment - {army_name}")
        self.transient(parent)
        self.grab_set()
        self.helpers = list(helpers)        # entries
        self.targets = list(targets)        # entries
        self.joined = []                    # [(helper_entry, target_entry)]
        self.result = None

        titles = [(f"{title_word}s", 14), ("Units", 14), ("Joined", 14)]
        for col, (title, h) in enumerate(titles):
            frame = ttk.LabelFrame(self, text=title)
            frame.grid(row=0, column=col, sticky="nsew", padx=4, pady=4)
            self.columnconfigure(col, weight=1)
            lb_frame, lb = scrollable_listbox(
                frame, width=38, height=h, exportselection=False)
            lb_frame.pack(fill=tk.BOTH, expand=True)
            setattr(self, ("help_lb", "unit_lb", "join_lb")[col], lb)
        self.rowconfigure(0, weight=1)
        self.help_lb.bind("<<ListboxSelect>>", lambda e: self._grey())

        bar = ttk.Frame(self)
        bar.grid(row=1, column=0, columnspan=3, pady=4)
        ttk.Button(bar, text="Join",
                   command=self.cmd_join).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="Remove",
                   command=self.cmd_remove).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="OK",
                   command=self.cmd_ok).pack(side=tk.LEFT, padx=12)
        self._refresh()

    # ---- compatibility for the current mode ----
    def _can(self, helper_entry, target_entry):
        hud = helper_entry["unit"]
        tud = target_entry["unit"]
        if self.mode == "leader":
            return lc.native_can_attach(hud, tud, self.fmt)
        return lc.native_can_support(hud, tud, self.fmt)

    def _name(self, entry):
        return lc.entry_label(entry)

    def _refresh(self):
        self.help_lb.delete(0, tk.END)
        for e in self.helpers:
            self.help_lb.insert(tk.END, self._name(e))
        self.unit_lb.delete(0, tk.END)
        for e in self.targets:
            self.unit_lb.insert(tk.END, self._name(e))
        self.join_lb.delete(0, tk.END)
        for he, te in self.joined:
            self.join_lb.insert(tk.END,
                                f"{te['unit']['name']} + {he['unit']['name']}")
        self._grey()

    def _compat(self, helper_entry):
        return [self._can(helper_entry, t) for t in self.targets]

    def _grey(self):
        sel = self.help_lb.curselection()
        compat = (self._compat(self.helpers[sel[0]]) if sel
                  else [True] * len(self.targets))
        for i, ok in enumerate(compat):
            self.unit_lb.itemconfig(i, foreground="" if ok else _GREY)
        self._compat_now = compat

    def cmd_join(self):
        hs, us = self.help_lb.curselection(), self.unit_lb.curselection()
        if not hs or not us:
            messagebox.showinfo("Join", f"Select one {self.mode} and one "
                                "unit.", parent=self)
            return
        if not self._compat_now[us[0]]:
            messagebox.showinfo("Join", f"That unit is not compatible with "
                                f"the selected {self.mode}.", parent=self)
            return
        target = self.targets[us[0]]
        used = sum(1 for _h, t in self.joined if t is target)
        if used >= lc.free_slots(target, self.slot, self.fmt):
            messagebox.showinfo("Join", f"That unit has no free "
                                f"{self.mode} slot left.", parent=self)
            return
        self.joined.append((self.helpers.pop(hs[0]), target))
        # The target stays selectable while it has another free slot.
        if used + 1 >= lc.free_slots(target, self.slot, self.fmt):
            self.targets.pop(us[0])
        self._refresh()

    def cmd_remove(self):
        sel = self.join_lb.curselection()
        if not sel:
            return
        he, te = self.joined.pop(sel[0])
        self.helpers.append(he)
        if te not in self.targets:
            self.targets.append(te)
        self._refresh()

    def cmd_ok(self):
        # Join the helper's base unit into the target entry's slot; unpaired
        # helpers and targets pass through unchanged.
        # Group by target: one entry may have taken several helpers.
        merged, order = {}, []
        for he, te in self.joined:
            key = id(te)
            if key not in merged:
                merged[key] = te
                order.append(key)
            merged[key] = lc.set_helpers(
                merged[key], self.slot,
                lc.helpers(merged[key], self.slot) + [he["unit"]])
        joined_entries = [merged[k] for k in order]
        self.result = joined_entries + self.helpers + self.targets
        self.destroy()


class TwoArmyJoinDialog(tk.Toplevel):
    """Unified join dialog for the game assistant, covering BOTH armies at
    once. One row per army (attacker A, defender B); each row shows three
    source lists -- Leaders, Units, Supports -- plus a Joined list. Multi-
    select is allowed in the source lists. Buttons:
      * Join    : the selected leaders and/or supports (several at once)
                  onto the selected target - a Unit, a Support, or an
                  existing Joined entry that still has a free slot.
      * Unjoin  : split the selected joined entry back to its lists.
    A label under each row shows how many leader/support slots the
    selected target still has free.
    Joined units disappear from their source lists (game-assistant rule).
    self.result = (entriesA, entriesB) or None.
    """

    def __init__(self, parent, data_a, data_b, fmt):
        super().__init__(parent)
        self.title("Join leaders & supports")
        self.transient(parent)
        self.grab_set()
        self.fmt = fmt
        self.states = {"A": lc.ArmyJoinState(data_a, fmt),
                       "B": lc.ArmyJoinState(data_b, fmt)}
        self.lb = {}                        # (side, which) -> Listbox
        self.slot_lbl = {}                  # side -> free-slots Label
        self.result = None

        self.columnconfigure(0, weight=1)
        for r, side in enumerate(("A", "B")):
            lf = ttk.LabelFrame(
                self, text=f"Army {side} ({'attacker' if side=='A' else 'defender'})")
            lf.grid(row=r, column=0, sticky="nsew", padx=4, pady=4)
            self.rowconfigure(r, weight=1)
            for c, which in enumerate(("leaders", "others", "supports",
                                       "joined")):
                col = ttk.Frame(lf)
                col.grid(row=0, column=c, sticky="nsew", padx=3, pady=3)
                lf.columnconfigure(c, weight=1)
                lf.rowconfigure(0, weight=1)
                title = {"leaders": "Leaders", "others": "Units",
                         "supports": "Supports", "joined": "Joined"}[which]
                ttk.Label(col, text=title).pack(anchor=tk.W)
                lb_frame, lb = scrollable_listbox(
                    col, width=26, height=9,
                    selectmode=tk.EXTENDED, exportselection=False)
                lb_frame.pack(fill=tk.BOTH, expand=True)
                lb.bind("<<ListboxSelect>>",
                        lambda e, s=side, w=which: self._grey(s, w))
                if which == "joined":
                    lb.config(selectmode=tk.BROWSE)
                self.lb[(side, which)] = lb
            bar = ttk.Frame(lf)
            bar.grid(row=1, column=0, columnspan=4, pady=3)
            # Free slots of the selected target; blank while none is
            # selected (or several are).
            lbl = ttk.Label(bar, text="", foreground="#666666")
            self.slot_lbl[side] = lbl
            lbl.pack(side=tk.RIGHT, padx=8)
            ttk.Button(bar, text="Join",
                       command=lambda s=side: self._join(s)
                       ).pack(side=tk.LEFT, padx=3)
            ttk.Button(bar, text="Unjoin",
                       command=lambda s=side: self._unjoin(s)
                       ).pack(side=tk.LEFT, padx=3)

        ok = ttk.Frame(self)
        ok.grid(row=2, column=0, pady=6)
        # One reminder for all the source lists (they are all multi-select).
        multi_select_hint(ok).pack(side=tk.LEFT, padx=12)
        ttk.Button(ok, text="OK", command=self.cmd_ok).pack(side=tk.LEFT,
                                                            padx=12)
        ttk.Button(ok, text="Cancel",
                   command=self.destroy).pack(side=tk.LEFT, padx=4)
        self._refresh()

    def _refresh(self):
        for side in ("A", "B"):
            st = self.states[side]
            for which, pool in (("leaders", st.leaders),
                                ("others", st.others),
                                ("supports", st.supports)):
                lb = self.lb[(side, which)]
                lb.delete(0, tk.END)
                for u in pool:
                    lb.insert(tk.END, u["name"])
            lbj = self.lb[(side, "joined")]
            lbj.delete(0, tk.END)
            for e in st.joined:
                lbj.insert(tk.END, lc.entry_label(e))
            self._clear_grey(side)
            self._update_slots(side)

    def _sel_one(self, side, which):
        sel = self.lb[(side, which)].curselection()
        return sel[0] if len(sel) == 1 else None

    def _sel_many(self, side, which):
        """All selected indices of a source list (they are EXTENDED)."""
        return list(self.lb[(side, which)].curselection())

    def _target_entry(self, side):
        """The entry the Join button would fill: the selected Unit, the
        selected Support, or the selected Joined entry. None when the
        selection is not exactly one target."""
        st = self.states[side]
        ui, ji = self._sel_one(side, "others"), self._sel_one(side, "joined")
        si_ = self._sel_one(side, "supports")
        if ji is not None:
            return st.joined[ji], ("joined", ji)
        if ui is not None:
            return lc.make_entry(st.others[ui]), ("others", ui)
        if si_ is not None:
            return lc.make_entry(st.supports[si_]), ("supports", si_)
        return None, (None, None)

    def _update_slots(self, side):
        entry, _where = self._target_entry(side)
        if entry is None:
            self.slot_lbl[side].config(text="")
            return
        self.slot_lbl[side].config(
            text=f"Free slots - leaders: "
                 f"{lc.free_slots(entry, 'leader', self.fmt)}   "
                 f"supports: {lc.free_slots(entry, 'support', self.fmt)}")

    def _pool(self, side, which):
        st = self.states[side]
        return {"leaders": st.leaders, "others": st.others,
                "supports": st.supports}.get(which, [])

    def _clear_grey(self, side):
        for which in ("leaders", "others", "supports"):
            lb = self.lb[(side, which)]
            for i in range(lb.size()):
                lb.itemconfig(i, foreground="")

    def _set_grey(self, side, which, ok_flags):
        lb = self.lb[(side, which)]
        for i, ok in enumerate(ok_flags):
            lb.itemconfig(i, foreground="" if ok else _GREY)

    def _grey(self, side, source_which):
        """Grey out options incompatible with the current selection in
        'source_which'. A selected helper greys the targets it cannot take;
        a selected target greys the helpers that cannot take it. Clears when
        nothing (or a multi-selection) is active."""
        self._clear_grey(side)
        st = self.states[side]
        self._update_slots(side)
        i = self._sel_one(side, source_which)
        if i is None:
            return
        if source_which == "leaders":
            leader = st.leaders[i]
            # units and supports this leader cannot lead -> grey
            self._set_grey(side, "others",
                           [st.can_lead(leader, u) for u in st.others])
            self._set_grey(side, "supports",
                           [st.can_lead(leader, u) for u in st.supports])
        elif source_which == "supports" and source_which:
            support = st.supports[i]
            # a support can (a) support units/other-supports, and (b) itself
            # be led by a leader. Grey by its support compatibility as helper.
            self._set_grey(side, "others",
                           [st.can_support(support, u) for u in st.others])
            self._set_grey(side, "leaders",
                           [st.can_lead(ld, support) for ld in st.leaders])
        elif source_which == "others":
            target = st.others[i]
            self._set_grey(side, "leaders",
                           [st.can_lead(ld, target) for ld in st.leaders])
            self._set_grey(side, "supports",
                           [st.can_support(sp, target) for sp in st.supports])
        elif source_which == "joined":
            # An existing joined entry is a valid target while it has a
            # free slot for the helper.
            entry = st.joined[i]
            target = entry["unit"]
            free_l = lc.free_slots(entry, "leader", self.fmt)
            free_s = lc.free_slots(entry, "support", self.fmt)
            self._set_grey(side, "leaders",
                           [bool(free_l) and st.can_lead(ld, target)
                            for ld in st.leaders])
            self._set_grey(side, "supports",
                           [bool(free_s) and st.can_support(sp, target)
                            for sp in st.supports])

    def _join(self, side):
        """Single smart join. Uses whatever is selected: one target
        (a Unit, a Support, or an existing Joined entry) plus one or more
        leaders and/or supports. Every selected helper that fits a free,
        compatible slot is attached; the rest is reported."""
        st = self.states[side]
        entry, (where, wi) = self._target_entry(side)
        if entry is None:
            messagebox.showinfo("Join", "Select one unit (or one joined "
                                "entry) to join.", parent=self)
            return
        picks = ([("leader", st.leaders[i])
                  for i in self._sel_many(side, "leaders")]
                 + [("support", st.supports[i])
                    for i in self._sel_many(side, "supports")
                    if where != "supports" or i != wi])
        if not picks:
            messagebox.showinfo("Join", "Select a leader and/or a support "
                                "to join with the unit.", parent=self)
            return
        target = entry["unit"]
        taken, refused = {"leader": 0, "support": 0}, []
        chosen = {"leader": [], "support": []}
        for slot, helper in picks:
            can = (st.can_lead(helper, target) if slot == "leader"
                   else st.can_support(helper, target))
            room = lc.free_slots(entry, slot, self.fmt) - taken[slot]
            if not can:
                refused.append(f"{helper['name']}: cannot {slot} that unit")
            elif room <= 0:
                refused.append(f"{helper['name']}: no free {slot} slot")
            else:
                chosen[slot].append(helper)
                taken[slot] += 1
        if chosen["leader"] or chosen["support"]:
            if where == "joined":
                for slot in ("leader", "support"):
                    for helper in chosen[slot]:
                        st.add_to_joined(wi, helper, slot)
            else:
                st.join_combo(target, chosen["leader"], chosen["support"])
            self._refresh()
        if refused:
            messagebox.showinfo("Join", "Not joined:\n- "
                                + "\n- ".join(refused), parent=self)

    def _unjoin(self, side):
        i = self._sel_one(side, "joined")
        if i is None:
            return
        self.states[side].unjoin(i)
        self._refresh()

    def cmd_ok(self):
        self.result = (self.states["A"].entries(),
                       self.states["B"].entries())
        self.destroy()
