"""Monte-Carlo cross-validation helpers shared by the parity tests.

The exact engine (attack_math) produces a full PMF; the dice engine
(attack_resolve) produces samples. These helpers compare the two the way
the maths says they should be compared, instead of with a tolerance
picked by eye:

  * MEAN: the sample mean of n draws has standard error sqrt(Var/n),
    and Var comes from the EXACT PMF - no need to estimate it. The test
    fails when the gap exceeds SIGMA standard errors.
  * DISTRIBUTION: comparing means alone misses errors that preserve the
    mean (a wrong convolution structure, a wrong correlation between the
    mortal and the normal stream). At every support point the empirical
    CDF is a binomial proportion with standard error sqrt(F(1-F)/n), so
    the same SIGMA bound applies point by point - but a distribution has
    dozens of support points, and testing them all at 4 sigma would fire
    on noise sooner or later. The CDF limit is therefore SIGMA corrected
    for the number of points compared (Bonferroni): SIGMA is turned into
    a two-sided p, divided by the number of points, and turned back into
    a z. With ~50 points a nominal 4 sigma becomes about 4.9.

SIGMA is the single knob: raise it to make the suite more forgiving,
lower it to make it stricter. 4 sigma is a two-sided p of about 6e-5 per
check; with a fixed seed the suite stays deterministic and quiet, while
a real divergence of a few per cent shows up immediately.

TRIALS trades runtime for resolution: the detectable difference shrinks
as 1/sqrt(TRIALS), so 4x the trials to halve it.
"""

import math
import random
from collections import Counter
from statistics import NormalDist

import attack_math as am
import attack_resolve as ar

# --- the knobs ---------------------------------------------------------
SIGMA = 4.0            # tolerance, in standard errors
TRIALS = 10000         # dice rolls per configuration
SEED = 20260814        # fixed: the suite must not flicker between runs


def clone_mech(mech):
    """Fresh mechanics copy: the resolver must not mutate a shared one."""
    return mech.copy()


def pmf_moments(pmf):
    """(mean, variance) of an exact PMF given as a list of weights."""
    mean = sum(i * p for i, p in enumerate(pmf))
    second = sum(i * i * p for i, p in enumerate(pmf))
    return mean, max(0.0, second - mean * mean)


def sample_damage(weapon, ref, ctx, mech, trials=None, seed=None,
                  kinds=None):
    """Roll the weapon 'trials' times and return the per-activation total
    damage. 'kinds' restricts the event kinds counted (None = all, i.e.
    normal damage plus mortal wounds, matching analyze_weapon's
    'damage')."""
    trials = TRIALS if trials is None else trials
    rng = random.Random(SEED if seed is None else seed)
    out = []
    for _ in range(trials):
        res = ar.resolve_weapon(weapon, ref, ctx, clone_mech(mech), rng)
        out.append(sum(e["amount"] for e in res["events"]
                       if kinds is None or e["kind"] in kinds))
    return out


def mean_deviation(pmf, samples):
    """(z, exact_mean, sample_mean): how many standard errors apart the
    two means are. The standard error uses the EXACT variance, so it does
    not itself depend on the sample."""
    n = len(samples)
    exact_mean, var = pmf_moments(pmf)
    got = sum(samples) / n
    se = math.sqrt(var / n)
    if se <= 0.0:                     # deterministic outcome
        return (0.0 if abs(got - exact_mean) < 1e-12 else float("inf"),
                exact_mean, got)
    return abs(got - exact_mean) / se, exact_mean, got


def family_limit(sigma, comparisons: int) -> float:
    """SIGMA corrected for testing 'comparisons' points at once, so that
    the chance of the whole check firing on noise stays at the level
    SIGMA names for a single check."""
    comparisons = max(1, int(comparisons))
    if comparisons == 1:
        return sigma
    p_single = 2.0 * (1.0 - NormalDist().cdf(sigma))
    p_each = max(p_single / comparisons, 1e-15)
    return NormalDist().inv_cdf(1.0 - p_each / 2.0)


def cdf_deviation(pmf, samples):
    """(z, value, points): the worst point-by-point disagreement between
    the exact CDF and the empirical one, in standard errors, and how many
    points were compared. Catches errors that leave the mean intact but
    move probability mass around."""
    n = len(samples)
    counts = Counter(samples)
    top = max(len(pmf) - 1, max(samples) if samples else 0)
    cum_exact = cum_obs = 0.0
    worst_z, worst_v = 0.0, 0
    for v in range(top + 1):
        cum_exact += pmf[v] if v < len(pmf) else 0.0
        cum_obs += counts.get(v, 0) / n
        # Binomial standard error, floored so that the tails (where
        # F(1-F) collapses to 0) stay comparable instead of dividing by
        # something arbitrarily small.
        se = math.sqrt(max(cum_exact * (1.0 - cum_exact), 1.0 / n) / n)
        z = abs(cum_obs - cum_exact) / se
        if z > worst_z:
            worst_z, worst_v = z, v
    return worst_z, worst_v, top + 1


def parity_report(name, pmf, samples, sigma=None):
    """(ok, message) for one configuration: both the mean and the whole
    distribution must sit within 'sigma' standard errors."""
    sigma = SIGMA if sigma is None else sigma
    z_mean, exact_mean, got = mean_deviation(pmf, samples)
    z_cdf, at, points = cdf_deviation(pmf, samples)
    limit = family_limit(sigma, points)
    ok = z_mean <= sigma and z_cdf <= limit
    msg = (f"{name:28s} exact={exact_mean:8.4f} mc={got:8.4f} "
           f"z(mean)={z_mean:5.2f}/{sigma:.1f} "
           f"z(cdf)={z_cdf:5.2f}/{limit:.1f}@{at}")
    if not ok:
        msg += "   <== PARITY BROKEN"
    return ok, msg


def check_weapon(name, weapon, ref, ctx, mech, sigma=None, trials=None,
                 seed=None):
    """Run one exact-vs-dice comparison end to end. Returns (ok, msg)."""
    exact = am.analyze_weapon(weapon, ref, ctx, clone_mech(mech))
    samples = sample_damage(weapon, ref, ctx, mech, trials=trials,
                            seed=seed)
    return parity_report(name, exact["damage_pmf"], samples, sigma)
