"""Global rules configuration.

WH40k 11th edition defaults:

- CAP_ROLL_MOD: net modifier cap on HIT and WOUND rolls (+/-1 RAW).
  Save rolls are exempt: AP and cover stack without cap (an impossible
  save simply fails; a natural 1 always fails).
- CAP_REROLLS: maximum number of re-rolls per die (1 in 11th edition;
  0 disables every re-roll, including weapon keywords like
  TWIN-LINKED; future rules may raise it).

Characteristic modifiers have NO cap (11th ed. RAW); they are floored
instead: M and OC cannot drop below 0, every other characteristic not
below 1, and AP (datasheet convention: negative or zero) cannot rise
above 0. See CHARACTERISTIC_FLOORS.
"""

CAP_ROLL_MOD = 1
CAP_REROLLS = 1

# Minimum value per characteristic after modification; attributes not
# listed floor at 1. AP is special-cased (ceiling 0) by the engine.
CHARACTERISTIC_FLOORS = {"M": 0, "OC": 0}


def characteristic_floor(attr: str) -> int:
    """The minimum legal value for characteristic attr after modifiers (per the rules config), used to cap reductions."""
    return CHARACTERISTIC_FLOORS.get(attr, 1)


def set_caps(roll="unchanged", rerolls="unchanged") -> None:
    """Override the caps (use None for 'no cap' on the roll modifier;
    the re-roll cap is an integer >= 0)."""
    global CAP_ROLL_MOD, CAP_REROLLS
    if roll != "unchanged":
        CAP_ROLL_MOD = roll
    if rerolls != "unchanged":
        CAP_REROLLS = max(0, int(rerolls))
