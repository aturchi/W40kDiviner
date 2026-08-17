"""Pure diff / selective-merge logic for the profile editor "Merge JSON".

Compares two armies of the native format (see :mod:`native_format`) at the
unit level and, for units present in both, produces a flat list of atomic,
individually-acceptable differences flowing from the SECOND army (the new
version, ``v2``) into the FIRST (``v1``).

No tkinter here: the dialog (``merge_dialog``) renders these records and
calls :func:`apply_change` / :func:`merge_unit` / :func:`delete_unit`;
everything below is unit-testable.

Matching keys (name-based, consistent with the rest of the suite):

* units, models, weapons and abilities are matched by their ``name``
  (abilities fall back to ``description`` when unnamed);
* a rename therefore shows up as one ``removed`` + one ``added``, not a
  modification (documented limitation, agreed out of scope);
* duplicate names inside one list collapse to the first occurrence - real
  rosters use the ``-NN`` duplicate convention so this is not hit in
  practice.

Volatile data: an ability's ``id`` is IGNORED when comparing (ids are
random per file). A whole-ability ``replaced`` keeps v1's id, so the
persistent enable/disable toggle references stay stable; the caller
re-stamps ids for global uniqueness after committing a merge
(``ability_ids.ensure_ids``).

Change granularity (agreed with the user):

* box 2 ("other")   - every non-ability atom at any level: unit fields,
  model/weapon characteristics, per-keyword add/remove, and a whole
  model/weapon added or removed;
* box 3 ("ability") - abilities at unit / model / weapon level (plus unit
  ``leader_effects``), at WHOLE-ability granularity: added / removed /
  replaced.

Colours are the Okabe-Ito colourblind-safe palette; every record also
carries a text prefix so the meaning survives without colour.
"""

import copy
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

# semantic tag -> display colour (Okabe-Ito) and colour-independent prefix
COLORS = {"identical": "#000000", "added": "#009E73",
          "removed": "#D55E00", "changed": "#0072B2"}
PREFIX = {"identical": "= ", "added": "+ ", "removed": "\u2212 ",
          "changed": "~ "}

# top-level unit status -> tag (drives colour/prefix in box 1)
_STATUS_TAG = {"identical": "identical", "added": "added",
               "removed": "removed", "modified": "changed"}

_SCALARS = (str, int, float, bool, type(None))
# keys that are structure or volatile - never compared as scalar fields
_SKIP_SCALAR = frozenset({"name", "id", "keywords", "abilities",
                          "core_abilities", "faction_abilities", "models",
                          "weapons", "leadership", "support",
                          "leader_effects"})
# list fields compared as unordered sets (keyword-style, per-item accept)
_SET_LISTS = ("keywords", "leadership", "support")
_SET_LABEL = {"keywords": "keyword", "leadership": "leads",
              "support": "supports"}


# ---------- data records ----------

@dataclass
class Change:
    """One atomic, individually-acceptable difference (applied v1 <- v2).

    op        : 'changed' (scalar field), 'added' (v2-only item),
                'removed' (v1-only item), 'replaced' (whole ability).
    category  : 'other' (box 2) or 'ability' (box 3).
    locator   : steps to the PARENT container in v1 - a str is a dict key,
                a ('models'|'weapons', name) tuple selects a keyed item.
    key       : field name (changed) or list name (add/remove/replace).
    label     : human text WITHOUT the prefix.
    tag       : 'added' | 'removed' | 'changed' (colour/prefix key).
    old / new : scalar values, for 'changed' (display + apply).
    ident     : keyword value or item name, for add/remove/replace.
    payload   : deep-copied item to insert / replacement.
    """
    op: str
    category: str
    locator: Tuple
    key: str
    label: str
    tag: str
    old: Any = None
    new: Any = None
    ident: Any = None
    payload: Any = None

    @property
    def color(self) -> str:
        return COLORS[self.tag]

    @property
    def display(self) -> str:
        return PREFIX[self.tag] + self.label


