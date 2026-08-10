"""Cross-engine consistency checks (additive; imports only).

The exact analytic engine (attack_math.analyze_weapon) and the dice
resolver (attack_resolve.resolve_weapon) implement the same 11th-ed
rules through shared primitives but along independent code paths. This
library calls BOTH on identical inputs and verifies that the Monte
Carlo mean of the resolver agrees with the exact mean within a
statistical tolerance. It modifies nothing: a regression in either
engine surfaces as a failing case here.

Use:
    from cross_check import run_suite
    report = run_suite()           # list of CaseResult
    assert all(r.ok for r in report)

or from the command line:
    python3 src/cross_check.py [N]      # N = samples per case
"""

import random
import statistics

import attack_math as am
import attack_resolve as ar
from unit_model import Weapon


# Each case: (name, weapon_kwargs, keywords, defender_ref, ctx).
# Kept small and explicit so a failure points straight at the rule.
_DEF_TOUGH = {"T": 4, "Sv": 3, "W": 12, "invuln": None, "fnp": None,
              "models": 1, "model_count": 1, "keywords": set(),
              "cover": False}
_DEF_HORDE = {"T": 4, "Sv": 5, "W": 1, "invuln": None, "fnp": 6,
              "models": 11, "model_count": 11, "keywords": set(),
              "cover": False}
_DEF_VEH = {"T": 9, "Sv": 2, "W": 16, "invuln": 5, "fnp": None,
            "models": 1, "model_count": 1, "keywords": {"VEHICLE"},
            "cover": True}

CASES = [
    ("plain", dict(name="P", wtype="Ranged", A=2, skill=3, S=4, AP=0, D=1),
     [], _DEF_TOUGH, {}),
    ("ap_and_cover",
     dict(name="AP", wtype="Ranged", A=2, skill=3, S=5, AP=-2, D=2),
     [], _DEF_VEH, {"cover": True}),
    ("sustained_lethal",
     dict(name="SL", wtype="Ranged", A=3, skill=3, S=8, AP=-1, D=1),
     ["SUSTAINED HITS 2", "LETHAL HITS"], _DEF_TOUGH, {}),
    ("devastating",
     dict(name="DW", wtype="Ranged", A=2, skill=2, S=6, AP=0, D="D3"),
     ["DEVASTATING WOUNDS"], _DEF_VEH, {}),
    ("twin_linked_reroll",
     dict(name="TL", wtype="Ranged", A=6, skill=4, S=4, AP=0, D=1),
     ["TWIN-LINKED"], _DEF_TOUGH, {}),
    ("rapid_melta_half",
     dict(name="RM", wtype="Ranged", A=1, skill=3, S=9, AP=-4, D="D6"),
     ["RAPID FIRE 2", "MELTA 2"], _DEF_VEH, {"half_range": True}),
    ("blast_vs_horde",
     dict(name="BL", wtype="Ranged", A="D6", skill=3, S=5, AP=-1, D=1),
     ["BLAST"], _DEF_HORDE, {}),
    ("heavy_stationary",
     dict(name="HV", wtype="Ranged", A=4, skill=4, S=6, AP=-1, D=2),
     ["HEAVY"], _DEF_TOUGH, {"stationary": True}),
    ("lance_charge_melee",
     dict(name="LC", wtype="Melee", A=4, skill=3, S=7, AP=-1, D=2),
     ["LANCE"], _DEF_VEH, {"charged": True}),
    ("anti_vehicle",
     dict(name="AV", wtype="Ranged", A=3, skill=3, S=6, AP=-2, D=2),
     ["ANTI-VEHICLE 4+"], _DEF_VEH, {}),
    ("fnp_horde",
     dict(name="FN", wtype="Ranged", A="D6", skill=3, S=4, AP=0, D=1),
     ["DEVASTATING WOUNDS"], _DEF_HORDE, {}),
    ("cocktail",
     dict(name="CK", wtype="Ranged", A="D3", skill=3, S=9, AP=-2,
          D="D6", count=2),
     ["SUSTAINED HITS 1", "LETHAL HITS", "DEVASTATING WOUNDS",
      "TWIN-LINKED", "RAPID FIRE 2", "MELTA 2", "BLAST", "HEAVY",
      "LANCE", "ANTI-VEHICLE 4+"], _DEF_VEH,
     {"half_range": True, "stationary": True, "charged": True,
      "cover": True}),
]


class CaseResult:
    """Result of one cross-check case: the two engines' outputs and whether they agree, for the regression cross-checker."""
    def __init__(self, name, exact_mean, mc_mean, sem, z, ok,
                 exact_med, mc_med, warnings):
        self.name = name
        self.exact_mean = exact_mean
        self.mc_mean = mc_mean
        self.sem = sem
        self.z = z
        self.ok = ok
        self.exact_med = exact_med
        self.mc_med = mc_med
        self.warnings = warnings

    def __repr__(self):
        flag = "OK " if self.ok else "*** "
        return (f"{flag}{self.name:<20} exact {self.exact_mean:8.4f} | "
                f"MC {self.mc_mean:8.4f} +- {self.sem:.4f} (z={self.z:4.2f}) "
                f"| med {self.exact_med}/{self.mc_med}")


def _mech(keywords):
    m = am.WeaponMechanics()
    am.parse_weapon_keywords(keywords, m)
    return m


def run_case(name, wkwargs, keywords, defender_ref, ctx,
             n=120000, seed=20240601, z_tol=4.0, metric="damage"):
    """Run one case on both engines. The resolver sums event amounts
    per attack sequence; the exact engine's '<metric>' mean is the
    reference. z is the standardised gap; ok when |z| < z_tol and the
    medians differ by at most 1."""
    weapon = Weapon(**wkwargs)
    exact = am.analyze_weapon(weapon, defender_ref, ctx, _mech(keywords))
    exact_mean = exact[metric]["mean"]
    exact_med = exact[metric]["median"]

    rng = random.Random(seed)
    mech = _mech(keywords)
    totals = []
    for _ in range(n):
        res = ar.resolve_weapon(weapon, defender_ref, ctx, mech, rng)
        if metric == "damage_net":
            w_ref = defender_ref.get("W") or 1
            totals.append(sum(min(e["amount"], w_ref)
                              for e in res["events"]))
        else:
            totals.append(sum(e["amount"] for e in res["events"]))
    mc_mean = sum(totals) / n
    sem = statistics.pstdev(totals) / n ** 0.5 if n > 1 else 0.0
    z = abs(mc_mean - exact_mean) / sem if sem > 0 else 0.0
    mc_med = statistics.median(totals)
    ok = (z < z_tol) and (abs(exact_med - mc_med) <= 1)
    return CaseResult(name, exact_mean, mc_mean, sem, z, ok,
                      exact_med, mc_med, list(exact["warnings"]))


def run_suite(n=120000, seed=20240601, z_tol=4.0):
    """Run every registered case; returns a list of CaseResult."""
    return [run_case(name, wk, kw, dref, ctx, n=n, seed=seed,
                     z_tol=z_tol)
            for (name, wk, kw, dref, ctx) in CASES]


if __name__ == "__main__":
    import sys
    samples = int(sys.argv[1]) if len(sys.argv) > 1 else 120000
    results = run_suite(n=samples)
    for r in results:
        print(r)
    n_fail = sum(0 if r.ok else 1 for r in results)
    print(f"\n{len(results) - n_fail}/{len(results)} cases consistent",
          f"({n_fail} FAILED)" if n_fail else "(all OK)")
    sys.exit(1 if n_fail else 0)
