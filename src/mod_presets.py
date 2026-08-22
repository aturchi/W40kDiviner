"""Named bundles of manual modifiers.

The same three or four modifiers get typed in again every evening -
"Guided by Marker Light", "-1 to hit aura", "Oath of Moment" - and each
one has to be picked from a combo box, given the right sign, and added.
A preset is just that list under a name, saved with the session.

Only the MODIFIERS are stored, not the context flags. A flag is one
tick away and its meaning is self-evident; a modifier is a target, a
sign and a value, and getting the sign wrong is silent. Keeping the two
apart also means applying a preset can never quietly change whether the
target was in cover.

No tkinter here: a preset is a list of (label, kind, key, value) tuples,
the same shape SetupPanel keeps, and the store serialises to plain JSON
types.
"""

# Modifier entry: (label, kind, key, value).
#   label  what the combo box called it, e.g. "Hit roll"
#   kind   'rolls' | 'rerolls' | 'weapon' | 'attacker_model' |
#          'defender_model'
#   key    the characteristic or roll; for 'rerolls' a (roll, mode) pair
#   value  signed integer, or None for a re-roll


def normalise(mod) -> tuple:
    """One entry in canonical form. JSON turns tuples into lists, so a
    re-roll key comes back as ['hit', 'fails'] and must become a tuple
    again or two identical presets would stop comparing equal."""
    label, kind, key, value = (list(mod) + [None] * 4)[:4]
    if isinstance(key, list):
        key = tuple(key)
    return (str(label), str(kind), key,
            None if value is None else int(value))


def same(a, b) -> bool:
    return normalise(a) == normalise(b)


def describe(mod) -> str:
    """How the entry reads in the modifier list."""
    label, kind, _key, value = normalise(mod)
    return label if kind == "rerolls" else f"{label}: {value:+d}"


def summary(mods, limit: int = 3) -> str:
    """Short one-line description of a whole preset."""
    mods = [normalise(m) for m in mods]
    if not mods:
        return "empty"
    head = ", ".join(describe(m) for m in mods[:limit])
    return head + (f" (+{len(mods) - limit} more)" if len(mods) > limit
                   else "")


class PresetStore:
    """Named presets, in insertion order."""

    def __init__(self, data=None):
        self._items = {}
        for name, mods in (data or {}).items():
            self._items[str(name)] = [normalise(m) for m in mods]

    # ---------- reading ----------

    def names(self) -> list:
        return list(self._items)

    def get(self, name) -> list:
        return list(self._items.get(name, []))

    def __contains__(self, name):
        return name in self._items

    def __len__(self):
        return len(self._items)

    def to_json(self) -> dict:
        """Plain types only: tuples become lists on the way out."""
        return {name: [list(m) for m in mods]
                for name, mods in self._items.items()}

    # ---------- writing ----------

    def save(self, name, mods):
        """Store (or overwrite) a preset. An empty name or an empty
        modifier list is refused: both would produce a preset that does
        nothing but take up a slot in the menu."""
        name = str(name).strip()
        if not name or not mods:
            return False
        self._items[name] = [normalise(m) for m in mods]
        return True

    def delete(self, name) -> bool:
        return self._items.pop(name, None) is not None

    def rename(self, old, new) -> bool:
        new = str(new).strip()
        if old not in self._items or not new or new in self._items:
            return False
        # Rebuilt rather than reassigned, to keep the original position
        # in the menu instead of jumping to the end.
        self._items = {(new if k == old else k): v
                       for k, v in self._items.items()}
        return True


def apply_to(current, preset_mods) -> tuple:
    """Add a preset to the modifiers already in the panel.

    Adding rather than replacing, because two presets are routinely in
    play at once ("marker light" AND "-1 to hit aura"). Entries already
    present are skipped instead of being added twice, which would double
    a modifier without any visible sign in the list.

    Returns (new list, how many were added, how many were skipped).
    """
    out = [normalise(m) for m in current]
    added = skipped = 0
    for mod in preset_mods:
        mod = normalise(mod)
        if any(same(mod, existing) for existing in out):
            skipped += 1
            continue
        out.append(mod)
        added += 1
    return out, added, skipped
