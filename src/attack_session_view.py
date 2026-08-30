"""The attack window of the game assistant: weapons left, target right.

One unit's attacks, resolved a weapon profile at a time. The left panel
is the firing queue, the right one is the defending unit grouped the way
the Save Rolls step groups it, and between the two the player does the
three things the program must not decide for them: the order the weapons
fire in, the order the allocation groups take attacks in, and where a
PRECISION weapon is pointed.

It replaced the results report and the allocation dialog together, both
since deleted. Those two showed a heap of damage after the fact and
asked where to put it; this one runs the sequence the rules describe, in
which a weapon fires into the unit the previous ones left behind and the
saves are rolled against the model each attack is allocated to.

THIS FILE ONLY DRAWS. What to show is decided in session_rows, what
happens is decided in attack_session, and both are pure. That is not
tidiness for its own sake: a window cannot be tested on a machine with
no display, so anything that can be decided outside one is.

WHEN THE TABLE IS WRITTEN. Not after every weapon: once, when the player
presses End sequence, as a single undo step - the same contract the
allocation dialog had before it. The window's own Undo is internal
and takes back a whole activation, dice included, so that undoing is
not a way to roll until the dice fall better.
"""

import tkinter as tk
from tkinter import ttk

import session_rows as sr
import ui_utils as ui

# Left panel.
W_COLUMNS = (("attacks", "Attacks", 62, tk.E),
             ("note", "Result", 220, tk.W))
# Right panel.
T_COLUMNS = (("wounds", "Wounds", 70, tk.E),
             ("damage", "Damage", 62, tk.E))

DONE_TAG = "done"
SKIP_TAG = "skipped"
NEXT_TAG = "next"
ARMED_TAG = "armed"
CURRENT_TAG = "current"
CHAR_TAG = "character"
AIM_TAG = "aimed"
HURT_TAG = "hurt"
DEAD_TAG = "dead"

DIM = "#8a8a8a"
ALERT = "#a00000"
WARN = "#7a4a00"
GOOD = "#005f2f"


