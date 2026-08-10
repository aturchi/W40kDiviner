"""Pure (Tk-free) state for the army load / join dialog.

ArmyLoadState holds the available armies as single-army native dicts,
supports joining a selected subset into a new named army (native_format.
join_raw), and builds the union native dict for the chosen armies. The GUI
(army_load_dialog.ArmyLoadDialog) is a thin layer over this.
"""

import native_format as nf


class ArmyLoadState:
    """Pure (Tk-free) state for the army load/join dialog: available armies as single-army native dicts, with join() to merge a subset and build() to produce the union dict to import."""
    def __init__(self, single_army_dicts):
        # each item: a native dict with exactly one army
        self.armies = list(single_army_dicts)

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

    def build(self, indices):
        """Union native dict for the chosen indices (concatenated armies),
        migrated + validated. Empty selection -> None."""
        idx = sorted(set(indices))
        if not idx:
            return None
        armies = []
        for i in idx:
            armies.extend(self.armies[i]["armies"])
        out = {"format": nf.FORMAT_TAG, "armies": armies}
        nf.validate(out)
        return out
