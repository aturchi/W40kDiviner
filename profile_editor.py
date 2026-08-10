#!/usr/bin/env python3
"""Profile editor (v2, native format).

Minimal clean base, to be extended step by step:
- Import / save native JSON profile files (see src/native_format.py)
- Unit tree: units -> models -> weapons -> abilities
- Quick edit tab (scalar fields) and JSON tab (full node)

Run:  python3 profile_editor.py
"""

import json
import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "src"))

import native_format
import ability_ids
from search_widget import attach_search
from list_dialog import StringListDialog, vocabulary_for         # noqa: E402
import node_templates as nt  # noqa: E402
import validation            # noqa: E402
from editor_widgets import PickerDialog  # noqa: E402
from ability_editor import AbilityEditor  # noqa: E402
from setup_panel import show_font_dialog  # noqa: E402
from merge_dialog import MergeDialog  # noqa: E402

SCALARS = (str, int, float, bool, type(None))

# Quick-form fields whose value is free-form long text: shown as a
# multi-line tk.Text (newline-preserving) rather than a single-line
# ttk.Entry. Always plain strings, so edited as raw text (not JSON-encoded
# like the other scalar fields).
MULTILINE_FIELDS = ("unit_composition", "wargear_options", "notes")
_MULTILINE_HEIGHT = 5           # rendered height (text lines) of each box


def get_node(root, path):
    """Resolve a path (tuple of dict keys / list indices) from root."""
    node = root
    for key in path:
        node = node[key]
    return node


def set_node(root, path, value):
    """Replace the node at path with value."""
    parent = get_node(root, path[:-1])
    parent[path[-1]] = value


