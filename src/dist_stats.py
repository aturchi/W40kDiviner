"""Statistics read off a damage probability mass function.

A PMF here is the same object the attack maths produces: a list of
probabilities indexed by the integer value, so ``pmf[3]`` is P(X == 3).
The analyzer already computes these exactly; this module only reads
them, which is why it is GUI-free and fully testable headless.

Provided:
  - percentile() / tail_prob(): the two questions a player actually
    asks ("how bad can it get", "what are my odds of at least N");
  - stats(): mean / sd / median / p10 / p90 / mode in one dict;
  - histogram(): the PMF folded into a bounded number of bars, ready
    to be drawn, with the far upper tail cut off and reported apart
    (a D6-damage weapon can reach values whose probability is 1e-9,
    and plotting them squashes everything else into the first pixel).
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


def stats(pmf) -> dict:
    """mean, sd, median, p10, p90, mode and the top of the support."""
    mean = sum(v * p for v, p in enumerate(pmf))
    var = sum(p * (v - mean) ** 2 for v, p in enumerate(pmf))
    mode = max(range(len(pmf)), key=lambda v: pmf[v]) if pmf else 0
    return {"mean": mean, "sd": var ** 0.5,
            "median": percentile(pmf, 0.5),
            "p10": percentile(pmf, 0.10),
            "p90": percentile(pmf, 0.90),
            "mode": mode, "max": max(0, len(pmf) - 1)}


def histogram(pmf, max_bars: int = 40, keep: float = 0.999) -> dict:
    """Fold the PMF into at most 'max_bars' contiguous bars.

    Values above the 'keep' quantile are dropped from the bars and
    their total probability reported as 'cut_mass', so a long thin
    tail cannot flatten the body of the distribution. Bars are
    integer ranges [lo, hi] (a single value when width == 1).

    Returns {'bins': [(lo, hi, p)], 'width': int, 'cut': int|None,
    'cut_mass': float}: 'cut' is the last value shown, None when the
    whole support is on screen.
    """
    if not pmf:
        return {"bins": [(0, 0, 0.0)], "width": 1, "cut": None,
                "cut_mass": 0.0}
    top = len(pmf) - 1
    cut = max(1, percentile(pmf, keep))
    if cut >= top:
        cut, cut_mass = top, 0.0
    else:
        cut_mass = tail_prob(pmf, cut + 1)
    n = cut + 1
    width = max(1, -(-n // max(1, max_bars)))      # ceil division
    bins = []
    for lo in range(0, n, width):
        hi = min(lo + width - 1, cut)
        bins.append((lo, hi, sum(pmf[lo:hi + 1])))
    return {"bins": bins, "width": width,
            "cut": cut if cut_mass > 0 else None, "cut_mass": cut_mass}


def summary_line(pmf, unit: str = "damage") -> str:
    """One-line textual summary, shared by the dialog and the exports."""
    s = stats(pmf)
    return (f"mean {s['mean']:.2f}  sd {s['sd']:.2f}  |  "
            f"p10 {s['p10']}  median {s['median']}  p90 {s['p90']}  "
            f"({unit})")
