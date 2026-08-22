"""Pinned analyses and the matrix that compares them.

The most repeated gesture at the table is running the same attack twice
with one thing changed - a weapon switched off, cover on, a different
target - and the result window of the first run is gone by the time the
second appears. So a result page can be PINNED, and the pins are lined
up side by side with the difference against the first one.

No tkinter here: a pin is a plain dict of numbers and PMFs, the matrix
is a list of rows, and the CSV is a string. What the widget adds is the
buttons and the overlaid histograms.

The context signature matters as much as the numbers. Comparing two
analyses run with different flags without noticing is the easiest way
to draw a wrong conclusion from a right calculation, so every pin
carries the flags and modifiers that produced it and the matrix marks
the ones that differ from the first pin.
"""

import dist_stats as ds

# key, label, how to read it out of a pin
METRICS = (
    ("attacks", "Attacks \u03bc", 2),
    ("effective", "Effective \u03bc", 2),
    ("damage", "Gross damage \u03bc", 2),
    ("damage_med", "Gross damage median", 0),
    ("inflicted", "Wounds inflicted \u03bc", 2),
    ("inflicted_med", "Wounds inflicted median", 0),
    ("kills", "Models killed \u03bc", 2),
    ("kills_med", "Models killed median", 0),
    ("wipe", "P(unit destroyed) %", 1),
    ("per100", "Wounds per 100 pts", 2),
)

# Flags that say nothing when False, so they are only listed when set.
_FLAG_LABELS = {"half_range": "half range", "cover": "cover",
                "charged": "charged", "attacker_stationary": "stationary",
                "attacker_below_half": "att below half",
                "defender_below_half": "def below half",
                "attacker_on_objective": "att on objective",
                "defender_on_objective": "def on objective",
                "attacker_in_engagement": "att engaged",
                "defender_in_engagement": "def engaged",
                "overwatch": "overwatch",
                "optimise_abilities": "optimise abilities"}


def context_signature(flags: dict, mods: dict, mode: str) -> str:
    """A short human-readable description of everything, besides the
    two units, that shaped the numbers."""
    bits = [mode]
    for key, label in _FLAG_LABELS.items():
        if (flags or {}).get(key):
            bits.append(label)
    n_off = len((flags or {}).get("disabled_abilities") or [])
    if n_off:
        bits.append(f"{n_off} ability off")
    n_on = len((flags or {}).get("extra_abilities") or [])
    if n_on:
        bits.append(f"{n_on} ability forced on")
    for group in ("rolls", "weapon", "attacker_model", "defender_model"):
        for key, val in sorted(((mods or {}).get(group) or {}).items()):
            if val:
                bits.append(f"{key}{val:+d}")
    for roll, what in sorted(((mods or {}).get("rerolls") or {}).items()):
        bits.append(f"reroll {roll} {what}")
    return ", ".join(bits)


def make_pin(name: str, results: dict, context: str = "") -> dict:
    """Freeze one result page into a pin: the metrics, the PMFs the
    comparison plots, and the context that produced them."""
    t = results["totals"]
    infl = t.get("removed") or t.get("damage_net")
    infl_pmf = t.get("removed_pmf") or t.get("damage_net_pmf")
    kills_pmf = t.get("kills_pmf")
    pts = t.get("points") or 0
    return {
        "name": name, "context": context,
        "values": {
            "attacks": sum(r["attacks"]["mean"] for r in results["weapons"]),
            "effective": sum(r["wounds"]["mean"]
                             for r in results["weapons"]),
            "damage": t["damage"]["mean"],
            "damage_med": t["damage"]["median"],
            "inflicted": infl["mean"] if infl else None,
            "inflicted_med": infl["median"] if infl else None,
            "kills": t["kills"]["mean"] if t.get("kills") else None,
            "kills_med": t["kills"]["median"] if t.get("kills") else None,
            "wipe": t["p_wipe"] * 100 if t.get("p_wipe") is not None
            else None,
            "per100": (infl["mean"] / pts * 100) if (pts and infl)
            else None},
        "pmfs": {"inflicted": list(infl_pmf or []),
                 "kills": list(kills_pmf or []),
                 "damage": list(t["damage_pmf"])},
        "points": pts,
        "unit_wounds": (t.get("models") or 0) * (t.get("W") or 0),
    }


def _fmt(value, nd: int) -> str:
    if value is None:
        return ""
    return f"{value:.{nd}f}" if nd else f"{value:.0f}"


def _delta(value, base, nd: int) -> str:
    """Difference against the first pin, signed. Empty for the first
    column and whenever either side is missing."""
    if value is None or base is None:
        return ""
    d = value - base
    if abs(d) < 0.5 * 10 ** -nd:
        return "="
    return f"{d:+.{nd}f}" if nd else f"{d:+.0f}"


def matrix(pins, deltas: bool = True) -> list:
    """Rows of the comparison table: (label, [cell per pin]).

    With deltas, every column past the first carries its difference
    against the first pin, which is the question actually being asked -
    'what did changing that one thing do?'.
    """
    rows = []
    for key, label, nd in METRICS:
        if all(p["values"].get(key) is None for p in pins):
            continue                      # nothing to show for this metric
        cells = []
        base = pins[0]["values"].get(key) if pins else None
        for i, p in enumerate(pins):
            v = p["values"].get(key)
            text = _fmt(v, nd)
            if deltas and i and text:
                text += f"  ({_delta(v, base, nd)})"
            cells.append(text)
        rows.append((label, cells))
    return rows


def context_rows(pins) -> list:
    """Header rows: what each pin was, and whether its context differs
    from the first one - the comparison is only meaningful if the
    reader can see that."""
    rows = [("Analysis", [p["name"] for p in pins])]
    ctx = [p.get("context", "") for p in pins]
    rows.append(("Context", list(ctx)))
    if len(pins) > 1:
        same = ["-"] + ["same" if c == ctx[0] else "DIFFERENT"
                        for c in ctx[1:]]
        rows.append(("vs first", same))
    rows.append(("Points", [str(p.get("points") or "") for p in pins]))
    return rows


def summary(pins) -> str:
    """One line per pin, for a caption or a log entry."""
    out = []
    for p in pins:
        v = p["values"]
        out.append(f"{p['name']}: inflicted {_fmt(v.get('inflicted'), 2)}, "
                   f"kills {_fmt(v.get('kills'), 2)}, "
                   f"wipe {_fmt(v.get('wipe'), 1)}%")
    return "\n".join(out)


def to_csv(pins) -> str:
    """The comparison as CSV: same rows, no delta annotations, so the
    numbers stay machine-readable."""
    def cell(v):
        v = str(v)
        return '"' + v.replace('"', '""') + '"' if ("," in v or '"' in v) \
            else v

    lines = [",".join(cell(c) for c in ["Metric"]
                      + [p["name"] for p in pins])]
    lines.append(",".join(cell(c) for c in ["Context"]
                          + [p.get("context", "") for p in pins]))
    for key, label, nd in METRICS:
        lines.append(",".join(cell(c) for c in [label]
                              + [_fmt(p["values"].get(key), nd)
                                 for p in pins]))
    return "\n".join(lines) + "\n"


def overlay_series(pins, key: str = "inflicted") -> list:
    """The same PMF from every pin, ready to be drawn on one chart."""
    return [{"name": p["name"], "pmf": p["pmfs"].get(key) or [],
             "stats": ds.stats(p["pmfs"].get(key) or [1.0])}
            for p in pins]
