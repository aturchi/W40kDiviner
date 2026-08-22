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
* **'turn' is a plain counter** advanced by the user. The program has
  no concept of a game turn yet (that is a separate, deferred point);
  the field only groups the entries, and nothing else reads it.
"""

import time

import mod_presets

FORMAT = "w40k-log/1"

# Flag keys of the setup panel that are not context ticks and must not
# be printed as such (they are handled one by one, or ignored).
_NOT_A_TICK = ("overwatch_value", "disabled_abilities", "extra_abilities")

# Wording for the flags whose key alone would read badly in a log.
_SPECIAL = {"optimise_abilities": "player choices optimised"}


# ---------------- building an entry ----------------


def _amounts(res: dict, kind: str) -> list:
    return [int(e.get("amount", 0)) for e in (res.get("events") or ())
            if e.get("kind") == kind]


def weapon_record(weapon, hazardous, res: dict) -> dict:
    """One weapon's line of an entry: what it rolled, per event.

    The individual amounts are kept rather than their sum, because that
    is what allocation works on - three events of 2 damage are not one
    event of 6, and a post-mortem that lost the distinction would be
    worthless."""
    return {"name": str(weapon.name),
            "count": int(getattr(weapon, "count", 1) or 1),
            "hazardous": bool(hazardous),
            "attacks": int(res.get("attacks", 0) or 0),
            "damage": _amounts(res, "damage"),
            "mortal": _amounts(res, "mortal"),
            "self_damage": int(res.get("self_damage", 0) or 0),
            "warnings": sorted(res.get("warnings") or ())}


def skipped_record(weapon, reason) -> dict:
    """A weapon the attack setup did not fire, and why."""
    return {"name": str(weapon.name),
            "count": int(getattr(weapon, "count", 1) or 1),
            "reason": str(reason)}


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


def entry_totals(entry: dict) -> dict:
    """Derived, never stored: attacks rolled, damaging events, damage to
    allocate (mortal wounds included, as the results popup counts them),
    of which mortal, and the attacker's own hazardous self-damage."""
    weapons = entry.get("weapons") or []
    normal = sum(sum(w.get("damage") or ()) for w in weapons)
    mortal = sum(sum(w.get("mortal") or ()) for w in weapons)
    events = sum(len(w.get("damage") or ()) + len(w.get("mortal") or ())
                 for w in weapons)
    return {"attacks": sum(int(w.get("attacks", 0) or 0) for w in weapons),
            "events": events,
            "damage": normal + mortal,
            "normal": normal,
            "mortal": mortal,
            "self_damage": sum(int(w.get("self_damage", 0) or 0)
                               for w in weapons)}


def damage_by_defender(entries) -> list:
    """[(unit name, {'damage', 'mortal', 'attacks'}), ...] in the order
    the units were first attacked. This is the running total the
    opponent asks for mid-game."""
    out = {}
    for e in entries or ():
        t = entry_totals(e)
        rec = out.setdefault(e.get("defender", "?"),
                             {"damage": 0, "mortal": 0, "attacks": 0})
        rec["damage"] += t["damage"]
        rec["mortal"] += t["mortal"]
        rec["attacks"] += 1
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
    dmg, mw = w.get("damage") or [], w.get("mortal") or []
    if dmg:
        parts.append("damage " + ", ".join(str(v) for v in dmg))
    if mw:
        parts.append("MORTAL " + ", ".join(str(v) for v in mw))
    if not dmg and not mw:
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
    tail = f" ({t['mortal']} mortal)" if t["mortal"] else ""
    lines.append(f"    TOTAL {t['events']} damaging attacks, "
                 f"{t['damage']} damage to allocate{tail}")
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
    lines = ["Damage rolled so far, by defending unit",
             "(to allocate: overkill on a destroyed model is NOT "
             "subtracted)"]
    for name, rec in rows:
        tail = f", {rec['mortal']} mortal" if rec["mortal"] else ""
        lines.append(f"  {name.ljust(width)}  {rec['damage']:>5} damage"
                     f"{tail}  ({rec['attacks']} attacks)")
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


CSV_COLUMNS = ("#", "turn", "time", "attacker", "defender", "mode",
               "weapon", "count", "attacks", "events", "damage",
               "mortal", "self-damage", "note")


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
        for w in e.get("weapons") or ():
            dmg, mw = w.get("damage") or [], w.get("mortal") or []
            lines.append(",".join(_cell(v) for v in head + [
                w.get("name"), w.get("count"), w.get("attacks"),
                len(dmg) + len(mw), sum(dmg) + sum(mw), sum(mw),
                w.get("self_damage"),
                "HAZARDOUS" if w.get("hazardous") else ""]))
        for s in e.get("skipped") or ():
            lines.append(",".join(_cell(v) for v in head + [
                s.get("name"), s.get("count"), 0, 0, 0, 0, 0,
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