@dataclass
class UnitRow:
    """One row of the top-level (box 1) unit comparison."""
    name: str
    status: str                   # identical | added | removed | modified
    unit1: Optional[dict]
    unit2: Optional[dict]

    @property
    def tag(self) -> str:
        return _STATUS_TAG[self.status]

    @property
    def color(self) -> str:
        return COLORS[self.tag]

    @property
    def display(self) -> str:
        return PREFIX[self.tag] + self.name


# ---------- small helpers ----------

def _item_name(item: dict) -> str:
    """Match key of a keyed-list item: 'name', falling back to
    'description' (unnamed abilities) then a constant placeholder."""
    return item.get("name") or item.get("description") or "<no name>"


def _norm(name) -> str:
    """Normalised match key for a name: case- and surrounding-whitespace-
    insensitive. Two names that differ only by letter case or padding
    (common between the 40k.app and Wahapedia exports, e.g. 'Commander In
    Coldstar Battlesuit' vs 'Commander in Coldstar Battlesuit') match."""
    return (name or "").strip().casefold()


def _pair_by_name(a_list, b_list):
    """Pair the items of two keyed lists by :func:`_norm` of their name.

    Yields ``(display_name, a_item_or_None, b_item_or_None)`` in a stable
    order: v1 (a) items first in their original order, then v2-only items.
    ``display_name`` is the v1 item's ORIGINAL-case name when present, else
    the v2 item's - so labels and locators keep the v1 spelling and a
    case-only difference in the name is never itself reported as a change.
    First occurrence wins on duplicate normalised names (see the
    duplicate-name caveat in the module docstring)."""
    a_by, b_by = {}, {}
    for item in a_list or []:
        a_by.setdefault(_norm(_item_name(item)), item)
    for item in b_list or []:
        b_by.setdefault(_norm(_item_name(item)), item)
    out, seen = [], set()
    for item in a_list or []:
        k = _norm(_item_name(item))
        if k in seen:
            continue
        seen.add(k)
        out.append((_item_name(item), item, b_by.get(k)))
    for item in b_list or []:
        k = _norm(_item_name(item))
        if k in seen:
            continue
        seen.add(k)
        out.append((_item_name(item), None, item))
    return out


def _ordered_union(a_keys, b_keys) -> list:
    """v1 keys in their original order, then v2-only keys appended - a
    deterministic order that reads naturally (existing items first)."""
    seen = list(a_keys)
    seen += [k for k in b_keys if k not in a_keys]
    return seen


def _fmt(value) -> str:
    """Compact scalar rendering for 'old -> new' labels."""
    return "\u2205" if value is None else str(value)


def _strip_ids(obj):
    """Deep copy of 'obj' with EVERY 'id' key removed, at any depth.
    Ids are volatile (random per file, re-stamped on save), so they must
    never make two otherwise identical items compare as different: a
    top-level ability id, or one buried in an effect / condition payload,
    would otherwise show the ability as 'replaced' with an inspector that
    lists no difference at all."""
    if isinstance(obj, dict):
        return {k: _strip_ids(v) for k, v in obj.items() if k != "id"}
    if isinstance(obj, list):
        return [_strip_ids(x) for x in obj]
    return copy.deepcopy(obj)


# ---------- diff builders ----------

def _diff_scalars(a: dict, b: dict, locator, hpath: str,
                  out: List[Change]) -> None:
    """Emit a 'changed' record for each differing scalar field (any key
    present in either dict, except structural/volatile ones). A string
    field that differs only by letter case or surrounding whitespace is
    treated as equal (the two sources capitalise differently), so it is
    not reported."""
    for k in _ordered_union(list(a), list(b)):
        if k in _SKIP_SCALAR:
            continue
        av, bv = a.get(k), b.get(k)
        if not (isinstance(av, _SCALARS) and isinstance(bv, _SCALARS)):
            continue
        if av == bv:
            continue
        if isinstance(av, str) and isinstance(bv, str) \
                and _norm(av) == _norm(bv):
            continue                    # case-/whitespace-only: noise
        out.append(Change(
            op="changed", category="other", locator=locator, key=k,
            old=av, new=bv, tag="changed",
            label=f"{hpath}{k}: {_fmt(av)} \u2192 {_fmt(bv)}"))