class AttackSessionWindow(tk.Toplevel):
    """session: attack_session.AttackSession; on_apply(rows) is called
    once with [{'key', 'label', 'before', 'wounds', 'dead'}] for every
    model whose wounds changed, plus the hazardous total owed by the
    attacking unit."""

    def __init__(self, parent, session, defender_name, on_apply,
                 skipped=(), attacker_name=""):
        super().__init__(parent)
        self.title(f"Attack - {attacker_name or 'unit'} into "
                   f"{defender_name}")
        self.geometry("980x600")
        self.transient(parent)
        self.session = session
        self.defender_name = defender_name
        self.on_apply = on_apply
        self.skipped = list(skipped)
        self.buttons = {}
        self.tips = {}                # mover key -> (label, its caption)
        self._armed = None            # what arm() reported, for the head
        self._last = None             # the activation just applied
        self._w_iid = {}              # tree iid -> weapon index
        self._t_iid = {}              # tree iid -> target row

        self._build_head()
        self._build_panels()
        self._build_bar()
        self.refresh()

    # ---------- construction ----------

    def _build_head(self):
        self.head_lbl = ttk.Label(self, font=ui.bold_font())
        self.head_lbl.pack(anchor=tk.W, padx=8, pady=(8, 0))
        self.hint_lbl = ttk.Label(self, foreground=WARN, wraplength=940,
                                  justify=tk.LEFT)
        self.hint_lbl.pack(anchor=tk.W, padx=8, pady=(2, 4))

    def _build_panels(self):
        panes = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True, padx=8)

        left = ttk.Frame(panes)
        self.weapons = self._tree(left, "Weapon (fires top down)",
                                  W_COLUMNS)
        self._mover(left, self._move_weapon, "Move the weapon in the "
                    "queue")
        panes.add(left, weight=1)

        right = ttk.Frame(panes)
        self.targets = self._tree(right, "Group / model (damage lands "
                                  "top down)", T_COLUMNS)
        bar = self._mover(right, self._move_target, "Move the group, or "
                          "the model inside its group")
        self.buttons["precision"] = ttk.Button(
            bar, text="Aim at character", command=self._toggle_precision)
        ui.tip(self.buttons["precision"],
               "PRECISION: send this weapon's wounds at the attached "
               "character instead of the bodyguard")
        self.buttons["precision"].pack(side=tk.LEFT, padx=(8, 0))
        panes.add(right, weight=1)

        for tree in (self.weapons, self.targets):
            tree.tag_configure(DONE_TAG, foreground=DIM)
            tree.tag_configure(SKIP_TAG, foreground=DIM)
            tree.tag_configure(DEAD_TAG, foreground=DIM)
            tree.tag_configure(HURT_TAG, foreground=WARN)
            tree.tag_configure(ALERT, foreground=ALERT)
            tree.tag_configure(ARMED_TAG, font=ui.bold_font(),
                               foreground=ALERT)
            tree.tag_configure(NEXT_TAG, font=ui.bold_font())
            tree.tag_configure(CURRENT_TAG, font=ui.bold_font())
            tree.tag_configure(AIM_TAG, foreground=ALERT)
            tree.tag_configure(CHAR_TAG, foreground=GOOD)

    def _tree(self, parent, heading, columns):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.BOTH, expand=True)
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns],
                            show="tree headings", selectmode="browse")
        tree.heading("#0", text=heading)
        tree.column("#0", width=240, stretch=True)
        for key, head, width, anchor in columns:
            tree.heading(key, text=head)
            tree.column(key, width=width, anchor=anchor, stretch=False)
        tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        return tree

    def _mover(self, parent, command, tip):
        bar = ttk.Frame(parent)
        bar.pack(fill=tk.X, pady=(4, 0))
        up = ttk.Button(bar, text="Move up", command=lambda: command(-1))
        ui.tip(up, tip)
        up.pack(side=tk.LEFT)
        down = ttk.Button(bar, text="Move down",
                          command=lambda: command(1))
        ui.tip(down, tip)
        down.pack(side=tk.LEFT, padx=3)
        key = "move_weapon" if command == self._move_weapon else "move"
        # The caption is kept, not thrown away: a greyed-out pair of
        # buttons with a caption describing what they would do reads as
        # a fault. refresh() replaces it with the reason instead.
        caption = ttk.Label(bar, foreground=ui.HINT_COLOR, text=tip)
        caption.pack(side=tk.LEFT, padx=6)
        self.tips[key] = (caption, tip)
        self.buttons[key + "_up"] = up
        self.buttons[key + "_down"] = down
        return bar

    def _build_bar(self):
        # ALERT, not WARN: the line only ever appears when the attacking
        # unit owes mortal wounds to itself, which is a thing that has
        # happened rather than something to bear in mind.
        self.foot_lbl = ttk.Label(self, foreground=ALERT, wraplength=940,
                                  justify=tk.LEFT)
        self.foot_lbl.pack(side=tk.BOTTOM, anchor=tk.W, padx=8,
                           pady=(0, 6))
        bar = ttk.Frame(self)
        bar.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=6)
        for key, text, command, help_text in (
                ("fire", "Fire", self._fire,
                 "Roll hits and wounds for the current weapon"),
                ("apply", "Roll saves", self._roll_saves,
                 "Roll the defender's saves for the wounds just scored "
                 "and work out the damage"),
                ("discard", "Re-roll", self._discard,
                 "Throw away this weapon's rolls and fire it again"),
                ("fire_all", "Fire all", self._fire_all,
                 "Resolve every remaining weapon in one go, in the order "
                 "shown on the left"),
                ("undo", "Undo weapon", self._undo,
                 "Take back the last weapon resolved, damage included")):
            btn = ttk.Button(bar, text=text, command=command)
            ui.tip(btn, help_text)
            btn.pack(side=tk.LEFT, padx=(0, 3))
            self.buttons[key] = btn
        self.buttons["cancel"] = ttk.Button(bar, text="Cancel",
                                            command=self.destroy)
        self.buttons["cancel"].pack(side=tk.RIGHT)
        self.buttons["write"] = ttk.Button(bar, text="End sequence",
                                           command=self._write)
        ui.tip(self.buttons["write"],
               "Close the attack and write its result onto the roster and "
               "into the attack log")
        self.buttons["write"].pack(side=tk.RIGHT, padx=3)

    # ---------- drawing ----------

    def refresh(self):
        """Rebuild both panels and the buttons from the session. Called
        after every action: the panels are never patched in place, so a
        row can never be left describing a state that has moved on."""
        self._fill_weapons()
        self._fill_targets()
        self.head_lbl.configure(text=sr.headline(self.session,
                                                 self._armed))
        self.hint_lbl.configure(text=sr.hint(self.session)
                                if self._armed is None else "")
        self.foot_lbl.configure(text=sr.closing_note(self.session))
        state = sr.buttons(self.session)
        for key in ("fire", "fire_all", "apply", "discard", "undo",
                    "precision"):
            self._enable(key, state[key])
        self._enable("move_weapon_up", state["move_weapon"])
        self._enable("move_weapon_down", state["move_weapon"])
        target_move = state["move_group"] or state["move_model"]
        self._enable("move_up", target_move)
        self._enable("move_down", target_move)
        self._say("move_weapon", state["move_weapon"],
                  "The dice are already rolled for this weapon."
                  if self._armed is not None else
                  "Nothing left to reorder.")
        self._say("move", target_move,
                  "Nothing of the unit is left to put in order.")

    def _say(self, key, on, reason):
        """Caption of a mover bar: what the buttons do when they are
        live, why they are not when they are off. A greyed-out pair of
        buttons under a caption describing the move they refuse to make
        reads as a fault, and the first run on a real display was
        reported as one."""
        entry = self.tips.get(key)
        if entry is not None:
            label, tip = entry
            label.configure(text=tip if on else reason)

    def _enable(self, key, on):
        btn = self.buttons.get(key)
        if btn is not None:
            btn.configure(state=tk.NORMAL if on else tk.DISABLED)

    def _fill_weapons(self):
        self.weapons.delete(*self.weapons.get_children())
        self._w_iid = {}
        for n, row in enumerate(sr.weapon_rows(self.session,
                                               self.skipped)):
            tags = []
            label = row["label"]
            if row["state"] == sr.DONE:
                tags.append(DONE_TAG)
            elif row["state"] == sr.SKIPPED:
                tags.append(SKIP_TAG)
            elif row["state"] == sr.ARMED:
                tags.append(ARMED_TAG)
                label += "   <- rolled, waiting for the saves"
            elif row["state"] == sr.NEXT:
                # The head of the queue looked exactly like the rest of
                # it: same font, no marker, nothing selected. The target
                # panel already marks its current group this way, so the
                # two panels now read the same.
                tags.append(NEXT_TAG)
                label += "   <- fires next"
            iid = self.weapons.insert(
                "", tk.END, iid="w%d" % n, text=label,
                values=("" if row["attacks"] is None else row["attacks"],
                        row["note"]), tags=tuple(tags))
            if row["selectable"]:
                self._w_iid[iid] = row

    def _fill_targets(self):
        self.targets.delete(*self.targets.get_children())
        self._t_iid = {}
        parents = {}
        for n, row in enumerate(sr.target_rows(self.session,
                                               self._last)):
            iid = "t%d" % n
            if row["kind"] == "group":
                tags = []
                if row["current"]:
                    tags.append(CURRENT_TAG)
                if row["character"]:
                    tags.append(CHAR_TAG)
                if row["precision"]:
                    tags.append(AIM_TAG)
                if row.get("casualties"):
                    tags.append(DEAD_TAG)
                label = row["label"]
                if row["current"]:
                    label += "   <- next attack"
                if row["precision"]:
                    label += "   <- PRECISION"
                self.targets.insert("", tk.END, iid=iid, text=label,
                                    open=True, tags=tuple(tags),
                                    values=("", ""))
                parents[row["group"]] = iid
            else:
                tags = []
                if row["state"] == sr.DEAD:
                    tags.append(DEAD_TAG)
                elif row["state"] == sr.HURT:
                    tags.append(HURT_TAG)
                self.targets.insert(
                    parents.get(row["group"], ""), tk.END, iid=iid,
                    text=row["label"], tags=tuple(tags),
                    values=("%d/%d" % (row["wounds"], row["max"]),
                            row["damage"] or ""))
            self._t_iid[iid] = row

    # ---------- actions ----------

    def _selected(self, tree, table):
        sel = tree.selection()
        return table.get(sel[0]) if sel else None

    def _move_weapon(self, delta):
        row = self._selected(self.weapons, self._w_iid)
        if row is None or row["position"] is None:
            return
        if self.session.move(row["position"], delta):
            self.refresh()
            self._reselect(self.weapons, "w%d" % (row["position"] + delta))

    def _move_target(self, delta):
        # Through the SESSION, not the Allocation: an Allocation lasts
        # one activation and the declaration has to last the sequence.
        # This is also what lets the panel be reordered before anything
        # is armed, when there is no Allocation to reorder at all.
        row = self._selected(self.targets, self._t_iid)
        if row is None or not row["movable"]:
            return
        if row["kind"] == "group":
            moved = self.session.reorder("group", row["position"], delta)
        else:
            moved = self.session.reorder("member", row["slot"], delta,
                                         group=row["group"])
        if moved:
            self.refresh()

    def _reselect(self, tree, iid):
        if tree.exists(iid):
            tree.selection_set(iid)

    def _toggle_precision(self):
        alloc = self.session.alloc
        if alloc is None:
            return
        row = self._selected(self.targets, self._t_iid)
        group = row["group"] if row else None
        if group is None or not alloc.groups[group]["character"]:
            group = (alloc.character_groups() or [None])[0]
        if group is None:
            return
        alloc.set_precision(None if alloc.precision == group else group)
        self.refresh()

    def _fire(self):
        self._last = None
        self._armed = self.session.arm()
        self.refresh()

    def _discard(self):
        self.session.discard()
        self._armed = None
        self.refresh()

    def _roll_saves(self):
        self._last = self.session.apply()
        self._armed = None
        self.refresh()

    def _fire_all(self):
        done = self.session.fire_all()
        self._last = done[-1] if done else None
        self._armed = None
        self.refresh()

    def _undo(self):
        self.session.undo()
        self._armed = self._last = None
        self.refresh()

    def _write(self):
        """Hand the caller every model whose wounds changed, once.

        The row carries WHAT CHANGED, not only the new value: the label
        and the wounds the model started the sequence with are what the
        attack log records, and a log that read '? : 0 -> 0' two turns
        later would tell the player nothing. They are both known here -
        the label comes with the model record, 'before' is the first
        activation's snapshot - so neither is looked up again downstream.
        """
        records = self.session.records()
        if not records:
            self.destroy()
            return
        start = records[0]["wounds_before"]
        rows = []
        for model, before in zip(self.session.models, start):
            after = int(model.get("wounds") or 0)
            if after != before:
                rows.append({"key": model.get("key"),
                             "label": model.get("label", "?"),
                             "before": before, "wounds": after,
                             "dead": after <= 0 and before > 0})
        self.on_apply(rows, self.session.self_damage())
        self.destroy()
