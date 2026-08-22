"""History of the attacks resolved during a game (program 1).

Every attack the game assistant resolves is appended here: who fired at
whom, under which context, with which weapons, and what each attack
ACTUALLY rolled. It answers two questions nothing else in the program
could: "how many wounds had I already taken off that unit?" in the
middle of a game, and "where did the turn go wrong?" afterwards.

No tkinter: an entry is a dict of plain JSON types, so the log goes
straight into the session file and every bit of formatting here is
testable headless.

Two deliberate choices:

* **Nothing derived is stored.** Totals are recomputed from the events
  (:func:`entry_totals`), so the log can never disagree with itself -
  and a hand-edited session file cannot produce a summary line that
  contradicts the attacks below it.
* **Mortal wounds are recorded in two lists, not one.** DEVASTATING
  WOUNDS are mortal wounds for every rule that keys on them, but they
  do NOT spill from a destroyed model to the next, and that difference
  decides how many models an attack removes. ``attack_resolve`` puts
  the distinction on each event (``spills``) and the log keeps it:
  ``mortal`` holds the wounds that spill, ``devastating`` the ones that
  do not. Collapsing the two would make the log useless for the one
  thing it is next meant to do - record what was actually ALLOCATED.
* **Rolled and REMOVED are two different numbers, and both are kept.**
  What an attack rolls is what there is to allocate; what it takes off
  the table is smaller, because the excess on a model that dies is
  wasted and how much was wasted depends on the allocation the player
  made. The entry therefore carries an optional ``allocation``, written
  when (and only when) the assisted allocation was applied: the models
  it touched, with their wounds before and after. Everything else -
  wounds removed, models destroyed, damage that went nowhere - is
  derived from those two numbers, so the log still cannot contradict
  itself. An entry without an ``allocation`` is an attack that was
  written off by hand, and the summary says so rather than guessing.
* **'turn' is a plain counter** advanced by the user. The program has
  no concept of a game turn yet (that is a separate, deferred point);
  the field only groups the entries, and nothing else reads it.
"""

import time

import mod_presets

FORMAT = "w40k-log/2"
# v1 entries carry a single 'mortal' list with no 'devastating' beside
# it: their devastating wounds are indistinguishable from real mortal
# wounds and are read as spilling, which is the default attack_resolve
# itself uses. Nothing is migrated - the readers below simply treat a
# missing 'devastating' as empty.

# Flag keys of the setup panel that are not context ticks and must not
# be printed as such (they are handled one by one, or ignored).
_NOT_A_TICK = ("overwatch_value", "disabled_abilities", "extra_abilities",
               "battle_round")

# Wording for the flags whose key alone would read badly in a log.
_SPECIAL = {"optimise_abilities": "player choices optimised"}


# ---------------- building an entry ----------------


def _amounts(res: dict, kind: str, spills=None) -> list:
    """The amounts of the events of one kind, in the order they were
    rolled. With 'spills' given, only the mortal wounds that do (True)
    or do not (False) spill over to the next model."""
    out = []
    for e in res.get("events") or ():
        if e.get("kind") != kind:
            continue
        if spills is not None and bool(e.get("spills", True)) != spills:
            continue
        out.append(int(e.get("amount", 0)))
    return out


def weapon_record(weapon, hazardous, res: dict) -> dict:
    """One weapon's line of an entry: what it rolled, per event.

    The individual amounts are kept rather than their sum, because that
    is what allocation works on - three events of 2 damage are not one
    event of 6, and a post-mortem that lost the distinction would be
    worthless. For the same reason the mortal wounds are split by
    whether they spill: 'mortal' are the ones that do, 'devastating'
    the ones that do not."""
    return {"name": str(weapon.name),
            "count": int(getattr(weapon, "count", 1) or 1),
            "hazardous": bool(hazardous),
            "attacks": int(res.get("attacks", 0) or 0),
            "damage": _amounts(res, "damage"),
            "mortal": _amounts(res, "mortal", spills=True),
            "devastating": _amounts(res, "mortal", spills=False),
            "self_damage": int(res.get("self_damage", 0) or 0),
            "warnings": sorted(res.get("warnings") or ())}


def skipped_record(weapon, reason) -> dict:
    """A weapon the attack setup did not fire, and why."""
    return {"name": str(weapon.name),
            "count": int(getattr(weapon, "count", 1) or 1),
            "reason": str(reason)}


