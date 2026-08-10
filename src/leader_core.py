"""Leader-attachment helpers shared by the attack analyzer and the
game assistant (GUI-free).

Object level (analyzer): split Unit lists into leaders/others and test
compatibility - the actual join is unit.attach_leader(leader), which
owns the shared-abilities semantics.

Native-dict level (game assistant): roster entries are normalised to
{'unit': dict, 'leader': dict|None}; the tree shows the concatenated
model entries of both parts, masks are collected with a GLOBAL model
index and split back here, and the combined Unit is rebuilt at attack
time so the masking machinery keeps working unchanged."""

import attack_resolve
from unit_model import units_from_native


# ---------------- object level (attack analyzer) ----------------


def is_leader_unit(unit) -> bool:
    """True for a unit that CAN lead: a non-empty leadership list. This is
    the standalone-leader test used to offer the join UI (unit.is_leader()
    additionally requires an already-attached unit and is for combined
    units only)."""
    return bool(getattr(unit, "leadership", None))


def is_support_unit(unit) -> bool:
    """True for a unit that CAN support: a non-empty support list. The
    standalone-support counterpart of is_leader_unit."""
    return bool(getattr(unit, "support", None))


def split_leaders(units):
    """(leaders, others) preserving order."""
    leaders = [u for u in units if is_leader_unit(u)]
    others = [u for u in units if not is_leader_unit(u)]
    return leaders, others


def split_supports(units):
    """(supports, others) preserving order, mirroring split_leaders for
    the separate support slot."""
    supports = [u for u in units if is_support_unit(u)]
    others = [u for u in units if not is_support_unit(u)]
    return supports, others


def compatibility(leader, units):
    """[bool, ...]: which units the leader can be attached to."""
    return [u.can_attach(leader) for u in units]


def support_compatibility(support, units):
    """[bool, ...]: which units the support can be attached to."""
    return [u.can_support(support) for u in units]


class ArmyJoinState:
    """Pure join model for ONE army (game-assistant dialog). Holds three
    pools of native unit dicts -- leaders (can lead), supports (can
    support) and others -- plus a list of combined entries. Joining a
    helper to a target removes BOTH from their pools and adds a combined
    entry (the game-assistant rule: joined units disappear from the source
    lists). Unjoining restores the parts. entries() yields the final
    leader_core entries: combined ones plus a plain make_entry for every
    unit still in a pool."""

    def __init__(self, unit_dicts, fmt="w40k-sim/6"):
        self.fmt = fmt
        self.leaders, rest = native_leaders_others(unit_dicts, fmt)
        self.supports, self.others = native_supports_others(rest, fmt)
        self.joined = []            # [{"unit","leader","support"}]

    def can_lead(self, leader_dict, target_dict):
        """True if the leader dict can lead the target dict (keyword match)."""
        return native_can_attach(leader_dict, target_dict, self.fmt)

    def can_support(self, support_dict, target_dict):
        """True if the support dict can support the target dict (keyword
        match)."""
        return native_can_support(support_dict, target_dict, self.fmt)

    def join_combo(self, target_dict, leader_dict=None, support_dict=None):
        """Build ONE joined entry from a target plus an optional leader
        and/or support, removing every chosen part from its pool. Powers
        the single Join button (leader+unit, support+unit, or
        leader+support+unit)."""
        self._remove(target_dict)
        if leader_dict is not None:
            self._remove(leader_dict)
        if support_dict is not None:
            self._remove(support_dict)
        self.joined.append(make_entry(target_dict, leader_dict,
                                      support_dict))

    def join_leader(self, leader_dict, target_dict):
        """Combine leader + target into a new joined entry; remove both
        from their pools (target may itself be a support)."""
        self._remove(leader_dict)
        self._remove(target_dict)
        self.joined.append(make_entry(target_dict, leader_dict, None))

    def join_support(self, support_dict, target_dict):
        """Combine support + target into a new joined entry; remove both
        from their pools."""
        self._remove(support_dict)
        self._remove(target_dict)
        self.joined.append(make_entry(target_dict, None, support_dict))

    def add_to_joined(self, entry_index, helper_dict, slot):
        """Attach an extra helper (slot 'leader'|'support') to an existing
        joined entry, consuming the helper from its pool. Enables
        leader+support units built in two steps."""
        self._remove(helper_dict)
        e = dict(self.joined[entry_index])
        e[slot] = helper_dict
        self.joined[entry_index] = e

    def unjoin(self, entry_index):
        """Split a joined entry back into its parts, returned to pools."""
        e = self.joined.pop(entry_index)
        for part in ("unit", "leader", "support"):
            if e.get(part):
                self._restore(e[part])

    def _remove(self, ud):
        for pool in (self.leaders, self.supports, self.others):
            if ud in pool:
                pool.remove(ud)
                return

    def _restore(self, ud):
        u = units_from_native({"format": self.fmt, "armies": [
            {"name": "x", "units": [ud]}]})[0]
        if is_leader_unit(u):
            self.leaders.append(ud)
        elif is_support_unit(u):
            self.supports.append(ud)
        else:
            self.others.append(ud)

    def entries(self):
        """Final leader_core entries: the combined ones plus a plain entry
        for each unit still unjoined."""
        out = list(self.joined)
        for pool in (self.leaders, self.supports, self.others):
            out += [make_entry(u) for u in pool]
        return out


