"""Rows of the analyzer's result table, as plain strings.

Kept apart from the widget on purpose: no tkinter here, so the way the
numbers are turned into a table can be tested headless - and the same
rows can later be written to a CSV without going through the interface.

Two things are properties of the ANALYSIS rather than constants, and
both are threaded through every row builder instead of being decided
again inside each one:

  * WHICH columns exist - see columns();
  * WHICH STATISTIC each column is showing. Every column backed by a
    distribution can be read as a mean, a median or a percentile, and
    the heading says which. A row that disagreed with the headings
    above it would put the right numbers in the wrong columns, which is
    worse than showing nothing at all.

The old rule about the totals row survives in a stronger form. It used
to be "only means may be summed down a column"; now nothing is summed
at all except the weapon COUNT. Every statistic of the totals is read
off the unit's own distribution, which analyzer_core convolves - and
for a mean that gives exactly what summing the column gave, while for a
median or a percentile it gives the only correct answer.
"""
import dist_stats as ds

# The statistics a column can be read as, in the order a click on the
# heading cycles through them.
STATS = ("mean", "median", "lo", "hi")
STAT_LABEL = dict(zip(("lo", "hi"), ds.SPREAD_LABELS),
                  **{"mean": "\u03bc", "median": "med"})
# Which fraction each statistic reads off the distribution. dist_stats
# owns the spread pair, so changing it there changes the headings, the
# chart readout and this cycle together.
STAT_Q = {"median": 0.5, "lo": ds.SPREAD[0], "hi": ds.SPREAD[1]}

# key, heading title, column width in pixels
ALL_COLUMNS = (("count", "xN", 44),
               ("att_m", "Attacks", 74),
               ("eff_m", "Effective", 84),
               ("dmg", "Damage", 80),
               ("infl", "Inflicted", 80),
               ("kills", "Kills", 66),
               ("self", "Self-dmg", 84),
               ("per100", "per 100pts", 80))

ALL_KEYS = tuple(k for k, _h, _w in ALL_COLUMNS)
TITLES = {k: t for k, t, _w in ALL_COLUMNS}

# Which distribution each statistic column is read from. The keys are
# the same on a weapon row and on the totals, so one lookup serves both
# - the difference between "this weapon alone" and "the whole unit" is
# in how analyzer_core built the PMF, not in how the table reads it.
# A tuple is a fallback chain: 'removed_pmf' is absent when the
# allocation chain did not run, and the net damage is the estimate.
STAT_PMF = {"att_m": ("attacks_pmf",),
            "eff_m": ("wounds_pmf",),
            "dmg": ("damage_pmf",),
            "infl": ("removed_pmf", "damage_net_pmf"),
            "kills": ("kills_pmf",),
            "self": ("self_damage_pmf",)}

# 'xN' is a count, not a sample, and 'per 100pts' is an efficiency that
# is only meaningful as a mean: a percentile of a ratio of two
# percentiles is not a percentile of anything.
FIXED_KEYS = tuple(k for k in ALL_KEYS if k not in STAT_PMF)


def next_stat(stat: str) -> str:
    """The statistic a click on the heading moves to."""
    return STATS[(STATS.index(stat) + 1) % len(STATS)] \
        if stat in STATS else STATS[0]


def heading(key: str, stat: str = "mean") -> str:
    """The heading text for a column under the statistic on show. The
    marker is not decoration: without it a median is indistinguishable
    from a mean, and the two differ by more than a rounding on any
    skewed distribution."""
    title = TITLES.get(key, key)
    return f"{title} {STAT_LABEL[stat]}" if key in STAT_PMF else title


def _pmf(src: dict, key: str):
    """The distribution behind a statistic column, following the
    fallback chain."""
    for name in STAT_PMF.get(key, ()):
        pmf = src.get(name)
        if pmf:
            return pmf
    return None


