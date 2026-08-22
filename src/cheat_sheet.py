"""One unit on one page: the printable cheat sheet.

What a player wants next to the dice is not the analysis, it is the
datasheet as the program understands it - the stat lines, the weapons
with their keywords, and the abilities that are actually switched on -
for the unit as it will be played, leader included. Printed once before
the game, it also settles the arguments the audit trail settles after
it: if the program is going to apply an ability, it is written here.

Two renderers over one intermediate structure (:func:`sections`), so
the text and the HTML can never drift apart, and the structure itself
is testable without a browser or a widget in sight.

The HTML is a single self-contained file with print styles: it opens in
any browser and Ctrl-P gives a clean page, which is cheaper than
depending on a PDF library.

A DISABLED ability is not silently dropped - it is listed as such. An
ability missing from a printed sheet is invisible; an ability printed
as "off" is a fact the opponent can check.
"""

import html as _html

import leader_core as lc

RANGED_COLUMNS = ("Weapon", "x", "RNG", "A", "BS", "S", "AP", "D",
                  "Keywords")
MELEE_COLUMNS = ("Weapon", "x", "A", "WS", "S", "AP", "D", "Keywords")


def _v(char):
    """Datasheet notation, never a roll: value() on a dice
    characteristic (A D3, D D6) would print a random result, and a
    different one on every print."""
    return "" if char is None else str(
        char.notation() if hasattr(char, "notation") else char)


def _plus(char):
    """A target number as the datasheet writes it ('3+'), leaving the
    empty and not-applicable cases alone rather than printing '-+'."""
    text = _v(char)
    return f"{text}+" if text and text != "-" else (text or "-")


def _weapon_row(weapon) -> tuple:
    skill = weapon.WS if weapon.type == "Melee" else weapon.BS
    cells = [weapon.name, f"x{weapon.count}"]
    if weapon.type != "Melee":
        cells.append(_v(weapon.RNG))
    cells += [_v(weapon.A), _plus(skill), _v(weapon.S), _v(weapon.AP),
              _v(weapon.D), ", ".join(weapon.keywords)]
    return tuple(cells)


def _model_section(model, unit) -> dict:
    stats = [("M", _v(model.M)), ("T", _v(model.T)),
             ("Sv", _plus(model.Sv)), ("W", _v(model.W)),
             ("LD", _plus(model.LD)), ("OC", _v(model.OC))]
    if model.invuln:
        stats.append(("Inv", f"{model.invuln}+"))
    if model.fnp:
        stats.append(("FNP", f"{model.fnp}+"))
    own = model.effective_keywords()
    return {"name": model.name, "count": model.model_count, "stats": stats,
            # Only what the model adds to the unit's own keywords: the
            # unit line already carries the rest.
            "keywords": sorted(own - set(unit.keywords)),
            "ranged": [_weapon_row(w) for w in model.weapons
                       if w.type != "Melee"],
            "melee": [_weapon_row(w) for w in model.weapons
                      if w.type == "Melee"]}


def sections(unit) -> dict:
    """The whole sheet as plain data."""
    abilities = []
    for scope, ab in lc.ability_dicts_of_unit(unit):
        name = (ab.get("name") or "").strip()
        desc = " ".join((ab.get("description") or "").split())
        if not name and not desc:
            continue
        abilities.append({"scope": scope, "name": name or "<unnamed>",
                          "description": desc,
                          "enabled": bool(ab.get("enabled", True))})
    notes = [(label, str(value).strip()) for label, value in
             (("Unit composition", getattr(unit, "unit_composition", "")),
              ("Wargear options", getattr(unit, "wargear_options", "")),
              ("Notes", getattr(unit, "notes", "")))
             if str(value).strip()]
    return {"name": unit.name, "points": unit.points,
            "keywords": list(unit.keywords),
            "leadership": list(getattr(unit, "leadership", []) or []),
            "support": list(getattr(unit, "support", []) or []),
            "models": [_model_section(m, unit) for m in unit.models()],
            "abilities": abilities, "notes": notes}


# ---------------- text ----------------


def _table_text(columns, rows, caption="") -> list:
    """Columns padded to their widest cell: a monospaced print stays
    readable, and a paste into a chat window survives."""
    if not rows:
        return []
    widths = [max(len(str(columns[i])),
                  *(len(str(r[i])) for r in rows))
              for i in range(len(columns))]
    out = [f"  {caption}"] if caption else []
    out.append("  " + "  ".join(str(c).ljust(widths[i])
                                for i, c in enumerate(columns)).rstrip())
    for r in rows:
        out.append("  " + "  ".join(str(c).ljust(widths[i])
                                    for i, c in enumerate(r)).rstrip())
    return out