# ---------------- native-dict level (game assistant) ----------------


def make_entry(unit_dict, leader_dict=None, support_dict=None) -> dict:
    """A roster entry: the base unit plus an optional attached leader and
    an optional attached support (independent slots; a unit may carry one
    of each). Model order for global indexing is unit, then leader, then
    support."""
    return {"unit": unit_dict, "leader": leader_dict,
            "support": support_dict}


def entry_label(entry) -> str:
    """Human-readable label for a roster entry: the base unit's name with
    ' + <name> [JOINED]' appended for each attached leader/support."""
    name = entry["unit"]["name"]
    for slot in ("leader", "support"):
        if entry.get(slot) is not None:
            name += f" + {entry[slot]['name']} [JOINED]"
    return name


def entry_points(entry) -> int:
    """Total points of a roster entry: the base unit plus any attached
    leader and support."""
    pts = entry["unit"].get("points") or 0
    for slot in ("leader", "support"):
        if entry.get(slot) is not None:
            pts += entry[slot].get("points") or 0
    return pts


def _entry_parts(entry):
    """The present parts of an entry in global-index order:
    [('unit', dict), ('leader', dict)?, ('support', dict)?]."""
    parts = [("unit", entry["unit"])]
    for slot in ("leader", "support"):
        if entry.get(slot) is not None:
            parts.append((slot, entry[slot]))
    return parts


def _segment_offsets(entry):
    """Cumulative model-count offsets per present part, in order. Returns
    [(slot, dict, start, length), ...] so a global model index gmi belongs
    to the part with start <= gmi < start+length."""
    out, start = [], 0
    for slot, d in _entry_parts(entry):
        n = len(d.get("models", []))
        out.append((slot, d, start, n))
        start += n
    return out


def entry_models(entry):
    """Concatenated model entries for display, in global-index order:
    unit's, then leader's, then support's. Returns
    [(global_index, model_dict), ...]."""
    models = []
    for _slot, d, _start, _n in _segment_offsets(entry):
        models += d.get("models", [])
    return list(enumerate(models))


def _split_indexed(entry, mapping):
    """Split a {global_model_index: value} or {(gmi, wi): value} /
    set-of-(gmi, wi) into one re-based mapping per present part, keyed by
    slot name. Model indices are re-based to each part's local range."""
    segs = _segment_offsets(entry)

    def gmi_of(key):
        return key[0] if isinstance(key, tuple) else key

    def seg_of(gmi):
        for slot, _d, start, n in segs:
            if start <= gmi < start + n:
                return slot, start
        return None, 0

    def rebase(key, start):
        if isinstance(key, tuple):
            return (key[0] - start, key[1])
        return key - start

    out = {slot: (set() if isinstance(mapping, set) else {})
           for slot, _d, _s, _n in segs}
    items = mapping if isinstance(mapping, set) else mapping.items()
    for it in items:
        key = it if isinstance(mapping, set) else it[0]
        slot, start = seg_of(gmi_of(key))
        if slot is None:
            continue
        if isinstance(mapping, set):
            out[slot].add(rebase(key, start))
        else:
            out[slot][rebase(key, start)] = it[1]
    return out


