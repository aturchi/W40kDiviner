"""Rows of the analyzer's result table, as plain strings.

Kept apart from the widget on purpose: no tkinter here, so the way the
numbers are turned into a table can be tested headless - and the same
rows can later be written to a CSV without going through the interface.

The one rule worth stating loudly is in totals_row(): only MEANS may be
summed down a column. A median is not additive (the median of a sum is
not the sum of the medians), and neither are the inflicted wounds or
the models killed, which depend on the weapons being chained into the
same target unit. Those are read off the totals distributions instead.

Which columns exist is a property of the ANALYSIS, not a constant: see
columns(). Every row builder therefore takes the key list it is being
projected onto instead of deciding again for itself - a row that
disagreed with the headings above it would put the right numbers in the
wrong columns, which is worse than showing nothing at all.
"""

# key, heading, column width in pixels
ALL_COLUMNS = (("count", "xN", 44),
               ("att_m", "Attacks \u03bc", 74),
               ("eff_m", "Effective \u03bc", 84),
               ("d_mean", "Damage \u03bc", 76),
               ("d_med", "Damage med", 84),
               ("infl", "Inflicted \u03bc", 80),
               ("kills", "Kills \u03bc", 66),
               ("self", "Self-dmg \u03bc", 84),
               ("per100", "per 100pts", 80))

ALL_KEYS = tuple(k for k, _h, _w in ALL_COLUMNS)

# What each heading means. The text lives here rather than in the window
# because it belongs to the column definition: a column that changed
# meaning and kept its old help would be worse than one with none. Two
# things every entry has to be honest about, because they are where the
# table is misread: whether the column is ADDITIVE (so the totals row
# could sum it) and whether a weapon row means the same thing as the
# totals row.
NAME_HELP = ("The weapon, one row each, then the TOTAL.\n\n"
             "A greyed row is a weapon the attack setup excluded - the "
             "reason replaces its numbers. The TOTAL chains the weapons "
             "into the SAME target unit, in the firing order reported "
             "under the table, so it is not the sum of the rows above "
             "it.")

COLUMN_HELP = {
    "count": ("How many copies of this weapon the unit is firing, "
              "models included.\n\n"
              "Set in the unit tree (masking a weapon takes it to 0, "
              "and the count can be typed by hand). On the TOTAL it is "
              "the sum over the weapons that fired."),
    "att_m": ("Mean number of attack ROLLS made: the Attacks "
              "characteristic times the count, a dice expression "
              "averaged, plus whatever an ability adds.\n\n"
              "Additive, so the TOTAL really is the sum of the rows."),
    "eff_m": ("Mean number of attacks that ended up dealing damage - "
              "past the hit roll, the wound roll, the save or "
              "invulnerable save AND Feel No Pain.\n\n"
              "NOT the number of successful wound rolls: an attack that "
              "wounds and is then saved never becomes effective. "
              "Additive."),
    "d_mean": ("Mean GROSS damage rolled, before any of it is wasted: "
               "an attack of 6 damage on a 2-wound model counts 6 "
               "here.\n\n"
               "Compare it with Inflicted to see the overkill. Additive "
               "as a mean, which is why the TOTAL agrees with the sum "
               "of the rows."),
    "d_med": ("Median gross damage: the value the roll falls below half "
              "the time.\n\n"
              "NOT additive - the median of a sum is not the sum of the "
              "medians - so the TOTAL shows the median of the combined "
              "distribution, not a column sum."),
    "infl": ("Wounds actually taken off the unit, waste on a destroyed "
             "model deducted.\n\n"
             "On a weapon row this is that weapon ALONE against a unit "
             "at full strength, so the weapon rows do NOT add up to the "
             "total: the total chains the weapons into the same unit, "
             "each firing into what the previous ones left standing."),
    "kills": ("Models destroyed, by the exact allocation chain.\n\n"
              "On a weapon row this is that weapon ALONE against a unit "
              "at full strength, so the weapon rows do NOT add up to "
              "the total - and two weapons that each average half a "
              "model kill a whole one when they are fired together."),
    "self": ("Mean damage the firing unit does to ITSELF with its "
             "HAZARDOUS weapons: one D6 per copy, a 1 or a 2 failing "
             "the test.\n\n"
             "The median is 0 and is deliberately not shown. The column "
             "appears only when a HAZARDOUS weapon is in the list."),
    "per100": ("Wounds inflicted per 100 points of the ATTACKING "
               "unit.\n\n"
               "On the TOTAL row only: the points bought the whole "
               "unit, so no single weapon can be charged with a share "
               "of them."),
}


