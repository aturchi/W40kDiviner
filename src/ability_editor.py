"""Unified ability editor.

One tab edits the "abilities" list of the attached node (unit, model or
weapon). An ability is one EFFECT plus the CONDITIONS under which it
applies, edited together:

  [abilities list]  |  description
  [Add] [Remove]    |  --- Effect: type combo + spec form
                    |  --- Conditions: list + type combo + Add/Remove
                    |      + spec form of the selected condition
                    |  [Apply changes]

"Apply changes" writes description, the effect form and the currently
shown condition form back into the data. Unknown effect/condition types
keep their data untouched (the JSON tab remains the catch-all).
"""

import tkinter as tk
from tkinter import ttk, messagebox
from ui_utils import scrollable_listbox

import condition_specs as cs
import effect_specs as es
import keywords_config
import node_templates as nt
from spec_forms import build_form, apply_form


class AbilityEditor(ttk.Frame):
    """Editor panel for a unit/model/weapon ability list: add/remove abilities, edit each ability's conditions and effect, and copy/paste abilities between nodes."""
    def __init__(self, master, on_change):
        super().__init__(master)
        self.on_change = on_change
        self.kwcfg = keywords_config.load()
        self.node = None             # dict owning the edited list
        self.list_key = "abilities"  # which list of the node is edited
        self._lists = ("abilities",)
        bar = ttk.Frame(self)
        bar.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(bar, text="List:").pack(side=tk.LEFT, padx=4)
        self.list_combo = ttk.Combobox(bar, state="readonly", width=16,
                                       values=["abilities"])
        self.list_combo.set("abilities")
        self.list_combo.pack(side=tk.LEFT)
        self.list_combo.bind("<<ComboboxSelected>>",
                             lambda e: self._on_list_change())
        self.eff_vars, self.cond_vars = [], []

        # Left column: abilities of the node
        left = ttk.Frame(self)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=4)
        ttk.Label(left, text="Abilities").pack(anchor=tk.W)
        ab_frame, self.ab_list = scrollable_listbox(
            left, width=34, exportselection=False)
        ab_frame.pack(fill=tk.BOTH, expand=True)
        self.ab_list.bind("<<ListboxSelect>>", lambda e: self.show_ability())
        row = ttk.Frame(left)
        row.pack(fill=tk.X, pady=3)
        ttk.Button(row, text="Add", command=self.cmd_add).pack(side=tk.LEFT)
        ttk.Button(row, text="Remove",
                   command=self.cmd_remove).pack(side=tk.LEFT, padx=4)
        ttk.Button(row, text="Copy",
                   command=self.cmd_copy).pack(side=tk.LEFT, padx=4)
        self.paste_btn = ttk.Button(row, text="Paste",
                                    command=self.cmd_paste)
        # packed only while the shared clipboard holds an ability
        self.clip_get = lambda: None     # injected by the host editor
        self.clip_set = lambda item: None

        # Right column: the selected ability
        right = ttk.Frame(self)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)
        nrow = ttk.Frame(right)
        nrow.pack(fill=tk.X)
        ttk.Label(nrow, text="Name:").pack(side=tk.LEFT)
        self.name_var = tk.StringVar()
        ttk.Entry(nrow, textvariable=self.name_var, width=60).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        drow = ttk.Frame(right)
        drow.pack(fill=tk.X)
        ttk.Label(drow, text="Description:").pack(side=tk.LEFT)
        self.desc_var = tk.StringVar()
        ttk.Entry(drow, textvariable=self.desc_var, width=60).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        # enabled: persistent per-profile toggle; a disabled ability is
        # skipped by the engine but kept in the file.
        self.enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(right, text="Enabled (uncheck to disable this "
                        "ability without deleting it)",
                        variable=self.enabled_var).pack(anchor=tk.W)
        # share_with_unit: when this ability's owner is attached to /
        # leads another unit, also apply the ability to all its models
        self.share_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(right, text="Share with associated unit "
                        "(apply to all models of the unit this element "
                        "joins or leads)",
                        variable=self.share_var).pack(anchor=tk.W)

        # exclusive_group: abilities of the same unit sharing this label
        # are mutually exclusive choices ("select one of the following",
        # "select one weapon"). The engine does not enforce it - it
        # cannot know which one you meant - but the analysis warns when
        # more than one of the group is switched on.
        grp = ttk.Frame(right)
        grp.pack(fill=tk.X)
        ttk.Label(grp, text="Exclusive group (optional): only one "
                            "ability with this label should be on").pack(
            side=tk.LEFT)
        self.group_var = tk.StringVar(value="")
        ttk.Entry(grp, textvariable=self.group_var, width=22).pack(
            side=tk.LEFT, padx=4)

        self.eff_frame = ttk.LabelFrame(right, text="Effect")
        self.eff_frame.pack(fill=tk.X, pady=4)

        cond_outer = ttk.LabelFrame(right, text="Activation conditions")
        cond_outer.pack(fill=tk.BOTH, expand=True, pady=4)
        cleft = ttk.Frame(cond_outer)
        cleft.pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=4)
        cond_frame, self.cond_list = scrollable_listbox(
            cleft, width=30, exportselection=False)
        cond_frame.pack(fill=tk.BOTH, expand=True)
        self.cond_list.bind("<<ListboxSelect>>",
                            lambda e: self.show_condition())
        crow = ttk.Frame(cleft)
        crow.pack(fill=tk.X, pady=3)
        self.cond_type = ttk.Combobox(crow, values=cs.list_types(),
                                      state="readonly", width=18)
        self.cond_type.set(cs.list_types()[0])
        self.cond_type.pack(side=tk.LEFT)
        ttk.Button(crow, text="Add", width=4,
                   command=self.cmd_add_cond).pack(side=tk.LEFT, padx=2)
        ttk.Button(crow, text="Del", width=4,
                   command=self.cmd_del_cond).pack(side=tk.LEFT)
        self.cond_form = ttk.Frame(cond_outer)
        self.cond_form.pack(side=tk.LEFT, fill=tk.BOTH, expand=True,
                            padx=4, pady=4)

        ttk.Button(right, text="Apply changes",
                   command=self.cmd_apply).pack(anchor=tk.W, pady=4)

    # ---------- public API ----------

    def load_node(self, node, select=None, lists=("abilities",)):
        """Attach a unit/model/weapon dict (or None); optionally select
        the ability at the given index. 'lists' names the node's
        ability-like lists this tab can edit (units also expose
        leader_effects); the selector is shown when there is a choice."""
        if hasattr(self, "paste_btn"):
            self._refresh_paste_btn()
        if select is None and node is not None and node is self.node:
            # reloading the same node (tree refresh after an edit):
            # keep the current ability selection
            cur = self.ab_list.curselection()
            select = cur[0] if cur else None
        self.node = node
        self._lists = tuple(lists)
        if self.list_key not in self._lists:
            self.list_key = self._lists[0]
        self.list_combo.configure(values=list(self._lists))
        self.list_combo.set(self.list_key)
        self.ab_list.delete(0, tk.END)
        if node is not None:
            for ab in node.get(self.list_key, []):
                label = (ab.get("name") or ab.get("description")
                         or "<no name>")[:50]
                if not ab.get("enabled", True):
                    label = "[OFF] " + label
                self.ab_list.insert(tk.END, label)
            if select is not None and self.ab_list.size() > select:
                self.ab_list.selection_set(select)
        self.show_ability()
        if hasattr(self, "paste_btn"):
            self._refresh_paste_btn()

    def _on_list_change(self):
        self.list_key = self.list_combo.get()
        self.load_node(self.node, lists=self._lists)

    # ---------- ability list ----------

    def _ability(self):
        if self.node is None or not self.ab_list.curselection():
            return None
        return self.node[self.list_key][self.ab_list.curselection()[0]]

    def _refresh_paste_btn(self):
        clip = self.clip_get()
        if clip is not None and clip[0] == "ability" \
                and self.node is not None:
            self.paste_btn.pack(side=tk.LEFT, padx=4)
        else:
            self.paste_btn.pack_forget()

    def cmd_copy(self):
        """Copy the selected ability to an internal clipboard for pasting onto another node."""
        ab = self._ability()
        if ab is not None:
            self.clip_set(("ability", ab))
            self._refresh_paste_btn()

    def cmd_paste(self):
        """Paste the copied ability onto the current node."""
        import copy
        clip = self.clip_get()
        if clip is None or clip[0] != "ability" or self.node is None:
            return
        self.node.setdefault(self.list_key, []).append(
            copy.deepcopy(clip[1]))
        self.load_node(self.node,
                       select=len(self.node[self.list_key]) - 1,
                       lists=self._lists)
        self.on_change()

    def cmd_add(self):
        if self.node is None:
            return
        self.node.setdefault(self.list_key, []).append(nt.new_ability())
        self.load_node(self.node, select=self.ab_list.size(),
                       lists=self._lists)
        self.on_change()

    def cmd_remove(self):
        if self._ability() is None:
            return
        del self.node[self.list_key][self.ab_list.curselection()[0]]
        self.load_node(self.node, lists=self._lists)
        self.on_change()

    # ---------- ability display ----------

    def show_ability(self):
        """Load the selected ability into the detail pane for editing."""
        ab = self._ability()
        self.name_var.set((ab or {}).get("name") or "")
        self.desc_var.set((ab or {}).get("description") or "")
        self.enabled_var.set(bool((ab or {}).get("enabled", True)))
        self.share_var.set(bool((ab or {}).get("share_with_unit", False)))
        self.group_var.set((ab or {}).get("exclusive_group") or "")
        # Effect section
        for w in self.eff_frame.winfo_children():
            w.destroy()
        self.eff_vars = []
        if ab is not None:
            eff = ab.setdefault("effect", es.new_effect("modifyRelative"))
            self.eff_type = ttk.Combobox(self.eff_frame,
                                         values=es.list_types(),
                                         state="readonly", width=26)
            self.eff_type.grid(row=0, column=0, columnspan=2, sticky=tk.W,
                               padx=4, pady=2)
            self.eff_type.set(eff.get("type", ""))
            self.eff_type.bind("<<ComboboxSelected>>", self.on_eff_type)
            spec = es.EFFECT_SPECS.get(eff.get("type"))
            if spec is not None:
                self.eff_vars = build_form(self.eff_frame, spec["fields"],
                                           eff.setdefault("data", {}),
                                           start_row=1)
                if eff.get("type") == "setKeyword":
                    self._wire_setkeyword_filter(spec)
            else:
                ttk.Label(self.eff_frame,
                          text="Unregistered effect type: use the JSON tab."
                          ).grid(row=1, column=0, padx=4, pady=2)
        # Conditions section
        self.cond_list.delete(0, tk.END)
        if ab is not None:
            for c in ab.get("conditions", []):
                self.cond_list.insert(tk.END, c.get("type", "?"))
        self.show_condition()

    def _wire_setkeyword_filter(self, spec):
        """Restrict the keyword suggestions to the vocabulary matching the
        selected target (weapon / model / unit), live on target change."""
        fields = {k: (var, w) for k, _kd, var, w in self.eff_vars}
        if "target" not in fields or "keyword" not in fields:
            return
        tvar, _ = fields["target"]
        _, kwidget = fields["keyword"]
        target_opts = dict(next(opts for k, _kd, _l, opts in spec["fields"]
                                if k == "target"))   # title -> key
        vocab = {"weapon": "weapon_keywords", "allWeapons": "weapon_keywords",
                 "model": "model_keywords", "allModels": "model_keywords",
                 "unit": "unit_keywords"}

        def sync(*_args):
            key = target_opts.get(tvar.get(), "unit")
            kwidget.configure(
                values=self.kwcfg.get(vocab.get(key, "unit_keywords"), []))

        tvar.trace_add("write", sync)
        sync()

    def on_eff_type(self, _event=None):
        """Switching effect type replaces the effect with fresh defaults."""
        ab = self._ability()
        if ab is None:
            return
        ab["effect"] = es.new_effect(self.eff_type.get())
        self.show_ability()
        self.on_change()

    # ---------- conditions ----------

    def _condition(self):
        ab = self._ability()
        if ab is None or not self.cond_list.curselection():
            return None
        return ab["conditions"][self.cond_list.curselection()[0]]

    def cmd_add_cond(self):
        ab = self._ability()
        if ab is None:
            return
        ab.setdefault("conditions", []).append(
            cs.new_condition(self.cond_type.get()))
        idx = len(ab["conditions"]) - 1
        self.show_ability()
        self.cond_list.selection_set(idx)
        self.show_condition()
        self.on_change()

    def cmd_del_cond(self):
        ab = self._ability()
        if self._condition() is None:
            return
        del ab["conditions"][self.cond_list.curselection()[0]]
        self.show_ability()
        self.on_change()

    def show_condition(self):
        """Load the selected condition of the current ability into its editor."""
        for w in self.cond_form.winfo_children():
            w.destroy()
        self.cond_vars = []
        cond = self._condition()
        if cond is None:
            ttk.Label(self.cond_form,
                      text="Select or add a condition.").pack(padx=6, pady=6)
            return
        spec = cs.CONDITION_SPECS.get(cond.get("type"))
        if spec is None:
            ttk.Label(self.cond_form,
                      text=f"Unregistered condition type "
                           f"'{cond.get('type')}': use the JSON tab."
                      ).pack(padx=6, pady=6)
            return
        ttk.Label(self.cond_form, text=spec["description"],
                  wraplength=320).grid(row=0, column=0, columnspan=2,
                                       sticky=tk.W, padx=4, pady=2)
        self.cond_vars = build_form(self.cond_form, spec["fields"],
                                    cond.setdefault("data", {}), start_row=1)

    # ---------- apply ----------

    def cmd_apply(self):
        """Write description + effect form + shown condition form back."""
        ab = self._ability()
        if ab is None:
            return
        ab["name"] = self.name_var.get()
        ab["description"] = self.desc_var.get()
        ab["enabled"] = bool(self.enabled_var.get())
        ab["share_with_unit"] = bool(self.share_var.get())
        group = self.group_var.get().strip()
        if group:
            ab["exclusive_group"] = group
        else:
            ab.pop("exclusive_group", None)
        try:
            eff = ab.get("effect") or {}
            spec = es.EFFECT_SPECS.get(eff.get("type"))
            if spec is not None and self.eff_vars:
                apply_form(self.eff_vars, spec["fields"], eff["data"])
            cond = self._condition()
            if cond is not None and self.cond_vars:
                cspec = cs.CONDITION_SPECS.get(cond.get("type"))
                if cspec is not None:
                    apply_form(self.cond_vars, cspec["fields"], cond["data"])
        except KeyError as exc:
            messagebox.showerror("Invalid value", str(exc))
            return
        sel = (self.ab_list.curselection() or [None])[0]
        self.load_node(self.node, select=sel)
        self.on_change()