def as_text(unit) -> str:
    s = sections(unit)
    lines = [f"{s['name']}  ({s['points']} pts)",
             "=" * max(12, len(s["name"]) + 12),
             "Keywords: " + (", ".join(s["keywords"]) or "-")]
    if s["leadership"]:
        lines.append("Can lead: " + ", ".join(s["leadership"]))
    if s["support"]:
        lines.append("Can support: " + ", ".join(s["support"]))
    for m in s["models"]:
        lines += ["", f"{m['name']}  x{m['count']}",
                  "  " + "  ".join(f"{k} {v}" for k, v in m["stats"])]
        if m["keywords"]:
            lines.append("  Model keywords: " + ", ".join(m["keywords"]))
        for caption, columns, rows in (
                ("Ranged", RANGED_COLUMNS, m["ranged"]),
                ("Melee", MELEE_COLUMNS, m["melee"])):
            lines += _table_text(columns, rows, caption)
    if s["abilities"]:
        lines += ["", "Abilities"]
        for ab in s["abilities"]:
            off = "" if ab["enabled"] else "  [OFF]"
            lines.append(f"  - [{ab['scope']}] {ab['name']}{off}")
            if ab["description"]:
                lines.append(f"      {ab['description']}")
    for label, value in s["notes"]:
        lines += ["", f"{label}: {value}"]
    return "\n".join(lines) + "\n"


# ---------------- html ----------------

_CSS = """
body { font-family: system-ui, sans-serif; font-size: 11pt;
       margin: 1.5em; color: #111; }
h1 { font-size: 16pt; margin: 0 0 .1em 0; }
h2 { font-size: 12pt; margin: 1em 0 .2em 0;
     border-bottom: 1px solid #999; }
.pts { font-weight: normal; color: #555; }
.kw { color: #444; font-size: 9.5pt; }
.stats span { display: inline-block; margin-right: .9em;
              font-weight: bold; }
table { border-collapse: collapse; width: 100%; margin: .3em 0 .6em 0; }
th, td { border: 1px solid #bbb; padding: 2px 5px; text-align: left;
         font-size: 9.5pt; }
th { background: #eef2f7; }
.model { page-break-inside: avoid; }
.off { color: #888; }
.cap { font-weight: bold; font-size: 9.5pt; margin: .4em 0 0 0; }
.desc { color: #333; font-size: 9.5pt; margin: 0 0 .35em 1.2em; }
@media print { body { margin: 0; } a { text-decoration: none; } }
"""


def _e(value) -> str:
    return _html.escape(str(value), quote=False)


def _table_html(columns, rows, caption="") -> list:
    if not rows:
        return []
    out = [f"<p class='cap'>{_e(caption)}</p>"] if caption else []
    out.append("<table><tr>"
               + "".join(f"<th>{_e(c)}</th>" for c in columns)
               + "</tr>")
    for r in rows:
        out.append("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in r)
                   + "</tr>")
    out.append("</table>")
    return out


def as_html(unit) -> str:
    s = sections(unit)
    body = [f"<h1>{_e(s['name'])} "
            f"<span class='pts'>({s['points']} pts)</span></h1>",
            f"<p class='kw'>{_e(', '.join(s['keywords']) or '-')}</p>"]
    for label, values in (("Can lead", s["leadership"]),
                          ("Can support", s["support"])):
        if values:
            body.append(f"<p class='kw'>{label}: "
                        f"{_e(', '.join(values))}</p>")
    for m in s["models"]:
        body.append("<div class='model'>")
        body.append(f"<h2>{_e(m['name'])} &times;{m['count']}</h2>")
        body.append("<p class='stats'>" + "".join(
            f"<span>{_e(k)}&nbsp;{_e(v)}</span>" for k, v in m["stats"])
            + "</p>")
        if m["keywords"]:
            body.append("<p class='kw'>Model keywords: "
                        f"{_e(', '.join(m['keywords']))}</p>")
        body += _table_html(RANGED_COLUMNS, m["ranged"], "Ranged")
        body += _table_html(MELEE_COLUMNS, m["melee"], "Melee")
        body.append("</div>")
    if s["abilities"]:
        body.append("<h2>Abilities</h2>")
        for ab in s["abilities"]:
            cls = "" if ab["enabled"] else " class='off'"
            off = "" if ab["enabled"] else " [OFF]"
            body.append(f"<p{cls}><b>{_e(ab['name'])}</b>{off} "
                        f"<span class='kw'>[{_e(ab['scope'])}]</span></p>")
            if ab["description"]:
                body.append(f"<p class='desc'>{_e(ab['description'])}</p>")
    for label, value in s["notes"]:
        body.append(f"<h2>{_e(label)}</h2><p class='desc'>{_e(value)}</p>")
    return ("<!DOCTYPE html>\n<html><head><meta charset='utf-8'>\n"
            f"<title>{_e(s['name'])}</title>\n<style>{_CSS}</style>\n"
            "</head><body>\n" + "\n".join(body) + "\n</body></html>\n")


def render(unit, path: str) -> str:
    """Whichever renderer the file name asks for (.txt -> text, HTML
    otherwise), so the format follows the extension the user typed."""
    return as_text(unit) if str(path).lower().endswith((".txt", ".md")) \
        else as_html(unit)


def default_filename(unit) -> str:
    """A file name that survives every file system: letters, digits,
    dashes and underscores only."""
    safe = "".join(ch if (ch.isalnum() or ch in "-_") else "_"
                   for ch in str(unit.name)).strip("_")
    return (safe or "unit") + "_cheatsheet"