class EditorApp(tk.Tk):
    """Profile editor window: load a native army file, edit units/models/
    weapons and their abilities in a tree, and save back to native JSON."""
    def __init__(self):
        super().__init__()
        self.title("W40k Profile Editor")
        self.geometry("1150x700")
        self.data = None             # native-format dict (v2, armies)
        self.army_idx = None         # index of the displayed army
        self.current_path = None     # last imported/saved file (for revert)
        self.paths = {}              # tree item id -> path tuple
        self.form_vars = []          # (key, StringVar) of the quick form
        self.form_texts = []         # (key, tk.Text) for multi-line fields
        self.clip = None             # ('model'|'weapon'|'ability', deepcopy)
        self._sel_path = None
        self._build_widgets()

    # ---------- UI construction ----------

    def _build_widgets(self):
        bar = ttk.Frame(self)
        bar.pack(side=tk.TOP, fill=tk.X)
        self.buttons = {}
        for text, cmd in [("Import JSON", self.cmd_import),
                          ("Save JSON", self.cmd_save),
                          ("Select army", self.cmd_select_army),
                          ("Add unit", self.cmd_add_unit),
                          ("Add model", self.cmd_add_model),
                          ("Add weapon", self.cmd_add_weapon),
                          ("Duplicate", self.cmd_duplicate),
                          ("Remove", self.cmd_remove),
                          ("Apply form", self.cmd_apply_form),
                          ("Apply JSON", self.cmd_apply_json),
                          ("Revert changes", self.cmd_revert)]:
            btn = ttk.Button(bar, text=text, command=cmd)
            btn.pack(side=tk.LEFT, padx=3, pady=3)
            self.buttons[text] = btn
        self._update_buttons(None)
        # Merge JSON: disabled until a file is loaded (enabled in
        # _update_status once self.data exists); not part of the
        # selection-managed button set above.
        self._merge_btn = ttk.Button(bar, text="Merge JSON",
                                     command=self.cmd_merge_json,
                                     state=tk.DISABLED)
        self._merge_btn.pack(side=tk.LEFT, padx=3, pady=3)
        # Accessibility: always-enabled font-size control (not part of the
        # selection-managed button set above).
        ttk.Button(bar, text="Font size",
                   command=lambda: show_font_dialog(self)).pack(
            side=tk.LEFT, padx=3, pady=3)
        self.status = ttk.Label(bar, text="No file loaded")
        self.status.pack(side=tk.LEFT, padx=10)

        main = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True)

        # Left: unit tree
        left = ttk.Frame(main)
        self.tree = ttk.Treeview(left, show="tree")
        ysb = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ysb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        attach_search(self, lambda: [self.tree])
        main.add(left, weight=1)

        # Right: notebook (Quick edit / JSON); more tabs in later steps
        self.nb = ttk.Notebook(main)
        self.form_frame = ttk.Frame(self.nb)
        self.nb.add(self.form_frame, text="Quick edit")
        self.ability_editor = AbilityEditor(self.nb,
                                            on_change=self.on_ability_change)
        self.ability_editor.clip_get = lambda: self.clip
        self.ability_editor.clip_set = self._clip_set
        self.nb.add(self.ability_editor, text="Abilities")
        json_frame = ttk.Frame(self.nb)
        self.json_text = tk.Text(json_frame, wrap=tk.NONE, undo=True)
        jsb = ttk.Scrollbar(json_frame, orient=tk.VERTICAL,
                            command=self.json_text.yview)
        self.json_text.configure(yscrollcommand=jsb.set)
        self.json_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        jsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.nb.add(json_frame, text="JSON")
        main.add(self.nb, weight=2)

    # ---------- tree population ----------

    def _army(self):
        """The currently displayed army dict (or None)."""
        if self.data is None or self.army_idx is None:
            return None
        return self.data["armies"][self.army_idx]

    def _army_path(self):
        return ("armies", self.army_idx)

    def rebuild_tree(self):
        """Rebuild the units/models/weapons tree view from the loaded army data."""
        self.tree.delete(*self.tree.get_children())
        self.paths.clear()
        army = self._army()
        if army is None:
            return
        # Display-only ascending alphabetical order: paths keep the
        # original indices, so the JSON on disk is not reordered.
        units = army["units"]
        order = sorted(range(len(units)),
                       key=lambda i: (units[i].get("name") or "").lower())
        for i in order:
            unit = units[i]
            upath = self._army_path() + ("units", i)
            uid = self._add(upath, "",
                            f"{unit.get('name', i)} "
                            f"[{unit.get('points', 0)} pts]")
            for k, ab in enumerate(unit.get("abilities", [])):
                self._add(upath + ("abilities", k), uid,
                          f"[ability] {(ab.get('name') or ab.get('description') or '')[:60]}")
            for j, model in enumerate(unit.get("models", [])):
                mpath = upath + ("models", j)
                mid = self._add(mpath, uid,
                                f"[model x{model.get('model_count', 1)}] "
                                f"{model.get('name', j)}")
                for k, ab in enumerate(model.get("abilities", [])):
                    self._add(mpath + ("abilities", k), mid,
                              f"[ability] {(ab.get('name') or ab.get('description') or '')[:60]}")
                for k, w in enumerate(model.get("weapons", [])):
                    wpath = mpath + ("weapons", k)
                    wid = self._add(wpath, mid,
                                    f"[{w.get('type', '?').lower()}] "
                                    f"{w.get('name', k)}")
                    for n, ab in enumerate(w.get("abilities", [])):
                        self._add(wpath + ("abilities", n), wid,
                                  f"[ability] "
                                  f"{(ab.get('name') or ab.get('description') or '')[:60]}")

    def _add(self, path, parent, label):
        iid = self.tree.insert(parent, tk.END, text=label)
        self.paths[iid] = path
        return iid

    # ---------- selection ----------

    def _update_buttons(self, path):
        """'Add model' appears only when a unit is selected; 'Add weapon'
        only when a model is selected. Re-packed before the Duplicate
        button so their position in the toolbar stays stable."""
        kind = path[-2] if path and len(path) >= 2 else None
        anchor = self.buttons["Duplicate"]
        for label, wanted in [("Add model", kind == "units"),
                              ("Add weapon", kind == "models")]:
            btn = self.buttons[label]
            if wanted and not btn.winfo_ismapped():
                btn.pack(side=tk.LEFT, padx=3, pady=3, before=anchor)
            elif not wanted and btn.winfo_ismapped():
                btn.pack_forget()

    def _ensure_schema_keys(self, node, node_kind):
        """Add any template key absent from this node (keeping its
        existing values), so the quick form can edit every schema
        field even on imported data that omitted some. Weapon skill
        keys (BS/WS) follow the weapon type and are not cross-added."""
        if node_kind == "units":
            template = nt.new_unit()
        elif node_kind == "models":
            template = nt.new_model()
        else:
            template = nt.new_weapon(node.get("type", "Ranged"))
            skip = "WS" if node.get("type") == "Ranged" else "BS"
            template.pop(skip, None)
        for key, default in template.items():
            if key not in node:
                node[key] = (list(default) if isinstance(default, list)
                             else default)

    def on_select(self, _event=None):
        node = self._selected_node()
        if node is None:
            return
        self._update_buttons(self._sel_path)
        # Quick form: one entry per scalar field, values JSON-encoded so
        # types (int / str / bool / null) survive the round trip
        for w in self.form_frame.winfo_children():
            w.destroy()
        self.form_vars = []
        self.form_texts = []
        if isinstance(node, dict):
            row = 0
            node_kind = next((p for p in reversed(self._sel_path)
                              if p in ("units", "models", "weapons",
                                       "abilities")),
                             "units")
            # Backfill any schema key missing from an imported node, so
            # every editable field (e.g. leadership) shows even when the
            # source omitted it. Defaults are taken from the templates.
            # Abilities have their own minimal schema - never inject the
            # unit template into them (that produced spurious name /
            # profile_name = "New unit" on ability nodes).
            if node_kind != "abilities":
                self._ensure_schema_keys(node, node_kind)
            for key, val in node.items():
                if key in MULTILINE_FIELDS and isinstance(val, (str,
                                                                 type(None))):
                    # Long free-form text: a dedicated multi-line Text box,
                    # edited as raw text (newlines kept) unlike the
                    # JSON-encoded single-line fields below.
                    ttk.Label(self.form_frame, text=key).grid(
                        row=row, column=0, sticky=tk.NW, padx=4, pady=1)
                    box = ttk.Frame(self.form_frame)
                    box.grid(row=row, column=1, columnspan=2, sticky=tk.W,
                             padx=4, pady=1)
                    txt = tk.Text(box, width=48, height=_MULTILINE_HEIGHT,
                                  wrap=tk.WORD, undo=True)
                    tsb = ttk.Scrollbar(box, orient=tk.VERTICAL,
                                        command=txt.yview)
                    txt.configure(yscrollcommand=tsb.set)
                    txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
                    tsb.pack(side=tk.RIGHT, fill=tk.Y)
                    txt.insert("1.0", val or "")
                    self.form_texts.append((key, txt))
                    row += 1
                elif isinstance(val, SCALARS):
                    ttk.Label(self.form_frame, text=key).grid(
                        row=row, column=0, sticky=tk.W, padx=4, pady=1)
                    var = tk.StringVar(value=json.dumps(val))
                    if isinstance(val, bool):
                        ttk.Combobox(self.form_frame, textvariable=var,
                                     state="readonly", width=38,
                                     values=["true", "false"]).grid(
                            row=row, column=1, sticky=tk.W, padx=4, pady=1)
                    else:
                        ttk.Entry(self.form_frame, textvariable=var,
                                  width=40).grid(row=row, column=1,
                                                 sticky=tk.W, padx=4,
                                                 pady=1)
                    self.form_vars.append((key, var))
                    row += 1
                elif (isinstance(val, list)
                      and all(isinstance(x, str) for x in val)
                      and key not in ("abilities", "leader_effects",
                                      "models", "weapons")):
                    # string-list properties (keywords, leadership):
                    # edited through a vocabulary-backed dialog
                    ttk.Label(self.form_frame, text=key).grid(
                        row=row, column=0, sticky=tk.W, padx=4, pady=1)
                    lbl = ttk.Label(self.form_frame,
                                    text=", ".join(val) or "(empty)",
                                    width=32)
                    lbl.grid(row=row, column=1, sticky=tk.W, padx=4)
                    ttk.Button(self.form_frame, text="Edit...",
                               command=lambda k=key, n=node,
                               nk=node_kind: self._edit_list(n, k, nk)
                               ).grid(row=row, column=2, padx=2)
                    row += 1
            # ---- copy/paste of whole models / weapons ----
            cp = ttk.Frame(self.form_frame)
            cp.grid(row=row + 1, column=0, columnspan=3, sticky=tk.W,
                    padx=4, pady=12)
            if node_kind in ("models", "weapons"):
                kind = "model" if node_kind == "models" else "weapon"
                ttk.Button(cp, text=f"Copy {kind}",
                           command=lambda k=kind, n=node:
                           self._clip_set((k, n))).pack(side=tk.LEFT)
            paste_kind = (
                "model" if node_kind == "units" and self.clip
                and self.clip[0] == "model"
                else "weapon" if node_kind == "models" and self.clip
                and self.clip[0] == "weapon" else None)
            if paste_kind is not None:
                ttk.Button(cp, text=f"Paste {paste_kind}",
                           command=lambda n=node:
                           self._paste_into(n)).pack(side=tk.LEFT, padx=6)
        # JSON pane: the full node
        self.json_text.delete("1.0", tk.END)
        self.json_text.insert("1.0", json.dumps(node, indent=1,
                                                ensure_ascii=False))
        # Abilities tab: attach the owning unit/model/weapon. Selecting
        # an ability in the tree opens its owner with that ability shown.
        path = self._sel_path
        if len(path) >= 2 and path[-2] == "abilities":
            self.ability_editor.load_node(get_node(self.data, path[:-2]),
                                          select=path[-1])
        elif len(path) >= 2 and path[-2] in ("units", "models", "weapons"):
            lists = (("abilities", "core_abilities", "faction_abilities",
                      "leader_effects")
                     if path[-2] == "units" else ("abilities",))
            self.ability_editor.load_node(node, lists=lists)
        else:
            self.ability_editor.load_node(None)

    def _clip_set(self, item):
        """Single-slot clipboard: the last Copy wins. A deep copy is
        stored so later edits of the source don't change the payload."""
        import copy
        self.clip = (item[0], copy.deepcopy(item[1]))
        self._update_status(f"Copied {item[0]}: "
                            f"{item[1].get('name', '(unnamed)')}")
        # paste-button visibility depends on the clipboard state
        self.on_select()

    def _paste_into(self, node):
        import copy
        kind, payload = self.clip
        key = "models" if kind == "model" else "weapons"
        node.setdefault(key, []).append(copy.deepcopy(payload))
        self._refresh_after_edit()

    def _edit_list(self, node, key, node_kind):
        dlg = StringListDialog(self, f"Edit {key}", node.get(key, []),
                               vocabulary_for(node_kind, key))
        self.wait_window(dlg)
        if dlg.result is not None:
            node[key] = dlg.result
            self._refresh_after_edit()

    def on_ability_change(self):
        """Refresh tree labels and JSON pane after ability edits."""
        self._refresh_after_edit()

    # ---------- remove / duplicate ----------

    def cmd_remove(self):
        """Remove the selected element and everything it contains."""
        node = self._selected_node()
        path = self._sel_path
        if node is None or len(path) < 2 or not isinstance(path[-1], int):
            return
        label = self.tree.item(self.tree.selection()[0], "text")
        if not messagebox.askyesno("Remove", f"Remove '{label}' and all its "
                                             "sub-elements?"):
            return
        del get_node(self.data, path[:-1])[path[-1]]
        self._sel_path = path[:-2] if len(path) > 2 else None
        self._refresh_after_edit(self._sel_path)

    def cmd_duplicate(self):
        """Duplicate the selected element at the same level.

        Naming: units get a ' (copy)' suffix on the copy; models and
        weapons follow the -NN convention (original 'X' becomes 'X-01'
        and the copy 'X-02'; an already numbered original keeps its
        name and the copy gets the next free number)."""
        node = self._selected_node()
        path = self._sel_path
        if node is None or len(path) < 2 or not isinstance(path[-1], int):
            return
        parent = get_node(self.data, path[:-1])
        dup = nt.clone(node)
        listname = path[-2]
        if listname == "units":
            dup["name"] = f"{node.get('name', '')} (copy)"
        elif listname in ("models", "weapons"):
            siblings = [s.get("name", "") for s in parent]
            orig_name, copy_name = nt.duplicate_name_pair(
                node.get("name", ""), siblings)
            node["name"], dup["name"] = orig_name, copy_name
        parent.insert(path[-1] + 1, dup)
        self._refresh_after_edit(path[:-1] + (path[-1] + 1,))

    def _selected_node(self):
        sel = self.tree.selection()
        if not sel or self.data is None:
            return None
        self._sel_path = self.paths[sel[0]]
        return get_node(self.data, self._sel_path)

    # ---------- commands ----------

    def cmd_import(self):
        """Import a native army file into the editor tree for editing."""
        paths = filedialog.askopenfilenames(
            title="Import native JSON (one or more)",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not paths:
            return
        try:
            self.data = native_format.load_many(paths)
            ability_ids.normalize(self.data)
        except Exception as exc:
            messagebox.showerror("Import failed", str(exc))
            return
        # A union of several files has no single source path: disable revert
        # and make the next Save prompt for a combined-file path. A single
        # file keeps its path so revert/save target it as before.
        self.current_path = paths[0] if len(paths) == 1 else None
        self._sel_path = None        # old selection paths are now invalid
        armies = self.data["armies"]
        self.army_idx = 0 if len(armies) == 1 else None
        if self.army_idx is None:
            self.cmd_select_army()
            if self.army_idx is None:    # user cancelled: default to first
                self.army_idx = 0 if armies else None
        self.rebuild_tree()
        self._update_buttons(None)
        self._update_status("Loaded")

    def cmd_merge_json(self):
        """Load a second (new-version) native file and open the selective
        merge dialog against the currently displayed army. Changes flow
        v2 -> v1 on a working copy; only 'Finish' commits them into the
        in-memory data (Save still writes to disk as usual)."""
        if self.data is None or self._army() is None:
            messagebox.showinfo("Merge JSON",
                                "Load a file and select an army first.")
            return
        path = filedialog.askopenfilename(
            title="Select the second (new) JSON to merge from",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            other = native_format.load(path)
        except Exception as exc:
            messagebox.showerror("Merge JSON", f"Load failed: {exc}")
            return
        army1 = self._army()
        armies2 = other.get("armies", [])
        if not armies2:
            messagebox.showerror("Merge JSON",
                                 "The second file contains no armies.")
            return
        # Compare against the army sharing the current one's name; if that
        # is not unique, let the user pick which second-file army to use.
        same = [a for a in armies2 if a.get("name") == army1.get("name")]
        if len(same) == 1:
            army2 = same[0]
        else:
            army2 = self._pick(
                "Select the army to compare against",
                [(f"{a.get('name', '?')} ({len(a.get('units', []))} units)", a)
                 for a in armies2], specials=[])
            if army2 is None:
                return
        import copy
        dlg = MergeDialog(self, copy.deepcopy(army1), army2,
                          name1=army1.get("name", "v1"),
                          name2=army2.get("name", "v2"))
        self.wait_window(dlg)
        if dlg.result is None:
            self._update_status("Merge cancelled")
            return
        # Commit the merged working army back in place and re-stamp ability
        # ids so they stay globally unique after the incoming units.
        self.data["armies"][self.army_idx] = dlg.result
        ability_ids.normalize(self.data)
        self._sel_path = None
        self.rebuild_tree()
        self._update_buttons(None)
        self._update_status("Merge applied (in memory)")

    def _update_status(self, prefix):
        # Merge is available as soon as any army file is loaded.
        if hasattr(self, "_merge_btn"):
            self._merge_btn.config(
                state=tk.NORMAL if self.data is not None else tk.DISABLED)
        army = self._army()
        if army is None:
            self.status.config(text=f"{prefix}: no army selected")
        else:
            self.status.config(
                text=f"{prefix} | Army: {army.get('name', '?')} "
                     f"({len(army.get('units', []))} units) | "
                     f"{self.current_path or 'unsaved'}")

    def cmd_select_army(self):
        """Choose which army the left tree shows."""
        if self.data is None:
            return
        items = [(f"{a.get('name', '?')} ({len(a.get('units', []))} units)",
                  i) for i, a in enumerate(self.data["armies"])]
        if not items:
            messagebox.showinfo("Select army", "The file contains no armies.")
            return
        choice = self._pick("Select army", items, specials=[])
        if choice is None:
            return
        self.army_idx = choice
        self._sel_path = None
        self.rebuild_tree()
        self._update_buttons(None)
        self._update_status("Army selected")

    def cmd_revert(self):
        """Reload the file from disk, discarding unsaved edits."""
        if self.current_path is None:
            messagebox.showinfo("Revert", "No file to revert to.")
            return
        if not messagebox.askyesno("Revert changes",
                                   "Discard ALL unsaved changes and reload "
                                   f"{self.current_path}?"):
            return
        old_name = (self._army() or {}).get("name")
        try:
            self.data = native_format.load(self.current_path)
            ability_ids.normalize(self.data)
        except Exception as exc:
            messagebox.showerror("Revert failed", str(exc))
            return
        names = [a.get("name") for a in self.data["armies"]]
        self.army_idx = names.index(old_name) if old_name in names \
            else (0 if names else None)
        self._sel_path = None
        self.rebuild_tree()
        self._update_buttons(None)
        self._update_status("Reverted")

    def cmd_save(self):
        """Validate the edited army and save it back to native JSON."""
        if self.data is None:
            return
        # Stamp ids on any ability that lacks one, so the persistent
        # enable/disable toggle always has a stable reference to save.
        if ability_ids.normalize(self.data):
            self._refresh_after_edit()
        issues = validation.validate_data(self.data)
        if issues:
            shown = "\n".join(issues[:15])
            if len(issues) > 15:
                shown += f"\n... and {len(issues) - 15} more"
            if not messagebox.askyesno(
                    "Consistency issues",
                    f"{len(issues)} issue(s) found:\n\n{shown}\n\n"
                    "Save anyway?"):
                return
        path = filedialog.asksaveasfilename(
            title="Save native JSON", defaultextension=".json",
            filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            native_format.save(self.data, path)
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            return
        self.current_path = path
        self._update_status("Saved")

    def cmd_apply_form(self):
        """Apply scalar-field edits from the quick form."""
        node = self._selected_node()
        if not isinstance(node, dict):
            return
        key = None
        try:
            for key, var in self.form_vars:
                node[key] = json.loads(var.get())
        except json.JSONDecodeError as exc:
            messagebox.showerror("Invalid value", f"Field '{key}': {exc}")
            return
        # Multi-line fields hold raw text. Text.get always appends a trailing
        # newline, so strip exactly one to preserve the content (including
        # any intentional internal blank lines).
        for key, txt in self.form_texts:
            value = txt.get("1.0", tk.END)
            if value.endswith("\n"):
                value = value[:-1]
            node[key] = value
        self._refresh_after_edit()
        self._warn_issues()

    def cmd_apply_json(self):
        """Replace the selected node with the JSON pane content."""
        if self._selected_node() is None:
            return
        try:
            value = json.loads(self.json_text.get("1.0", tk.END))
        except json.JSONDecodeError as exc:
            messagebox.showerror("Invalid JSON", str(exc))
            return
        set_node(self.data, self._sel_path, value)
        self._refresh_after_edit()
        self._warn_issues()

    # ---------- structural commands ----------

    def _pick(self, title, items, specials):
        """Open the picker; return the chosen payload or None."""
        dlg = PickerDialog(self, title, items, specials)
        self.wait_window(dlg)
        return dlg.choice

    def cmd_add_unit(self):
        """Add a new empty unit to the army and select it in the tree."""
        if self.data is None:
            self.data = {"format": native_format.FORMAT_TAG,
                         "armies": [{"name": "New army", "units": []}]}
            self.army_idx = 0
        if self._army() is None:
            messagebox.showinfo("Add unit", "Select an army first.")
            return
        choice = self._pick(
            "Add unit: new or copy of an existing one",
            nt.collect_units(self.data),
            specials=[("<New empty unit>", nt.new_unit)])
        if choice is None:
            return
        unit = choice() if callable(choice) else nt.clone(choice)
        lst = self._army()["units"]
        lst.append(unit)
        self._refresh_after_edit(self._army_path() + ("units", len(lst) - 1))

    def cmd_add_model(self):
        """Add a new empty model to the selected unit."""
        upath = self._enclosing("units")
        if upath is None:
            messagebox.showinfo("Add model",
                                "Select a unit (or one of its nodes) first.")
            return
        choice = self._pick(
            "Add model: new or copy of an existing one",
            nt.collect_models(self.data),
            specials=[("<New empty model>", nt.new_model)])
        if choice is None:
            return
        model = choice() if callable(choice) else nt.clone(choice)
        lst = get_node(self.data, upath).setdefault("models", [])
        lst.append(model)
        self._refresh_after_edit(upath + ("models", len(lst) - 1))

    def cmd_add_weapon(self):
        """Add a new empty weapon to the selected model."""
        mpath = self._enclosing("models")
        if mpath is None:
            messagebox.showinfo("Add weapon",
                                "Select a model (or one of its nodes) first.")
            return
        choice = self._pick(
            "Add weapon: new or copy of an existing one",
            nt.collect_weapons(self.data),
            specials=[("<New ranged weapon>",
                       lambda: nt.new_weapon("Ranged")),
                      ("<New melee weapon>",
                       lambda: nt.new_weapon("Melee"))])
        if choice is None:
            return
        weapon = choice() if callable(choice) else nt.clone(choice)
        lst = get_node(self.data, mpath).setdefault("weapons", [])
        lst.append(weapon)
        self._refresh_after_edit(mpath + ("weapons", len(lst) - 1))

    def _enclosing(self, listname):
        """Path prefix of the innermost node reached via 'listname' along
        the current selection path, or None if the selection (or the
        path) doesn't traverse that list."""
        path = self._sel_path
        if path is None or self.data is None:
            return None
        for cut in range(len(path), 0, -1):
            if cut >= 2 and path[cut - 2] == listname:
                return path[:cut]
        return None

    def _warn_issues(self):
        """Pop a warning if the data contains incompatible parameters
        (e.g. an invalid characteristic); the edit is kept either way."""
        issues = validation.validate_data(self.data)
        if issues:
            shown = "\n".join(issues[:15])
            if len(issues) > 15:
                shown += f"\n... and {len(issues) - 15} more"
            messagebox.showwarning(
                "Consistency issues",
                f"{len(issues)} issue(s) found:\n\n{shown}")

    def _refresh_after_edit(self, sel_path=None):
        """Rebuild the tree keeping (or setting) the selection path."""
        if sel_path is None:
            sel_path = self._sel_path
        self.rebuild_tree()
        for iid, path in self.paths.items():
            if path == sel_path:
                self.tree.selection_set(iid)
                self.tree.see(iid)
                break
        self._update_status("Edit applied (in memory)")


if __name__ == "__main__":
    EditorApp().mainloop()