def allocation_record(rows, stamp=None) -> dict:
    """What the player actually took off the table, as applied.

    'rows' are the rows the allocation dialog hands back: only the
    models whose wounds changed. Nothing derived is stored - not the
    number removed, not the models destroyed - because both follow from
    'before' and 'after' and a stored copy could drift away from them.
    """
    return {"time": time.strftime("%H:%M:%S") if stamp is None
            else str(stamp),
            "models": [{"label": str(r.get("label", "?")),
                        "before": int(r.get("before", 0) or 0),
                        "after": int(r.get("after", 0) or 0)}
                       for r in rows or ()]}


def allocation_totals(entry: dict):
    """{'removed', 'killed', 'models'} for an entry whose allocation was
    applied, or None when it was not: the caller has to be able to tell
    "nothing was removed" from "we do not know"."""
    alloc = (entry or {}).get("allocation")
    if not isinstance(alloc, dict):
        return None
    rows = alloc.get("models") or []
    removed = killed = 0
    for r in rows:
        before = int(r.get("before", 0) or 0)
        after = int(r.get("after", 0) or 0)
        removed += max(0, before - after)
        if before > 0 >= after:
            killed += 1
    return {"removed": removed, "killed": killed, "models": len(rows)}


def ref_record(ref: dict) -> dict:
    """The defending profile the attack was resolved against. Recorded
    because the same unit can be attacked against different reference
    models, and the numbers below only make sense next to it."""
    ref = ref or {}
    return {k: ref.get(k) for k in ("T", "Sv", "W", "invuln", "fnp")}


def context_lines(flags: dict, mods=(), labels=None) -> list:
    """The context in words: the ticked flags and the manual modifiers.

    ``labels`` maps a flag key to the wording of its checkbox (pass
    ``dict(setup_panel.FLAGS)``); keys without one are spelled out from
    the key itself, so a new flag appears in the log the day it is added
    to the panel rather than the day someone remembers to list it here.
    """
    labels = dict(labels or {})
    out = []
    for key, value in (flags or {}).items():
        if key in _NOT_A_TICK or not value:
            continue
        if key == "overwatch":
            v = (flags or {}).get("overwatch_value")
            out.append(f"Overwatch (hits on {v}+)" if v else "Overwatch")
            continue
        out.append(_SPECIAL.get(key,
                                labels.get(key, key.replace("_", " "))))
    rnd = (flags or {}).get("battle_round")
    if rnd:
        # Not a tick: it is always set, so it is reported always. A
        # post-mortem two turns later needs to know which round it was.
        out.append(f"battle round {rnd}")
    for key, word in (("disabled_abilities", "switched off"),
                      ("extra_abilities", "added by hand")):
        n = len((flags or {}).get(key) or ())
        if n:
            out.append(f"{n} abilit{'y' if n == 1 else 'ies'} {word}")
    out += [mod_presets.describe(m) for m in mods or ()]
    return out


def make_entry(attacker, defender, ref: dict, results, skipped=(),
               mode="ranged", melee=None, context=(), stamp=None) -> dict:
    """One resolved attack. ``results`` is the game assistant's own
    ``[(weapon, hazardous, resolve_result), ...]`` and ``skipped`` its
    ``[(weapon, reason), ...]``, so the caller has nothing to convert.

    ``seq`` and ``turn`` are filled in by :meth:`AttackLog.add`; passing
    a fixed ``stamp`` keeps the entry reproducible for the tests."""
    return {"time": time.strftime("%H:%M:%S") if stamp is None
            else str(stamp),
            "attacker": str(attacker),
            "defender": str(defender),
            "mode": str(mode),
            "melee": str(melee) if melee else None,
            "ref": ref_record(ref),
            "context": [str(c) for c in context or ()],
            "weapons": [weapon_record(w, h, r) for w, h, r in results],
            "skipped": [skipped_record(w, why)
                        for w, why in (skipped or ())]}


# ---------------- reading an entry ----------------


_AMOUNT_KEYS = ("damage", "mortal", "devastating")