def columns(results: dict) -> tuple:
    """The columns this analysis actually has.

    'Self-dmg' is dropped unless a HAZARDOUS weapon is in the list: the
    engine leaves self_damage_mean at None for every other weapon, so
    otherwise the column is a stripe of blanks that still has to be read
    before it can be ignored.
    """
    hazardous = any(r.get("self_damage_mean") is not None
                    for r in results.get("weapons", ()))
    return tuple(c for c in ALL_COLUMNS if hazardous or c[0] != "self")


def keys(results: dict) -> tuple:
    """Just the keys of columns(results), in the same order."""
    return tuple(k for k, _h, _w in columns(results))


def _f(x, nd=2):
    return "" if x is None else f"{x:.{nd}f}"


def _mean(pmf):
    return sum(v * p for v, p in enumerate(pmf)) if pmf else None


def _project(cells: dict, cols) -> tuple:
    """A row in the order of 'cols'. A key the builder did not fill is
    blank rather than missing, so a row is always as wide as the table."""
    return tuple(cells.get(k, "") for k in cols)


def weapon_row(r: dict, cols=ALL_KEYS) -> tuple:
    """One weapon. 'Inflicted' and 'Kills' are this weapon ALONE against
    a full-strength unit, so they do not add up to the totals; the
    efficiency column is left to the totals row, because the points
    belong to the unit and not to any one weapon."""
    infl = r.get("removed") or r.get("damage_net")
    return _project({"count": r["count"],
                     "att_m": _f(r["attacks"]["mean"]),
                     "eff_m": _f(r["wounds"]["mean"]),
                     "d_mean": _f(r["damage"]["mean"]),
                     "d_med": str(r["damage"]["median"]),
                     "infl": _f(infl["mean"] if infl else None),
                     "kills": _f(_mean(r.get("kills_pmf"))),
                     "self": _f(r.get("self_damage_mean"))}, cols)


def skipped_row(r: dict, cols=ALL_KEYS) -> tuple:
    """A weapon the attack setup excluded: the reason replaces the
    numbers, so the table still accounts for the whole unit. Positional
    on purpose - the reason is a sentence and runs across whichever
    columns follow the count."""
    return (r["count"], r["reason"]) + ("",) * (len(cols) - 2)


def totals_label(results: dict) -> str:
    pts = results["totals"].get("points") or 0
    n = len(results["weapons"])
    return f"TOTAL ({n} weapons" + (f", {pts} pts)" if pts else ")")


def totals_row(results: dict, cols=ALL_KEYS) -> tuple:
    """The closing row. Sums only what may be summed."""
    t, rows = results["totals"], results["weapons"]
    infl = t.get("removed") or t.get("damage_net")
    pts = t.get("points") or 0
    self_sum = sum(r["self_damage_mean"] or 0.0 for r in rows)
    return _project(
        {"count": sum(r["count"] for r in rows),
         "att_m": _f(sum(r["attacks"]["mean"] for r in rows)),
         "eff_m": _f(sum(r["wounds"]["mean"] for r in rows)),
         "d_mean": _f(t["damage"]["mean"]),
         "d_med": str(t["damage"]["median"]),
         "infl": _f(infl["mean"] if infl else None),
         "kills": _f(t["kills"]["mean"] if t.get("kills") else None),
         "self": _f(self_sum) if self_sum else "",
         "per100": _f(infl["mean"] / pts * 100) if (pts and infl) else ""},
        cols)


def table(results: dict) -> list:
    """The whole table as [(name, values)], totals row included."""
    cols = keys(results)
    out = [(r["name"], weapon_row(r, cols)) for r in results["weapons"]]
    out += [(r["name"], skipped_row(r, cols))
            for r in results.get("skipped", [])]
    out.append((totals_label(results), totals_row(results, cols)))
    return out


def to_csv(results: dict) -> str:
    """The same table as CSV text (no file I/O, no quoting surprises:
    weapon names are the only free text and commas in them are quoted)."""
    def cell(v):
        v = str(v)
        return '"' + v.replace('"', '""') + '"' if ("," in v or '"' in v) \
            else v

    lines = [",".join(["Weapon"] + [h for _k, h, _w in columns(results)])]
    for name, vals in table(results):
        lines.append(",".join(cell(v) for v in (name,) + tuple(vals)))
    return "\n".join(lines) + "\n"