def _diff_sets(a: dict, b: dict, locator, hpath: str, out: List[Change],
               keys=_SET_LISTS) -> None:
    """Emit per-item added/removed records for unordered list fields
    (keywords / leadership / support), compared CASE-INSENSITIVELY - the
    two exports capitalise keywords differently (40k.app ALL-CAPS vs
    Wahapedia Title-case), so only genuine additions/removals are shown,
    not case-only ones. Order is sorted for determinism; the reported /
    accepted value keeps its own source's spelling."""
    for k in keys:
        sa = list(a.get(k, []) or [])
        sb = list(b.get(k, []) or [])
        na = {_norm(x) for x in sa}
        nb = {_norm(x) for x in sb}
        for x in sorted(v for v in sa if _norm(v) not in nb):
            out.append(Change(
                op="removed", category="other", locator=locator, key=k,
                ident=x, tag="removed",
                label=f"{hpath}{_SET_LABEL.get(k, k)} {x}"))
        for x in sorted(v for v in sb if _norm(v) not in na):
            out.append(Change(
                op="added", category="other", locator=locator, key=k,
                ident=x, payload=x, tag="added",
                label=f"{hpath}{_SET_LABEL.get(k, k)} {x}"))


def _diff_abilities(a_list, b_list, locator, key: str, hpath: str,
                    out_ab: List[Change]) -> None:
    """Whole-ability diff of two ability lists, keyed by name (id ignored,
    case-insensitive). Emits added / removed / replaced records into the
    ability bucket."""
    for name, ax, bx in _pair_by_name(a_list, b_list):
        if ax is not None and bx is not None:
            if _strip_ids(ax) != _strip_ids(bx):
                out_ab.append(Change(
                    op="replaced", category="ability", locator=locator,
                    key=key, ident=name, payload=copy.deepcopy(bx),
                    tag="changed", label=f"{hpath}[ability] {name}"))
        elif bx is not None:
            out_ab.append(Change(
                op="added", category="ability", locator=locator, key=key,
                ident=name, payload=copy.deepcopy(bx), tag="added",
                label=f"{hpath}[ability] {name}"))
        else:
            out_ab.append(Change(
                op="removed", category="ability", locator=locator, key=key,
                ident=name, tag="removed", label=f"{hpath}[ability] {name}"))


def _diff_weapons(a_list, b_list, mloc, hpath: str,
                  out: List[Change], out_ab: List[Change]) -> None:
    """Diff two weapon lists (keyed by name, case-insensitive): whole
    weapon add/remove into 'other', otherwise recurse scalars + keywords
    + abilities."""
    for name, ax, bx in _pair_by_name(a_list, b_list):
        if ax is not None and bx is not None:
            wloc = mloc + (("weapons", name),)
            wh = f"{hpath}{name} \u203a "
            _diff_scalars(ax, bx, wloc, wh, out)
            _diff_sets(ax, bx, wloc, wh, out, keys=("keywords",))
            _diff_abilities(ax.get("abilities", []), bx.get("abilities", []),
                            wloc, "abilities", wh, out_ab)
        elif bx is not None:
            out.append(Change(
                op="added", category="other", locator=mloc, key="weapons",
                ident=name, payload=copy.deepcopy(bx), tag="added",
                label=f"{hpath}[weapon] {name}"))
        else:
            out.append(Change(
                op="removed", category="other", locator=mloc, key="weapons",
                ident=name, tag="removed", label=f"{hpath}[weapon] {name}"))