def entry_totals(entry: dict) -> dict:
    """Derived, never stored: attacks rolled, damaging events, damage to
    allocate (mortal wounds included, as the results popup counts them),
    how it splits, and the attacker's own hazardous self-damage.

    'mortal' is every mortal wound, which is what the word means in the
    rules: DEVASTATING WOUNDS are mortal wounds. 'spill' and
    'devastating' are the two halves it is made of, and they are kept
    apart because only the first passes to the next model."""
    weapons = entry.get("weapons") or []

    def total(key):
        return sum(sum(w.get(key) or ()) for w in weapons)

    normal, spill, dev = (total(k) for k in _AMOUNT_KEYS)
    events = sum(len(w.get(k) or ()) for w in weapons
                 for k in _AMOUNT_KEYS)
    return {"attacks": sum(int(w.get("attacks", 0) or 0) for w in weapons),
            "events": events,
            "damage": normal + spill + dev,
            "normal": normal,
            "mortal": spill + dev,
            "spill": spill,
            "devastating": dev,
            "self_damage": sum(int(w.get("self_damage", 0) or 0)
                               for w in weapons)}


def damage_by_defender(entries) -> list:
    """[(unit name, {...}), ...] in the order the units were first
    attacked: the running total the opponent asks for mid-game.

    'damage' and 'mortal' are what was ROLLED; 'removed' and 'killed'
    are what the applied allocations actually took off, and 'applied'
    says over how many of the 'attacks' that is known. Where applied <
    attacks the removed figure is a lower bound, and the summary says
    as much instead of presenting it as the answer."""
    out = {}
    for e in entries or ():
        t = entry_totals(e)
        rec = out.setdefault(e.get("defender", "?"),
                             {"damage": 0, "mortal": 0, "attacks": 0,
                              "removed": 0, "killed": 0, "applied": 0})
        rec["damage"] += t["damage"]
        rec["mortal"] += t["mortal"]
        rec["attacks"] += 1
        got = allocation_totals(e)
        if got:
            rec["removed"] += got["removed"]
            rec["killed"] += got["killed"]
            rec["applied"] += 1
    return list(out.items())


# ---------------- formatting ----------------


def _ref_text(ref: dict) -> str:
    ref = ref or {}
    bits = [f"T{ref.get('T')}", f"Sv{ref.get('Sv')}+", f"W{ref.get('W')}"]
    if ref.get("invuln"):
        bits.append(f"inv{ref['invuln']}+")
    if ref.get("fnp"):
        bits.append(f"fnp{ref['fnp']}+")
    return " ".join(bits)


def header_line(entry: dict) -> str:
    mode = entry.get("mode", "")
    if entry.get("melee"):
        mode = f"{mode}: {entry['melee']}"
    return (f"#{entry.get('seq', '?')}  [turn {entry.get('turn', '?')}"
            f"  {entry.get('time', '')}]  {entry.get('attacker', '?')}"
            f"  ->  {entry.get('defender', '?')}  ({mode})")


def weapon_text(w: dict) -> str:
    head = f"{w.get('name', '?')} x{w.get('count', 1)}" \
        + (" [HAZARDOUS]" if w.get("hazardous") else "")
    parts = [f"{w.get('attacks', 0)} attacks"]
    dmg = w.get("damage") or []
    mw = w.get("mortal") or []
    dev = w.get("devastating") or []
    if dmg:
        parts.append("damage " + ", ".join(str(v) for v in dmg))
    if mw:
        parts.append("MORTAL " + ", ".join(str(v) for v in mw))
    if dev:
        # Mortal wounds too, but they do not spill: the reader has to
        # be able to tell, because it changes what died.
        parts.append("DEVASTATING " + ", ".join(str(v) for v in dev))
    if not dmg and not mw and not dev:
        parts.append("no damage")
    if w.get("self_damage"):
        parts.append(f"self-damage {w['self_damage']}")
    return head + " - " + "; ".join(parts)