def build_entry_unit(entry, masked_copies, masked_weapons, weapon_counts,
                     fmt="w40k-sim/6"):
    """Combined (or plain) Unit from a roster entry and the table state
    (global model indices). Masked-out parts are dropped; a helper (leader
    or support) that is fully masked simply does not attach, and if the
    base unit is fully masked a surviving helper fights alone. Returns None
    when nothing is left."""
    mc = _split_indexed(entry, masked_copies)
    mw = _split_indexed(entry, masked_weapons)
    wc = _split_indexed(entry, weapon_counts)

    def rebuild(slot):
        ud = entry.get(slot)
        if ud is None:
            return None
        f = attack_resolve.filter_native_unit(
            ud, mc.get(slot, {}), mw.get(slot, {}), wc.get(slot, {}))
        if not f["models"]:
            return None
        return units_from_native({"format": fmt, "armies": [
            {"name": "table", "units": [f]}]})[0]

    unit = rebuild("unit")
    leader = rebuild("leader")
    support = rebuild("support")
    # If the base unit is gone, a surviving helper fights alone (prefer the
    # leader, else the support).
    if unit is None:
        return leader or support
    if leader is not None and unit.can_attach(leader):
        unit = unit.attach_leader(leader)
    if support is not None and unit.can_support(support):
        unit = unit.attach_support(support)
    return unit


def entry_ability_dicts(entry):
    """(scope_label, ability_dict) for every ability of an entry across
    all present parts (unit, leader, support), so inspect toggles reach
    the support's abilities too. Prefixes leader/support scopes."""
    for part in ("unit", "leader", "support"):
        d = entry["unit"] if part == "unit" else entry.get(part)
        if d is None:
            continue
        pref = "" if part == "unit" else f"{part}: "
        for scope, ab in iter_ability_dicts(d):
            yield (pref + scope, ab)


def attach_support_to_entry(entry, support_dict):
    """Return a copy of 'entry' with support_dict filling its support slot
    (compatibility already checked by the caller)."""
    new = dict(entry)
    new["support"] = support_dict
    return new


def native_leaders_others(unit_dicts, fmt="w40k-sim/6"):
    """Split native unit dicts into (leaders, others) using the object
    model as the single source of truth for leader detection."""
    leaders, others = [], []
    for ud in unit_dicts:
        u = units_from_native({"format": fmt, "armies": [
            {"name": "x", "units": [ud]}]})[0]
        (leaders if is_leader_unit(u) else others).append(ud)
    return leaders, others


def native_supports_others(unit_dicts, fmt="w40k-sim/6"):
    """Split native unit dicts into (supports, others): supports are the
    units whose object model carries a non-empty support list. Mirrors
    native_leaders_others for the separate support slot."""
    supports, others = [], []
    for ud in unit_dicts:
        u = units_from_native({"format": fmt, "armies": [
            {"name": "x", "units": [ud]}]})[0]
        (supports if is_support_unit(u) else others).append(ud)
    return supports, others


def native_can_attach(leader_dict, unit_dict, fmt="w40k-sim/6"):
    """True if 'leader_dict' can lead 'unit_dict', working at the native
    (dict) level by building the two Unit objects and calling can_attach."""
    us = units_from_native({"format": fmt, "armies": [
        {"name": "x", "units": [unit_dict, leader_dict]}]})
    return us[0].can_attach(us[1])


def native_can_support(support_dict, unit_dict, fmt="w40k-sim/6"):
    """True if 'support_dict' can support 'unit_dict', at the native (dict)
    level (mirrors native_can_attach for the support slot)."""
    us = units_from_native({"format": fmt, "armies": [
        {"name": "x", "units": [unit_dict, support_dict]}]})
    return us[0].can_support(us[1])


