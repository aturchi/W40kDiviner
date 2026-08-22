"""Rows of the analyzer's result table, as plain strings.

Kept apart from the widget on purpose: no tkinter here, so the way the
numbers are turned into a table can be tested headless - and the same
rows can later be written to a CSV without going through the interface.

The one rule worth stating loudly is in totals_row(): only MEANS may be
summed down a column. A median is not additive (the median of a sum is
not the sum of the medians), and neither are the inflicted wounds or
the models killed, which depend on the weapons being chained into the
same target unit. Those are read off the totals distributions instead.
"""

# key, heading, column width in pixels
COLUMNS = (("count", "xN", 44),
           ("att_m", "Attacks \u03bc", 74),
           ("eff_m", "Effective \u03bc", 84),
           ("d_mean", "Damage \u03bc", 76),
           ("d_med", "Damage med", 84),
           ("infl", "Inflicted \u03bc", 80),
           ("kills", "Kills \u03bc", 66),
           ("self", "Self-dmg \u03bc", 84),
           ("per100", "per 100pts", 80))

KEYS = tuple(k for k, _h, _w in COLUMNS)


def _f(x, nd=2):
    return "" if x is None else f"{x:.{nd}f}"


def _mean(pmf):
    return sum(v * p for v, p in enumerate(pmf)) if pmf else None


def weapon_row(r: dict) -> tuple:
    """One weapon. 'Inflicted' and 'Kills' are this weapon ALONE against
    a full-strength unit, so they do not add up to the totals; the
    efficiency column is left to the totals row, because the points
    belong to the unit and not to any one weapon."""
    infl = r.get("removed") or r.get("damage_net")
    return (r["count"], _f(r["attacks"]["mean"]), _f(r["wounds"]["mean"]),
            _f(r["damage"]["mean"]), str(r["damage"]["median"]),
            _f(infl["mean"] if infl else None),
            _f(_mean(r.get("kills_pmf"))),
            _f(r.get("self_damage_mean")), "")


def skipped_row(r: dict) -> tuple:
    """A weapon the attack setup excluded: the reason replaces the
    numbers, so the table still accounts for the whole unit."""
    return (r["count"], r["reason"]) + ("",) * (len(KEYS) - 2)


def totals_label(results: dict) -> str:
    pts = results["totals"].get("points") or 0
    n = len(results["weapons"])
    return f"TOTAL ({n} weapons" + (f", {pts} pts)" if pts else ")")


def totals_row(results: dict) -> tuple:
    """The closing row. Sums only what may be summed."""
    t, rows = results["totals"], results["weapons"]
    infl = t.get("removed") or t.get("damage_net")
    pts = t.get("points") or 0
    self_sum = sum(r["self_damage_mean"] or 0.0 for r in rows)
    return (sum(r["count"] for r in rows),
            _f(sum(r["attacks"]["mean"] for r in rows)),
            _f(sum(r["wounds"]["mean"] for r in rows)),
            _f(t["damage"]["mean"]), str(t["damage"]["median"]),
            _f(infl["mean"] if infl else None),
            _f(t["kills"]["mean"] if t.get("kills") else None),
            _f(self_sum) if self_sum else "",
            _f(infl["mean"] / pts * 100) if (pts and infl) else "")


def table(results: dict) -> list:
    """The whole table as [(name, values)], totals row included."""
    out = [(r["name"], weapon_row(r)) for r in results["weapons"]]
    out += [(r["name"], skipped_row(r)) for r in results.get("skipped", [])]
    out.append((totals_label(results), totals_row(results)))
    return out


def to_csv(results: dict) -> str:
    """The same table as CSV text (no file I/O, no quoting surprises:
    weapon names are the only free text and commas in them are quoted)."""
    def cell(v):
        v = str(v)
        return '"' + v.replace('"', '""') + '"' if ("," in v or '"' in v) \
            else v

    lines = [",".join(["Weapon"] + [h for _k, h, _w in COLUMNS])]
    for name, vals in table(results):
        lines.append(",".join(cell(v) for v in (name,) + tuple(vals)))
    return "\n".join(lines) + "\n"