def entry_text(entry: dict) -> str:
    """One attack as a text block, self-contained enough to be pasted
    somewhere on its own."""
    lines = [header_line(entry),
             f"    reference model: {_ref_text(entry.get('ref'))}"]
    if entry.get("context"):
        lines.append("    context: " + "; ".join(entry["context"]))
    for w in entry.get("weapons") or ():
        lines.append("    " + weapon_text(w))
    for s in entry.get("skipped") or ():
        lines.append(f"    {s.get('name', '?')} x{s.get('count', 1)}"
                     f" - not fired: {s.get('reason', '')}")
    t = entry_totals(entry)
    bits = []
    if t["spill"]:
        bits.append(f"{t['spill']} mortal")
    if t["devastating"]:
        bits.append(f"{t['devastating']} devastating")
    tail = f" ({', '.join(bits)})" if bits else ""
    lines.append(f"    TOTAL {t['events']} damaging attacks, "
                 f"{t['damage']} damage to allocate{tail}")
    got = allocation_totals(entry)
    if got:
        gone = t["damage"] - got["removed"]
        tail = (f", {gone} went nowhere (overkill or spare)"
                if gone > 0 else "")
        lines.append(f"    APPLIED at "
                     f"{entry['allocation'].get('time', '?')}: "
                     f"{got['removed']} wounds removed, "
                     f"{got['killed']} models destroyed{tail}")
    if t["self_damage"]:
        lines.append(f"    Hazardous self-damage: {t['self_damage']}")
    warn = sorted({w for wp in entry.get("weapons") or ()
                   for w in wp.get("warnings") or ()})
    if warn:
        lines.append("    Not modelled: " + "; ".join(warn))
    return "\n".join(lines)


def summary_text(entries) -> str:
    """The running totals, by defending unit.

    This is damage ROLLED, not wounds removed: the excess damage of an
    attack that kills a model is wasted, and how much was wasted depends
    on the allocation the player made at the table, which the program
    does not know. The two numbers can only be equal by accident."""
    rows = damage_by_defender(entries)
    if not rows:
        return "No attack logged yet."
    width = max(len(name) for name, _rec in rows)
    lines = ["By defending unit",
             "(rolled = there was that much to allocate, overkill on a "
             "destroyed model included;",
             " removed = what the applied allocations actually took "
             "off the table)"]
    for name, rec in rows:
        tail = f", {rec['mortal']} mortal" if rec["mortal"] else ""
        if rec["applied"] == rec["attacks"]:
            got = (f"{rec['removed']:>4} removed, "
                   f"{rec['killed']} models destroyed")
        elif rec["applied"]:
            got = (f"{rec['removed']:>4} removed, "
                   f"{rec['killed']} models destroyed - but only "
                   f"{rec['applied']} of {rec['attacks']} attacks "
                   f"were applied here, so this is a lower bound")
        else:
            got = "   allocation never applied, removed unknown"
        lines.append(f"  {name.ljust(width)}  {rec['damage']:>5} rolled"
                     f"{tail}  ({rec['attacks']} attacks)")
        lines.append(f"  {' ' * width}  {got}")
    return "\n".join(lines)


def to_text(entries, summary=True) -> str:
    """The whole log as text, one block per attack, blank-line
    separated, with a turn heading whenever the turn changes."""
    entries = list(entries or ())
    if not entries:
        return "No attack logged yet.\n"
    blocks, turn = [], None
    for e in entries:
        if e.get("turn") != turn:
            turn = e.get("turn")
            blocks.append(f"===== TURN {turn} =====")
        blocks.append(entry_text(e))
    if summary:
        blocks.append(summary_text(entries))
    return "\n\n".join(blocks) + "\n"


# 'removed' and 'killed' belong to the ATTACK, not to any one weapon:
# they are written on the first row of each entry and left blank on the
# others, so summing the column in a spreadsheet gives the right total
# instead of counting the same allocation once per weapon.
CSV_COLUMNS = ("#", "turn", "time", "attacker", "defender", "mode",
               "weapon", "count", "attacks", "events", "damage",
               "mortal", "devastating", "self-damage", "removed",
               "killed", "note")


def _cell(v) -> str:
    v = "" if v is None else str(v)
    return '"' + v.replace('"', '""') + '"' \
        if ("," in v or '"' in v or "\n" in v) else v


