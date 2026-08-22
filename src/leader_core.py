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
from unit_model import units_from_native, combined_name


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
        """Build ONE joined entry from a target plus optional leaders
        and/or supports (each argument may be a single dict or a list),
        removing every chosen part from its pool. Powers the single Join
        button (leader+unit, support+unit, or leader+support+unit)."""
        leaders = _as_list(leader_dict)
        supports = _as_list(support_dict)
        self._remove(target_dict)
        for d in leaders + supports:
            self._remove(d)
        entry = make_entry(target_dict)
        entry = set_helpers(entry, "leader", leaders)
        self.joined.append(set_helpers(entry, "support", supports))

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
        """Attach one more helper (slot 'leader'|'support') to an existing
        joined entry, consuming it from its pool. Enables leader+support
        units built in two steps, and units with more than one slot."""
        self._remove(helper_dict)
        e = self.joined[entry_index]
        self.joined[entry_index] = set_helpers(
            e, slot, helpers(e, slot) + [helper_dict])

    def free_slots(self, entry_index, slot) -> int:
        """How many more helpers the joined entry can take in 'slot'."""
        return free_slots(self.joined[entry_index], slot, self.fmt)

    def unjoin(self, entry_index):
        """Split a joined entry back into its parts, returned to pools."""
        e = self.joined.pop(entry_index)
        self._restore(e["unit"])
        for slot in ("leader", "support"):
            for h in helpers(e, slot):
                self._restore(h)

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


def helpers(entry, slot) -> list:
    """The helpers filling 'slot' ('leader'|'support') of an entry, as a
    list. A slot holds None, a single dict, or a list of dicts - the
    compact forms are kept so that files and code written when a slot
    could hold only one helper still read correctly."""
    v = entry.get(slot)
    if v is None:
        return []
    return list(v) if isinstance(v, list) else [v]


def set_helpers(entry, slot, items) -> dict:
    """Copy of 'entry' with 'slot' filled by 'items' (a list), stored in
    the most compact form: None / a single dict / a list."""
    items = [x for x in items if x is not None]
    new = dict(entry)
    new[slot] = None if not items else (items[0] if len(items) == 1
                                        else items)
    return new


def free_slots(entry, slot, fmt="w40k-sim/6") -> int:
    """How many more helpers the entry can take in 'slot': the base
    unit's capacity (its leader_slots/support_slots field plus any
    enabled attachmentSlots ability) minus what is already attached."""
    unit = units_from_native({"format": fmt, "armies": [
        {"name": "x", "units": [entry["unit"]]}]})[0]
    return max(0, unit.slot_capacity(slot) - len(helpers(entry, slot)))


def make_entry(unit_dict, leader_dict=None, support_dict=None) -> dict:
    """A roster entry: the base unit plus an optional attached leader and
    an optional attached support (independent slots; a unit may carry one
    of each). Model order for global indexing is unit, then leader, then
    support."""
    return {"unit": unit_dict, "leader": leader_dict,
            "support": support_dict}


def entry_label(entry) -> str:
    """Human-readable label for a roster entry: the base unit's name plus
    its attached helpers. One helper of a kind is named, several are
    summarised ('+ 2 leaders'), so a unit with two Leaders and a Support
    still fits a list column - same rule as the combined Unit's name."""
    lds = [h["name"] for h in helpers(entry, "leader")]
    sps = [h["name"] for h in helpers(entry, "support")]
    name = combined_name(entry["unit"]["name"], lds, sps)
    return f"{name} [JOINED]" if (lds or sps) else name


def entry_points(entry) -> int:
    """Total points of a roster entry: the base unit plus any attached
    leader and support."""
    pts = entry["unit"].get("points") or 0
    for slot in ("leader", "support"):
        for h in helpers(entry, slot):
            pts += h.get("points") or 0
    return pts


def _entry_parts(entry):
    """The present parts of an entry in global-index order:
    [('unit', dict), ('leader:0', dict)?, ..., ('support:0', dict)?, ...].
    A slot may hold several helpers, so each part gets a unique key."""
    parts = [("unit", entry["unit"])]
    for slot in ("leader", "support"):
        for i, h in enumerate(helpers(entry, slot)):
            parts.append((f"{slot}:{i}", h))
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


def attached_model_indices(entry) -> set:
    """Global model indices belonging to an attached CHARACTER.

    Every model of a leader or a support part: the rules forbid
    allocating an attack to them while the unit still has a Bodyguard
    model standing, so the assisted allocation has to be able to tell
    them apart from the unit's own models (see :mod:`allocation`).
    """
    out = set()
    for slot, _d, start, n in _segment_offsets(entry):
        if slot != "unit":
            out.update(range(start, start + n))
    return out


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

    def rebuild(part_key, ud):
        if ud is None:
            return None
        f = attack_resolve.filter_native_unit(
            ud, mc.get(part_key, {}), mw.get(part_key, {}),
            wc.get(part_key, {}))
        if not f["models"]:
            return None
        return units_from_native({"format": fmt, "armies": [
            {"name": "table", "units": [f]}]})[0]

    unit = rebuild("unit", entry["unit"])
    leaders = [u for u in (rebuild(k, d) for k, d in _entry_parts(entry)
                           if k.startswith("leader:")) if u is not None]
    supports = [u for u in (rebuild(k, d) for k, d in _entry_parts(entry)
                            if k.startswith("support:")) if u is not None]
    # If the base unit is gone, a surviving helper fights alone (prefer a
    # leader, else a support).
    if unit is None:
        return (leaders + supports or [None])[0]
    for helper in leaders:
        if unit.can_attach(helper):
            unit = unit.attach_leader(helper)
    for helper in supports:
        if unit.can_support(helper):
            unit = unit.attach_support(helper)
    return unit


