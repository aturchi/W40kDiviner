"""Distribution statistics (src/dist_stats.py) against closed forms."""
import testpaths                      # sets up sys.path to the engine src/
import dist_stats as ds
import attack_math as am


def close(a, b, eps=1e-9):
    assert abs(a - b) < eps, f"{a} != {b}"


# ---- single d6: percentiles, tail, stats -------------------------------
d6 = [0.0] + [1 / 6] * 6
close(ds.total_mass(d6), 1.0)
assert ds.percentile(d6, 0.5) == 3, ds.percentile(d6, 0.5)
assert ds.percentile(d6, 0.10) == 1
assert ds.percentile(d6, 0.90) == 6      # P(X<=5) = 5/6 < 0.9
close(ds.tail_prob(d6, 5), 2 / 6)
close(ds.tail_prob(d6, 1), 1.0)
close(ds.tail_prob(d6, 0), 1.0)
close(ds.tail_prob(d6, 7), 0.0)
s = ds.stats(d6)
close(s["mean"], 3.5)
close(s["sd"], (35 / 12) ** 0.5)          # variance of a d6 = 35/12
assert s["max"] == 6

# ---- 'max' is the top of the SUPPORT, not the end of the list --------
# kill_chain sizes its vectors on the target (models + 1, W*models + 1)
# and leaves what the weapon cannot reach at exactly zero, so reading the
# maximum off len(pmf) reported the unit's model count as if it were a
# statistic of the attack.
assert ds.support_top(d6) == 6
assert ds.support_top([0.0] + [1 / 6] * 6 + [0.0] * 9) == 6
assert ds.stats([0.0] + [1 / 6] * 6 + [0.0] * 9)["max"] == 6
assert ds.support_top([1.0]) == 0
assert ds.support_top([1.0, 0.0, 0.0]) == 0
assert ds.support_top([]) == 0                 # no support at all
assert ds.support_top([0.0, 0.0]) == 0         # all-zero: no value at all
# A leading run of zeros is not a reason to look further down.
assert ds.support_top([0.0, 0.0, 0.5, 0.5, 0.0]) == 3
# The other statistics are blind to trailing zeros and must stay so.
padded = ds.stats(d6 + [0.0] * 5)
for k in ("mean", "sd", "median", "lo", "hi", "mode"):
    assert padded[k] == ds.stats(d6)[k], k

# A quantile is the SMALLEST value reaching q, boundaries included:
# P(X <= 3) is exactly 0.5 for a d6, so p50 is 3 and not 4.
assert ds.percentile(d6, 0.5) == 3

# ---- 2d6: convolution vs closed form ----------------------------------
two = am.convolve(d6, d6)
close(ds.stats(two)["mean"], 7.0)
close(ds.tail_prob(two, 10), 6 / 36)      # 10, 11, 12 -> 3+2+1 of 36
assert ds.stats(two)["mode"] == 7

# ---- degenerate cases --------------------------------------------------
zero = am.delta(0)
h = ds.histogram(zero)
assert h["bins"] == [(0, 0, 1.0)], h
assert h["cut"] is None and h["cut_mass"] == 0.0
assert ds.stats(zero)["median"] == 0

# ---- histogram: binning, conservation of mass, tail cut ----------------
h = ds.histogram(d6, max_bars=40)
assert h["width"] == 1 and len(h["bins"]) == 7      # values 0..6
close(sum(p for _lo, _hi, p in h["bins"]), 1.0)

# Fewer bars than values -> contiguous bins, no value lost or repeated.
h = ds.histogram(two, max_bars=4)
assert h["width"] >= 4, h["width"]
lo_prev = None
for lo, hi, _p in h["bins"]:
    assert hi >= lo
    if lo_prev is not None:
        assert lo == lo_prev + 1, h["bins"]
    lo_prev = hi
assert h["bins"][0][0] == 0

# A long thin tail is cut off and reported apart, never silently dropped.
tail = [0.0] * 60
tail[1] = 0.9995
tail[55] = 0.0005
h = ds.histogram(tail, max_bars=40, keep=0.999)
assert h["cut"] is not None and h["cut"] < 55, h["cut"]
close(h["cut_mass"], 0.0005, 1e-12)
close(sum(p for _lo, _hi, p in h["bins"]) + h["cut_mass"], 1.0, 1e-12)

# Whole support visible -> nothing is reported as cut.
h = ds.histogram(d6, max_bars=40, keep=0.999)
assert h["cut"] is None and h["cut_mass"] == 0.0

print("dist_stats: OK")