def to_csv(entries) -> str:
    """One row per weapon per attack (skipped weapons included, with the
    reason in the note column), so the log can be pivoted in a
    spreadsheet."""
    lines = [",".join(CSV_COLUMNS)]
    for e in entries or ():
        mode = e.get("mode", "")
        if e.get("melee"):
            mode = f"{mode}: {e['melee']}"
        head = [e.get("seq"), e.get("turn"), e.get("time"),
                e.get("attacker"), e.get("defender"), mode]
        got = allocation_totals(e)
        # Entry-level cells: on the first row of the entry only, so a
        # SUM over the column is the total and not a multiple of it.
        pending = [[got["removed"], got["killed"]] if got else ["", ""]]

        def once():
            out, pending[0] = pending[0], ["", ""]
            return out

        for w in e.get("weapons") or ():
            dmg = w.get("damage") or []
            mw = w.get("mortal") or []
            dev = w.get("devastating") or []
            lines.append(",".join(_cell(v) for v in head + [
                w.get("name"), w.get("count"), w.get("attacks"),
                len(dmg) + len(mw) + len(dev),
                sum(dmg) + sum(mw) + sum(dev), sum(mw), sum(dev),
                w.get("self_damage")] + once() + [
                "HAZARDOUS" if w.get("hazardous") else ""]))
        for s in e.get("skipped") or ():
            lines.append(",".join(_cell(v) for v in head + [
                s.get("name"), s.get("count"), 0, 0, 0, 0, 0, 0]
                + once() + [
                "not fired: " + str(s.get("reason", ""))]))
    return "\n".join(lines) + "\n"


# ---------------- the log itself ----------------


class AttackLog:
    """Ordered attacks, plus the turn counter they are grouped by."""

    def __init__(self, data=None):
        self.entries = []
        self.turn = 1
        self.load(data)

    # ---------- persistence ----------

    def load(self, data):
        """Restore from :meth:`to_json`. A bare list of entries is also
        accepted, and anything unusable leaves an empty log rather than
        raising: a session must still open when its log is damaged."""
        if isinstance(data, list):
            data = {"entries": data}
        if not isinstance(data, dict):
            return
        entries = data.get("entries")
        self.entries = [e for e in (entries or ()) if isinstance(e, dict)]
        try:
            self.turn = max(1, int(data.get("turn", 1)))
        except (TypeError, ValueError):
            self.turn = 1
        # A hand-edited or truncated file may have lost the numbering.
        for i, e in enumerate(self.entries, start=1):
            e.setdefault("seq", i)
            e.setdefault("turn", 1)
        self.turn = max([self.turn] + [int(e.get("turn") or 1)
                                       for e in self.entries])

    def to_json(self) -> dict:
        return {"format": FORMAT, "turn": self.turn,
                "entries": list(self.entries)}

    # ---------- writing ----------

    def add(self, entry: dict) -> dict:
        """Append an entry, numbering it and stamping the current turn."""
        entry = dict(entry)
        entry["seq"] = self._next_seq()
        entry.setdefault("turn", self.turn)
        self.entries.append(entry)
        return entry

    def record(self, *args, **kwargs) -> dict:
        """make_entry + add, the way the caller wants it."""
        return self.add(make_entry(*args, **kwargs))

    def _next_seq(self) -> int:
        return max([int(e.get("seq") or 0) for e in self.entries] or [0]) + 1

    def set_allocation(self, seq, record) -> bool:
        """Attach an applied allocation to the entry numbered 'seq'.

        Returns False when there is no such entry - the results window
        outlives the log it was opened from, and an attack deleted in
        the meantime must not resurrect itself as a bare allocation.
        """
        for e in self.entries:
            if int(e.get("seq") or 0) == int(seq):
                e["allocation"] = record
                return True
        return False

    def new_turn(self) -> int:
        self.turn += 1
        return self.turn

    def remove(self, seqs) -> int:
        """Drop the entries with those sequence numbers (a mis-clicked
        attack). Returns how many went. The numbering is NOT compacted:
        a stable number is worth more here than a tidy one."""
        seqs = {int(s) for s in seqs}
        before = len(self.entries)
        self.entries = [e for e in self.entries
                        if int(e.get("seq") or 0) not in seqs]
        return before - len(self.entries)

    def undo_last(self):
        """Remove and return the last entry, or None."""
        return self.entries.pop() if self.entries else None

    def clear(self):
        """Empty the log. The turn counter is kept: clearing the history
        is not the same as starting the game again, and resetting it
        would silently renumber everything logged next."""
        self.entries = []

    # ---------- reading ----------

    def __len__(self):
        return len(self.entries)

    def to_text(self, summary=True) -> str:
        return to_text(self.entries, summary=summary)

    def to_csv(self) -> str:
        return to_csv(self.entries)
