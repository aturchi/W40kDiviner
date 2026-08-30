"""Pure (Tk-free) state for the army load / join / save dialog.

ArmyLoadState holds the available armies as single-army native dicts and
offers the four operations the dialog is made of:

- :meth:`join` merges a ticked subset into ONE new named army
  (``native_format.join_raw``);
- :meth:`save` writes the ticked armies to one file, each keeping its
  own identity (``native_format.join``). That is the second kind of
  join, and it is an ACTION rather than a list entry on purpose: the
  mode is flat and associative, so a file of files is the same file as
  the flat one, and what it would need a name for is the path the save
  dialog already asks for;
- :meth:`rename` fixes a name, which both join modes need: they reject
  duplicate army names, and rosters really do collide (two files that
  both carry "Space Marines", or one faction spelled two ways);
- :meth:`build` produces the union dict to hand back to the caller.

The GUI (army_load_dialog.ArmyLoadDialog) is a thin layer over this.
"""

import ability_ids
import native_format as nf


class ArmyLoadState:
    """Pure (Tk-free) state for the army load/join/save dialog: available armies as single-army native dicts, with join() to merge a subset, rename() to fix a name, save() to write a file and build() to produce the union dict to import."""

    def __init__(self, single_army_dicts):
        # each item: a native dict with exactly one army
        self.armies = list(single_army_dicts)
        # Whether the working set no longer matches what was loaded. The
        # caller uses it to decide whether the document in memory is still
        # a file it could save back to without asking.
        self.modified = False

    def names(self):
        """Display names of the available armies, in list order."""
        return [d["armies"][0]["name"] for d in self.armies]

    def join(self, indices, new_name):
        """Join the armies at 'indices' into one new army named 'new_name';
        the originals are removed and the joined army is appended. Raises
        ValueError on <2 armies, empty name, or duplicate source names."""
        idx = sorted(set(indices))
        if len(idx) < 2:
            raise ValueError("select at least two armies to join")
        if not new_name.strip():
            raise ValueError("the joined army needs a name")
        picked = [self.armies[i] for i in idx]
        joined = nf.join_raw(picked, new_name.strip())
        for i in reversed(idx):
            del self.armies[i]
        self.armies.append(joined)
        self.modified = True

    def rename(self, index, new_name):
        """Rename the army at 'index'. Raises ValueError on an empty name
        or one another entry already carries.

        Renaming is not cosmetic: join_raw and join both reject duplicate
        army names, and a multi-army file holding two armies under one
        name cannot be told apart afterwards. This is the only way out of
        a selection that collides."""
        name = str(new_name).strip()
        if not name:
            raise ValueError("an army needs a name")
        for i, other in enumerate(self.names()):
            if i != index and other == name:
                raise ValueError(f"another army is already called {name!r}")
        self.armies[index]["armies"][0]["name"] = name
        self.modified = True

    def conflicts(self, indices=None):
        """Names carried by two or more of the given entries (all of them
        when 'indices' is None), sorted.

        Behind both the dialog's warning line and the refusal to save: a
        native file whose armies share a name is one neither join mode
        would have produced, and nothing downstream can separate them
        again."""
        names = self.names()
        idx = range(len(names)) if indices is None else sorted(set(indices))
        seen, dup = set(), set()
        for i in idx:
            if names[i] in seen:
                dup.add(names[i])
            seen.add(names[i])
        return sorted(dup)

    def build(self, indices, strict=False):
        """Union native dict for the chosen indices (concatenated armies),
        migrated + validated. Empty selection -> None.

        'strict' also rejects duplicate army names. It is off for import,
        where the caller may still want to look at a colliding pair, and
        ON for save, which must not write a file that the joins would
        refuse to read back."""
        idx = sorted(set(indices))
        if not idx:
            return None
        if strict:
            dup = self.conflicts(idx)
            if dup:
                raise ValueError("two armies share a name: "
                                 + ", ".join(repr(n) for n in dup))
        armies = []
        for i in idx:
            armies.extend(self.armies[i]["armies"])
        out = {"format": nf.FORMAT_TAG, "armies": armies}
        nf.validate(out)
        return out

    def save(self, indices, path):
        """Write the chosen armies to 'path' as one native file: a
        single-army file for one entry, a multi-army file for several.

        Ability ids are made globally unique first: ids are only unique
        per SOURCE file, so merging two sources without re-stamping
        writes a file whose ability toggles address two abilities at
        once.

        Returns (armies, units, ids_stamped)."""
        data = self.build(indices, strict=True)
        if data is None:
            raise ValueError("select at least one army to save")
        stamped = ability_ids.ensure_ids(data)
        nf.save(data, path)
        units = sum(len(a.get("units", [])) for a in data["armies"])
        return len(data["armies"]), units, stamped