# ---------------- inspect text (both GUIs) ----------------


def unit_inspect_text(unit) -> str:
    """Readable full profile of a Unit object."""
    lines = [f"{unit.name}  ({unit.points} pts)",
             "Keywords: " + (", ".join(unit.keywords) or "-")]
    if getattr(unit, "leadership", None):
        lines.append("Can lead: " + ", ".join(unit.leadership))
    if getattr(unit, "support", None):
        lines.append("Can support: " + ", ".join(unit.support))
    lines.append("")
    def _v(c):
        return c.value() if hasattr(c, "value") else c
    for m in unit.models():
        inv = f"  invuln {m.invuln}+" if m.invuln else ""
        fnp = f"  FNP {m.fnp}+" if m.fnp else ""
        lines.append(f"{m.name}  x{m.model_count}")
        mkw = m.effective_keywords()
        if mkw and mkw != set(unit.keywords):
            lines.append("  Model keywords: " + ", ".join(sorted(mkw)))
        lines.append(f"  M {_v(m.M)}  T {_v(m.T)}  Sv {_v(m.Sv)}+  "
                     f"W {_v(m.W)}  LD {_v(m.LD)}  OC {_v(m.OC)}{inv}{fnp}")
        for w in m.weapons:
            skill = w.WS if w.type == "Melee" else w.BS
            kw = ("  [" + ", ".join(w.keywords) + "]") if w.keywords else ""
            lines.append(f"    [{w.type[0]}] {w.name} x{w.count}: "
                         f"A {_v(w.A)}  {'WS' if w.type == 'Melee' else 'BS'} "
                         f"{_v(skill)}+  S {_v(w.S)}  AP {_v(w.AP)}  "
                         f"D {_v(w.D)}{kw}")
        lines.append("")
    abil = [ab for ab in unit.abilities
            if ab.get("name") or ab.get("description")]
    if abil:
        lines.append("Abilities:")
        for ab in abil:
            nm, d = ab.get("name", ""), ab.get("description", "")
            lines.append(f"  - {nm}: {d}" if nm and d else f"  - {nm or d}")
    for label, val in (("Unit composition",
                        getattr(unit, "unit_composition", "")),
                       ("Wargear options",
                        getattr(unit, "wargear_options", "")),
                       ("Notes", getattr(unit, "notes", ""))):
        if val:
            lines += ["", f"{label}:", f"  {val}"]
    return "\n".join(lines)


# ---------------- ability enumeration (inspect toggles) ----------------


def iter_ability_dicts(unit_dict):
    """(scope_label, ability_dict) for every ability of a NATIVE unit
    dict, in display order: unit, leader_effects, per model, per
    weapon. Used by the inspect dialog so its checkboxes toggle the
    'enabled' flag on the caller's own dicts."""
    for ab in unit_dict.get("abilities", []):
        yield ("unit", ab)
    for ab in unit_dict.get("core_abilities", []):
        yield ("core", ab)
    for ab in unit_dict.get("faction_abilities", []):
        yield ("faction", ab)
    for ab in unit_dict.get("leader_effects", []):
        yield ("leader effect", ab)
    for m in unit_dict.get("models", []):
        mname = m.get("name", "model")
        for ab in m.get("abilities", []):
            yield (f"model: {mname}", ab)
        for w in m.get("weapons", []):
            for ab in w.get("abilities", []):
                yield (f"weapon: {w.get('name', 'weapon')}", ab)


def ability_dicts_of_unit(unit):
    """(scope_label, ability_dict) pairs from a Unit OBJECT. The dicts
    are the same objects the engine reads, so toggling 'enabled' on
    them affects the next analysis; for a joined unit this spans both
    the unit's and the leader's abilities."""
    pairs = [("unit", ab) for ab in unit.abilities]
    for m in unit.models():
        for ab in m.abilities:
            pairs.append((f"model: {m.name}", ab))
        for w in m.weapons:
            for ab in w.abilities:
                pairs.append((f"weapon: {w.name}", ab))
    return pairs