def _diff_models(a_list, b_list, out: List[Change],
                 out_ab: List[Change]) -> None:
    """Diff two model lists (keyed by name, case-insensitive): whole model
    add/remove into 'other', otherwise recurse scalars + keywords +
    abilities + weapons."""
    for name, ax, bx in _pair_by_name(a_list, b_list):
        if ax is not None and bx is not None:
            mloc = (("models", name),)
            mh = f"{name} \u203a "
            _diff_scalars(ax, bx, mloc, mh, out)
            _diff_sets(ax, bx, mloc, mh, out, keys=("keywords",))
            _diff_abilities(ax.get("abilities", []), bx.get("abilities", []),
                            mloc, "abilities", mh, out_ab)
            _diff_weapons(ax.get("weapons", []), bx.get("weapons", []),
                          mloc, mh, out, out_ab)
        elif bx is not None:
            out.append(Change(
                op="added", category="other", locator=(), key="models",
                ident=name, payload=copy.deepcopy(bx), tag="added",
                label=f"[model] {name}"))
        else:
            out.append(Change(
                op="removed", category="other", locator=(), key="models",
                ident=name, tag="removed", label=f"[model] {name}"))


def diff_unit(unit1: dict, unit2: dict) -> Tuple[List[Change], List[Change]]:
    """Full diff of two units matched by name. Returns
    (other_changes, ability_changes) i.e. the box-2 and box-3 lists,
    every record applying v2's state onto v1."""
    out: List[Change] = []
    out_ab: List[Change] = []
    _diff_scalars(unit1, unit2, (), "", out)
    _diff_sets(unit1, unit2, (), "", out)          # keywords/leadership/support
    _diff_abilities(unit1.get("abilities", []), unit2.get("abilities", []),
                    (), "abilities", "", out_ab)
    _diff_abilities(unit1.get("core_abilities", []),
                    unit2.get("core_abilities", []),
                    (), "core_abilities", "[core] ", out_ab)
    _diff_abilities(unit1.get("faction_abilities", []),
                    unit2.get("faction_abilities", []),
                    (), "faction_abilities", "[faction] ", out_ab)
    _diff_abilities(unit1.get("leader_effects", []),
                    unit2.get("leader_effects", []),
                    (), "leader_effects", "[leader] ", out_ab)
    _diff_models(unit1.get("models", []), unit2.get("models", []), out, out_ab)
    return out, out_ab


def diff_army(army1: dict, army2: dict) -> List[UnitRow]:
    """Top-level (box 1) comparison: one UnitRow per unit, matched by name
    case-insensitively across both armies, sorted case-insensitively
    (matching the editor's display). A unit in both is 'modified' when
    diff_unit finds any change, else 'identical'."""
    rows: List[UnitRow] = []
    for name, u1, u2 in _pair_by_name(army1.get("units", []),
                                      army2.get("units", [])):
        if u1 is not None and u2 is not None:
            other, ability = diff_unit(u1, u2)
            status = "modified" if (other or ability) else "identical"
        elif u2 is not None:
            status = "added"
        else:
            status = "removed"
        rows.append(UnitRow(name, status, u1, u2))
    rows.sort(key=lambda r: (r.name or "").casefold())
    return rows


# ---------- apply / merge ----------

def _find_named(lst, name):
    """First item in lst whose normalised match key == normalised name
    (case-insensitive); KeyError if absent."""
    target = _norm(name)
    for item in lst:
        if _norm(_item_name(item)) == target:
            return item
    raise KeyError(name)


def _resolve(node, locator):
    """Walk a locator to the parent container inside 'node' (a unit)."""
    for step in locator:
        if isinstance(step, tuple):
            list_key, name = step
            node = _find_named(node[list_key], name)
        else:
            node = node[step]
    return node


