"""The reasoning behind a weapon's numbers, in words.

The analyzer already says what it could NOT model ("Not modelled: ...").
The opposite is more useful and was missing: what it DID. A line like

    Hit    BS 4+ (3+ base, -1 cover)  ->  50.0%   critical on 6+

is what convinces a reader that the program understood the datasheet -
and it is how the flag left ticked from three analyses ago gets caught.

The numbers come from attack_math's audit trail, which records what the
chain actually used; nothing here recomputes them, so the explanation
cannot drift away from the calculation. Only the wording lives here.
"""

import rules_config

SECTIONS = ("attacks", "hit", "wound", "save", "fnp", "damage",
            "mechanics")


def _pct(p):
    return f"{p * 100:.1f}%"


def _signed(n):
    return f"{n:+d}" if n else ""


def _attacks(a: dict) -> str:
    at = a["attacks"]
    fixed = (at["expr"].isdigit() and not at["mod"]
             and not at["rapid_fire"] and not at["blast"])
    if fixed:
        # A flat characteristic with nothing acting on it: printing
        # "3 -> 3.00 attacks" would be noise.
        return (f"{at['mean']:.0f} attacks"
                + (f" ({a['count']} copies included)"
                   if a["count"] != 1 else ""))
    bits = [f"{at['expr']}"]
    extra = []
    if a["attacks"]["mod"]:
        extra.append(f"{_signed(a['attacks']['mod'])} attacks")
    if a["attacks"]["rapid_fire"]:
        extra.append(f"RAPID FIRE +{a['attacks']['rapid_fire']}")
    if a["attacks"]["blast"]:
        extra.append(f"blast +{a['attacks']['blast']}")
    if extra:
        bits.append("(" + ", ".join(extra) + ")")
    bits.append(f"-> {a['attacks']['mean']:.2f} attacks")
    if a["count"] != 1:
        bits.append(f"({a['count']} copies included)")
    return " ".join(bits)


def _hit(a: dict) -> str:
    h = a["hit"]
    if h["auto"]:
        return "automatic (no hit roll, so no critical hits)"
    if h["overwatch"]:
        return (f"OVERWATCH: unmodified {h['overwatch']}+ only, every "
                f"modifier and re-roll discarded -> {_pct(h['p'])}")
    why = []
    if h["skill"] is not None and h["skill"] != h["target"]:
        why.append(f"{h['skill']}+ base")
    if h["cover"]:
        why.append("-1 cover")
    txt = f"{'WS' if a['type'] == 'Melee' else 'BS'} {h['target']}+"
    if why:
        txt += " (" + ", ".join(why) + ")"
    if h["mod"]:
        txt += f", roll {_signed(h['mod'])}"
    if h.get("unmod_min", 1) > 1:
        # INDIRECT FIRE: an unmodified roll below the floor always
        # misses, however good the target number looks.
        txt += (f", unmodified {h['unmod_min']}+ floor "
                "(indirect fire: no re-rolls)")
    if h["reroll"]:
        txt += f", re-roll {h['reroll']}"
    txt += f"  ->  {_pct(h['p'])}"
    if h["p_crit"]:
        txt += f"   critical on {h['crit_on']}+ ({_pct(h['p_crit'])})"
    if h["p_mw"]:
        txt += f"   mortal-wound branch {_pct(h['p_mw'])}"
    return txt


def _wound(a: dict) -> str:
    w = a["wound"]
    if w["auto"]:
        return "automatic (every hit wounds, no roll)"
    txt = f"S{w['S']} vs T{w['T']}  ->  {w['target']}+"
    if w["mod"]:
        txt += f", roll {_signed(w['mod'])}"
    if w["reroll"]:
        txt += f", re-roll {w['reroll']}"
    txt += f"  ->  {_pct(w['p'])}"
    if w["p_crit"]:
        extra = " (ANTI)" if w["crit_on"] != 6 else ""
        txt += (f"   critical on {w['crit_on']}+{extra} "
                f"({_pct(w['p_crit'])})")
    return txt


def _save(a: dict) -> str:
    s = a["save"]
    parts = []
    if s["Sv"] is not None:
        armour = rules_config.clamp_characteristic("Sv", s["Sv"]) \
            + abs(s["ap"])
        parts.append(f"armour {armour}+ (Sv {s['Sv']}+ vs AP{s['ap']})"
                     if s["ap"] else f"armour {armour}+")
    if s["invuln"] is not None:
        parts.append(f"invulnerable {s['invuln']}+")
    if s["mod"]:
        parts.append(f"save roll {_signed(s['mod'])}")
    if s["invuln_mod"]:
        parts.append(f"invuln roll {_signed(s['invuln_mod'])}")
    if s["reroll"]:
        parts.append(f"re-roll {s['reroll']}")
    if not parts:
        parts.append("no save")
    both = s["Sv"] is not None and s["invuln"] is not None
    txt = ", ".join(parts) + ("  ->  best of the two, fails "
                              if both else "  ->  fails ")
    txt += _pct(s["p_unsaved"])
    if abs(s["p_unsaved_crit"] - s["p_unsaved"]) > 1e-12:
        txt += (f"   (critical wounds: AP{s['ap_crit']}, fails "
                f"{_pct(s['p_unsaved_crit'])})")
    return txt


def _fnp(a: dict) -> str:
    f = a["fnp"]
    if not f["value"] and not f["mw_only"] and not f["invuln_mw"]:
        return "none"
    bits = []
    if f["value"]:
        eff = f["value"] - f["mod"]
        bits.append(f"{f['value']}+"
                    + (f" ({_signed(-f['mod'])} to the roll -> {eff}+)"
                       if f["mod"] else ""))
    if f["mw_only"]:
        bits.append(f"{f['mw_only']}+ against mortal wounds only")
    if f["invuln_mw"]:
        bits.append(f"invulnerable {f['invuln_mw']}+ against mortal "
                    "wounds")
    return ", ".join(bits)


def _damage(a: dict) -> str:
    d = a["damage"]
    txt = f"{d['expr']}  ->  {d['mean']:.2f} per attack"
    if d["melta"]:
        txt += f"   MELTA +{d['melta']} (within half range)"
    return txt


def lines(audit: dict) -> list:
    """[(section, text)] for one weapon."""
    out = [("Attacks", _attacks(audit)), ("Hit", _hit(audit)),
           ("Wound", _wound(audit)), ("Save", _save(audit)),
           ("Feel No Pain", _fnp(audit)), ("Damage", _damage(audit))]
    mech = audit.get("mechanics") or []
    out.append(("Abilities in play",
                ", ".join(mech) if mech else "none"))
    if audit.get("warnings"):
        out.append(("Not modelled", "; ".join(audit["warnings"])))
    return out


def text(audit: dict, width: int = 18) -> str:
    """The same, as a block of text."""
    return "\n".join(f"{label:<{width}}{value}"
                     for label, value in lines(audit))


def report(results: dict) -> str:
    """Every weapon of one analysis, in table order."""
    blocks = []
    for r in results.get("weapons", []):
        a = r.get("audit")
        if not a:
            continue
        head = r["name"] + (f"  x{a['count']}" if a["count"] != 1 else "")
        blocks.append(head + "\n" + text(a))
    for r in results.get("skipped", []):
        blocks.append(f"{r['name']}  x{r['count']}\n"
                      f"{'Excluded':<18}{r['reason']}")
    return "\n\n".join(blocks)
