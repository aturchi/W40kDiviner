"""Global rules configuration.

WH40k 11th edition defaults:

- CAP_ROLL_MOD: net modifier cap on the HIT and WOUND rolls (+/-1 RAW).
  No other roll is capped: saving throws, invulnerable saves and Feel No
  Pain take their modifiers in full (an impossible save simply fails; an
  unmodified 1 always fails).
- CAP_REROLLS: maximum number of re-rolls per die (1 in 11th edition;
  0 disables every re-roll, including weapon keywords like
  TWIN-LINKED; future rules may raise it).
- BATTLE_ROUND_RANGE / BATTLE_ROUND_DEFAULT: a matched-play battle lasts
  five battle rounds, and the setup panel offers exactly those. The
  number is context, not a cap - it only decides whether a battleRound
  condition holds - but it belongs here rather than in the widget,
  because a format that ran longer would change the rules and not the
  interface.

CHARACTERISTICS ARE NOT CAPPED. They have ABSOLUTE LIMITS instead, and
the two things are independent - which matters, because in 11th edition
the Benefit of Cover is a -1 to the BS characteristic, not to the hit
roll, so it stacks with a -1 to-hit ability for an effective -2. The
limits (see CHARACTERISTIC_LIMITS):

  BS / WS   never better than 2+, never worse than 6+
  Sv        never better than 2+ (an invulnerable save likewise)
  AP        never worse than 0 (datasheet convention: negative is better)
  M / OC    never below 0; every other characteristic never below 1

The BS/WS and save limits are largely implied by "an unmodified 1 always
fails, an unmodified 6 always hits", but only when nothing else touches
the die: clamp the characteristic FIRST and a further roll modifier then
applies on top of the clamped value, which is what the rules say and
what the helpers below enforce.
"""

CAP_ROLL_MOD = 1
CAP_REROLLS = 1

# Battle rounds in a matched-play game, and the one a fresh analysis
# assumes.
BATTLE_ROUND_RANGE = (1, 5)
BATTLE_ROUND_DEFAULT = 1

# Absolute limits per characteristic, as (best, worst) in RULES terms,
# expressed as (lo, hi) numeric bounds; None = unbounded on that side.
# A skill or a save is "better" when the number is LOWER, so their best
# value is the lower bound. AP is bounded above at 0.
CHARACTERISTIC_LIMITS = {
    "BS": (2, 6), "WS": (2, 6), "_skill": (2, 6),
    "Sv": (2, None), "invuln": (2, None),
    "AP": (None, 0),
    "M": (0, None), "OC": (0, None),
}
_DEFAULT_LIMITS = (1, None)          # every other characteristic


def characteristic_limits(attr: str):
    """(lo, hi) absolute bounds for characteristic attr; None = open."""
    return CHARACTERISTIC_LIMITS.get(attr, _DEFAULT_LIMITS)


def clamp_characteristic(attr: str, value: int) -> int:
    """Clamp a characteristic value to its absolute limits."""
    lo, hi = characteristic_limits(attr)
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value


def characteristic_floor(attr: str) -> int:
    """The minimum legal value for characteristic attr after modifiers."""
    lo, _hi = characteristic_limits(attr)
    return 1 if lo is None else lo


def cap_roll(mod: int) -> int:
    """Clamp a net HIT or WOUND roll modifier to +/-CAP_ROLL_MOD
    (None = no cap). Saves, invulns and FNP are NOT capped."""
    cap = CAP_ROLL_MOD
    return mod if cap is None else max(-cap, min(cap, mod))


def set_caps(roll="unchanged", rerolls="unchanged") -> None:
    """Override the caps (use None for 'no cap' on the hit/wound roll
    modifier; the re-roll cap is an integer >= 0)."""
    global CAP_ROLL_MOD, CAP_REROLLS
    if roll != "unchanged":
        CAP_ROLL_MOD = roll
    if rerolls != "unchanged":
        CAP_REROLLS = max(0, int(rerolls))