def apply_change(unit1: dict, ch: Change) -> None:
    """Mutate unit1 in place so it adopts v2's state for this one change.

    Locators are semantic (name-keyed), never raw indices, so a batch of
    changes from the same diff can be applied in any order without index
    drift. The dialog still re-diffs after applying, per the agreed design.
    """
    parent = _resolve(unit1, ch.locator)
    if ch.op == "changed":
        parent[ch.key] = copy.deepcopy(ch.new)
    elif ch.op == "added":
        if ch.key in _SET_LISTS:
            lst = parent.setdefault(ch.key, [])
            if ch.ident not in lst:
                lst.append(ch.ident)
        else:
            parent.setdefault(ch.key, []).append(copy.deepcopy(ch.payload))
    elif ch.op == "removed":
        lst = parent.get(ch.key, [])
        if ch.key in _SET_LISTS:
            parent[ch.key] = [x for x in lst if x != ch.ident]
        else:
            parent[ch.key] = [x for x in lst
                              if _norm(_item_name(x)) != _norm(ch.ident)]
    elif ch.op == "replaced":
        lst = parent.get(ch.key, [])
        for i, x in enumerate(lst):
            if _norm(_item_name(x)) == _norm(ch.ident):
                new = copy.deepcopy(ch.payload)
                if x.get("id"):          # keep v1 id -> stable toggle ref
                    new["id"] = x["id"]
                lst[i] = new
                break


def merge_unit(army1: dict, unit2: dict) -> None:
    """Add a whole v2-only unit (box-1 green) into army1 as a deep copy."""
    army1.setdefault("units", []).append(copy.deepcopy(unit2))


def delete_unit(army1: dict, unit_name: str) -> None:
    """Remove a v1-only unit (box-1 red) from army1 by name
    (case-insensitive)."""
    army1["units"] = [u for u in army1.get("units", [])
                      if _norm(_item_name(u)) != _norm(unit_name)]


# ---------- field-level inspector (box-3 detail, read-only) ----------

_MISSING = object()          # sentinel: a key/index present on one side only


def current_item(unit: dict, ch: "Change"):
    """The working-copy item that a 'replaced'/'removed' Change refers to
    (parent resolved by locator, item matched by name in ch.key), or None
    if it can no longer be found. Lets the dialog fetch the live v1 side
    of a modified ability for the inspector box."""
    try:
        parent = _resolve(unit, ch.locator)
    except KeyError:
        return None
    for x in parent.get(ch.key, []):
        if _norm(_item_name(x)) == _norm(ch.ident):
            return x
    return None


def _walk_detail(a, b, path: tuple, out: list) -> None:
    """Recursive field-level diff of two matched objects. Aligns dicts by
    key and lists by index; 'id' keys are ignored. Appends
    (tag, label) pairs for each differing leaf."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in _ordered_union(list(a), list(b)):
            if k == "id":
                continue
            _walk_detail(a.get(k, _MISSING), b.get(k, _MISSING),
                         path + (str(k),), out)
    elif isinstance(a, list) and isinstance(b, list):
        for i in range(max(len(a), len(b))):
            av = a[i] if i < len(a) else _MISSING
            bv = b[i] if i < len(b) else _MISSING
            _walk_detail(av, bv, path + (f"[{i}]",), out)
    else:
        label = ".".join(path).replace(".[", "[") or "(root)"
        if a is _MISSING and b is not _MISSING:
            out.append(("added", f"{label}: {_fmt(b)}"))
        elif b is _MISSING and a is not _MISSING:
            out.append(("removed", f"{label}: {_fmt(a)}"))
        elif a != b:
            out.append(("changed", f"{label}: {_fmt(a)} \u2192 {_fmt(b)}"))


def diff_detail(old, new) -> List[Change]:
    """Read-only, field-level diff of two matched objects (typically the
    two versions of a 'replaced' ability). Returns display-only Change
    records (category 'detail', empty locator - never applied): the
    inspector box shows WHAT changed inside an item, while acceptance
    stays at whole-item granularity in box 2/3. 'id' is ignored at every
    depth, including inside a whole sub-object that was added or removed
    (where it would otherwise be printed as part of the value)."""
    rows: list = []
    _walk_detail(_strip_ids(old), _strip_ids(new), (), rows)
    return [Change(op=tag, category="detail", locator=(), key="",
                   label=label, tag=tag) for tag, label in rows]