def entry_ability_dicts(entry):
    """(scope_label, ability_dict) for every ability of an entry across
    all present parts (unit, leader, support), so inspect toggles reach
    the support's abilities too. Prefixes leader/support scopes."""
    for part, d in _entry_parts(entry):
        pref = "" if part == "unit" else f"{part}: "
        for scope, ab in iter_ability_dicts(d):
            yield (pref + scope, ab)


POSITIONAL_KEY = "#"          # prefix of the fallback key, see below


def entry_ability_keys(entry):
    """[(key, scope_label, ability_dict)] for the entry, in
    entry_ability_dicts order.

    'key' identifies the ability inside the entry and is what the game
    assistant stores in its table row id. It is the ability's own 'id'
    whenever that id exists and is unique within the entry, so the row
    keeps pointing at the SAME ability even if the entry's parts change
    (a leader joined or removed shifts every later position).

    Rosters that never went through ability_ids.normalize may carry
    abilities without an id, or two parts may repeat one; those fall
    back to the position, '#<index>'. A uuid hex never contains '#', so
    the two key spaces cannot collide."""
    pairs = list(entry_ability_dicts(entry))
    ids = [str(ab.get("id") or "").strip() for _s, ab in pairs]
    dup = {i for i in ids if i and ids.count(i) > 1}
    return [(aid if aid and aid not in dup else f"{POSITIONAL_KEY}{idx}",
             scope, ab)
            for idx, ((scope, ab), aid) in enumerate(zip(pairs, ids))]


def entry_ability_by_key(entry, key):
    """The (scope_label, ability_dict) with that key, or (None, None)
    when the entry has no such ability (a stale row id)."""
    for k, scope, ab in entry_ability_keys(entry):
        if k == str(key):
            return (scope, ab)
    return (None, None)


def set_entry_ability_enabled(entry, key, enabled) -> bool:
    """Switch the ability with that key on or off, writing the flag on
    the entry's own native dict (so a unit rebuilt from the roster sees
    it). Returns False when the key does not resolve."""
    _scope, ab = entry_ability_by_key(entry, key)
    if ab is None:
        return False
    ab["enabled"] = bool(enabled)
    return True


def entry_ability_label(scope, ab) -> str:
    """Row text of one ability: '[scope] Name'. The NAME identifies it -
    core and faction abilities are usually stored with an empty
    description, so a description-only label would show blank rows."""
    name = (ab.get("name") or "").strip() or "<unnamed ability>"
    return f"[{scope}] {name}"


def attach_support_to_entry(entry, support_dict):
    """Return a copy of 'entry' with support_dict added to its support
    slot (compatibility and capacity already checked by the caller)."""
    return set_helpers(entry, "support",
                       helpers(entry, "support") + [support_dict])


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


def attach_all(combined, picks):
    """Attach every pick that fits to a Unit, in order.

    'picks' is [(slot, Unit)] with slot 'leader'|'support'. Returns
    (combined, taken, refused): 'taken' the [(slot, Unit)] actually
    attached, 'refused' the [(Unit, reason)] that did not fit, with a
    reason to show the user instead of silently doing nothing.
    """
    taken, refused = [], []
    for slot, helper in picks:
        attached = (combined.attached_leaders if slot == "leader"
                    else combined.attached_supports)
        fits = (combined.can_attach(helper) if slot == "leader"
                else combined.can_support(helper))
        if fits:
            combined = (combined.attach_leader(helper) if slot == "leader"
                        else combined.attach_support(helper))
            taken.append((slot, helper))
        elif any(u.name == helper.name for u in attached):
            refused.append((helper, f"already attached as {slot}"))
        elif len(attached) >= combined.slot_capacity(slot):
            refused.append((helper, f"no free {slot} slot on "
                                    f"{combined.base_name}"))
        else:
            refused.append((helper, f"cannot {slot} {combined.base_name}"))
    return combined, taken, refused


def _as_list(x):
    """None / one dict / a list of dicts -> a list."""
    if x is None:
        return []
    return list(x) if isinstance(x, list) else [x]


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
        """Datasheet notation, NOT a roll: value() would print a random
        result for a dice characteristic (A D3, D D6...) and a different
        one at every refresh."""
        return c.notation() if hasattr(c, "notation") else c
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
    # Leader/support effects are kept apart from the unit's own abilities
    # but obey the same 'enabled' flag, so they belong in the same list.
    pairs += [("leader effect", ab) for ab in unit.leader_effects]
    for m in unit.models():
        for ab in m.abilities:
            pairs.append((f"model: {m.name}", ab))
        for w in m.weapons:
            for ab in w.abilities:
                pairs.append((f"weapon: {w.name}", ab))
    return pairs
