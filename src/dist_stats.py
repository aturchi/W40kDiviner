"""Statistics read off a damage probability mass function.

A PMF here is the same object the attack maths produces: a list of
probabilities indexed by the integer value, so ``pmf[3]`` is P(X == 3).
The analyzer already computes these exactly; this module only reads
them, which is why it is GUI-free and fully testable headless.

Provided:
  - percentile() / tail_prob(): the two questions a player actually
    asks ("how bad can it get", "what are my odds of at least N");
  - stats(): mean / sd / median / mode and the SPREAD pair in one
    dict. The pair is keyed 'lo' and 'hi', never by its percentile:
    which two percentiles are reported is a matter of taste (SPREAD
    below) and hard-coding them into the keys would spread that choice
    across every caller;
  - histogram(): the PMF folded into a bounded number of bars, ready
    to be drawn, with the far upper tail cut off and reported apart
    (a D6-damage weapon can reach values whose probability is 1e-9,
    and plotting them squashes everything else into the first pixel);
  - default_xmax(): where that automatic cut falls, so the view can
    offer the axis bounds as controls and start them from the same
    place the drawing would have chosen.
"""


def total_mass(pmf) -> float:
    """Sum of the PMF. Should be 1.0; used to detect drift."""
    return sum(pmf)


def cdf(pmf) -> list:
    """Cumulative distribution: out[v] = P(X <= v)."""
    out, acc = [], 0.0
    for p in pmf:
        acc += p
        out.append(acc)
    return out


def percentile(pmf, q: float) -> int:
    """Smallest value v with P(X <= v) >= q (discrete quantile).

    q is a fraction, not a percentage: percentile(pmf, 0.9) is p90.
    """
    acc = 0.0
    for v, p in enumerate(pmf):
        acc += p
        if acc >= q - 1e-12:
            return v
    return max(0, len(pmf) - 1)


def tail_prob(pmf, n: int) -> float:
    """P(X >= n): the probability of dealing AT LEAST n damage."""
    if n <= 0:
        return total_mass(pmf)
    if n >= len(pmf):
        return 0.0
    return sum(pmf[n:])


# The two percentiles reported either side of the median, and the only
# place they are decided. 25/75 is the interquartile range: it brackets
# the half of the outcomes around the middle, which is what a player
# means by "a normal roll". A wider pair (10/90) answers a different
# question - how bad a bad roll gets - and is a one-line change here.
SPREAD = (0.25, 0.75)
SPREAD_LABELS = tuple("p%d" % round(q * 100) for q in SPREAD)


def stats(pmf) -> dict:
    """mean, sd, median, mode, the top of the support, and the SPREAD
    pair as 'lo' and 'hi' (see SPREAD for which percentiles those are)."""
    mean = sum(v * p for v, p in enumerate(pmf))
    var = sum(p * (v - mean) ** 2 for v, p in enumerate(pmf))
    mode = max(range(len(pmf)), key=lambda v: pmf[v]) if pmf else 0
    return {"mean": mean, "sd": var ** 0.5,
            "median": percentile(pmf, 0.5),
            "lo": percentile(pmf, SPREAD[0]),
            "hi": percentile(pmf, SPREAD[1]),
            "mode": mode, "max": max(0, len(pmf) - 1)}


def default_xmax(pmf, keep: float = 0.999) -> int:
    """The last value a histogram plots when nothing forces the axis:
    the 'keep' quantile, never past the end of the support.

    Exposed because the view offers the axis length as a control and has
    to be able to show what the automatic choice was."""
    if not pmf:
        return 0
    return min(len(pmf) - 1, max(1, percentile(pmf, keep)))


def histogram(pmf, max_bars: int = 40, keep: float = 0.999,
              cut=None, low=None) -> dict:
    """Fold the PMF into at most 'max_bars' contiguous bars.

    Values above the 'keep' quantile are dropped from the bars and
    their total probability reported as 'cut_mass', so a long thin
    tail cannot flatten the body of the distribution. Bars are
    integer ranges [lo, hi] (a single value when width == 1).

    'cut' and 'low' force the last and the first value plotted - the two
    ends of the X axis - and None asks for the automatic ones (the keep
    quantile, and zero). Either way the mass outside them is reported as
    'cut_mass' and 'low_mass': narrowing the axis hides BARS, never
    probability, and the percentiles beside the chart keep describing
    the whole distribution.

    Returns {'bins': [(lo, hi, p)], 'width': int, 'cut': int|None,
    'cut_mass': float, 'low': int|None, 'low_mass': float}: 'cut' and
    'low' are the last and first values shown, and are None when there
    is no mass hidden beyond them - which is what the caller annotates
    on, so a bound that hides nothing is not worth a label.
    """
    if not pmf:
        return {"bins": [(0, 0, 0.0)], "width": 1, "cut": None,
                "cut_mass": 0.0, "low": None, "low_mass": 0.0}
    top = len(pmf) - 1
    cut = default_xmax(pmf, keep) if cut is None \
        else max(0, min(top, int(cut)))
    # The floor never crosses the ceiling: an empty axis is not a view
    # of anything, so a minimum above the maximum collapses to it.
    low = 0 if low is None else max(0, min(cut, int(low)))
    cut_mass = tail_prob(pmf, cut + 1)
    low_mass = sum(pmf[:low])
    n = cut - low + 1
    width = max(1, -(-n // max(1, max_bars)))      # ceil division
    bins = []
    for start in range(low, cut + 1, width):
        hi = min(start + width - 1, cut)
        bins.append((start, hi, sum(pmf[start:hi + 1])))
    return {"bins": bins, "width": width,
            "cut": cut if cut_mass > 0 else None, "cut_mass": cut_mass,
            "low": low if low_mass > 0 else None, "low_mass": low_mass}


def summary_line(pmf, unit: str = "damage") -> str:
    """One-line textual summary, shared by the dialog and the exports."""
    s = stats(pmf)
    lo, hi = SPREAD_LABELS
    return (f"mean {s['mean']:.2f}  sd {s['sd']:.2f}  |  "
            f"{lo} {s['lo']}  median {s['median']}  {hi} {s['hi']}  "
            f"({unit})")