def _stat(pmf, stat: str) -> str:
    """One statistic of a PMF, formatted. Means keep two decimals;
    a median and a percentile are VALUES the dice can actually produce,
    so they are printed as the integers they are."""
    if not pmf:
        return ""
    if stat == "mean":
        return _f(sum(v * p for v, p in enumerate(pmf)))
    return str(ds.percentile(pmf, STAT_Q[stat]))


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
    "att_m": ("Attack ROLLS made: the Attacks characteristic times the "
              "count, plus whatever an ability adds.\n\n"
              "Click the heading to read this column as a median or a "
              "percentile instead of a mean - useful wherever Attacks "
              "is a dice expression."),
    "eff_m": ("Attacks that ended up dealing damage - past the hit "
              "roll, the wound roll, the save or invulnerable save AND "
              "Feel No Pain.\n\n"
              "NOT the number of successful wound rolls: an attack that "
              "wounds and is then saved never becomes effective."),
    "dmg": ("GROSS damage rolled, before any of it is wasted: an "
            "attack of 6 damage on a 2-wound model counts 6 here.\n\n"
            "Compare it with Inflicted to see the overkill."),
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
    "self": ("Damage the firing unit does to ITSELF with its HAZARDOUS "
             "weapons: one D6 per copy, a 1 or a 2 failing the "
             "test.\n\n"
             "Worth a click on the heading: two hazardous weapons "
             "average 1.33 damage but their most likely outcome is "
             "none at all, which only the median shows. The column "
             "appears only when a HAZARDOUS weapon is in the list."),
    "per100": ("Mean wounds inflicted per 100 points of the ATTACKING "
               "unit.\n\n"
               "On the TOTAL row only: the points bought the whole "
               "unit, so no single weapon can be charged with a share "
               "of them. Always a mean, whatever Inflicted is showing - "
               "a ratio of two percentiles is not a percentile of the "
               "ratio."),
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


def _project(cells: dict, cols) -> tuple:
    """A row in the order of 'cols'. A key the builder did not fill is
    blank rather than missing, so a row is always as wide as the table."""
    return tuple(cells.get(k, "") for k in cols)


def _stat_cells(src: dict, cols, stats) -> dict:
    """Every statistic column of one row, read off its own PMF. Shared
    by the weapon rows and the totals, which differ only in the two
    columns that are not statistics."""
    stats = stats or {}
    return {k: _stat(_pmf(src, k), stats.get(k, "mean"))
            for k in cols if k in STAT_PMF}


def weapon_row(r: dict, cols=ALL_KEYS, stats=None) -> tuple:
    """One weapon. 'Inflicted' and 'Kills' are this weapon ALONE against
    a full-strength unit, so they do not add up to the totals; the
    efficiency column is left to the totals row, because the points
    belong to the unit and not to any one weapon."""
    cells = _stat_cells(r, cols, stats)
    cells["count"] = r["count"]
    return _project(cells, cols)


def skipped_row(r: dict, cols=ALL_KEYS, stats=None) -> tuple:
    """A weapon the attack setup excluded: the reason replaces the
    numbers, so the table still accounts for the whole unit. Positional
    on purpose - the reason is a sentence and runs across whichever
    columns follow the count."""
    return (r["count"], r["reason"]) + ("",) * (len(cols) - 2)


def totals_label(results: dict) -> str:
    pts = results["totals"].get("points") or 0
    n = len(results["weapons"])
    return f"TOTAL ({n} weapons" + (f", {pts} pts)" if pts else ")")


def totals_row(results: dict, cols=ALL_KEYS, stats=None) -> tuple:
    """The closing row, read off the unit's own distributions.

    Nothing is summed down a column here except the weapon count. For a
    mean that makes no difference - a mean is additive - but a median
    or a percentile of the unit is not a function of the weapons'
    medians at all, and reading it off the convolved law is the only
    way to get it right.
    """
    t, rows = results["totals"], results["weapons"]
    cells = _stat_cells(t, cols, stats)
    cells["count"] = sum(r["count"] for r in rows)
    pts = t.get("points") or 0
    infl = _pmf(t, "infl")
    # Efficiency stays a MEAN whatever the Inflicted column is showing:
    # a ratio of two percentiles is not a percentile of the ratio.
    if pts and infl:
        cells["per100"] = _f(sum(v * p for v, p in enumerate(infl))
                             / pts * 100)
    return _project(cells, cols)


def table(results: dict, stats=None) -> list:
    """The whole table as [(name, values)], totals row included."""
    cols = keys(results)
    out = [(r["name"], weapon_row(r, cols, stats))
           for r in results["weapons"]]
    out += [(r["name"], skipped_row(r, cols, stats))
            for r in results.get("skipped", [])]
    out.append((totals_label(results), totals_row(results, cols, stats)))
    return out


def to_csv(results: dict, stats=None) -> str:
    """The same table as CSV text, headings included - so the export
    carries WHICH statistic each column was showing and cannot be
    mistaken for a table of means (no file I/O, and weapon names are
    the only free text: commas in them are quoted)."""
    def cell(v):
        v = str(v)
        return '"' + v.replace('"', '""') + '"' if ("," in v or '"' in v) \
            else v

    stats = stats or {}
    lines = [",".join(["Weapon"] + [heading(k, stats.get(k, "mean"))
                                    for k, _t, _w in columns(results)])]
    for name, vals in table(results, stats):
        lines.append(",".join(cell(v) for v in (name,) + tuple(vals)))
    return "\n".join(lines) + "\n"
