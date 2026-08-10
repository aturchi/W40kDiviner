"""Characteristics with dice-notation support.

A Characteristic is immutable and wraps one of:
- None        -> unknown / not applicable (M, LD, OC, RNG for now)
- int         -> fixed value
- "XdY+Z"     -> dice notation (X >= 1 optional, Z optional, +/- allowed)

API:
  value(rng=None) -> int|None   roll the dice (explicit Random for
                                 reproducibility) or return the int
  value_avg()     -> float|None  expected value: X*(Y+1)/2 + Z
  with_delta(d)   -> Characteristic   new object with flat part += d
"""

import random
import re

_DICE_RE = re.compile(r"^\s*(\d*)\s*[dD]\s*(\d+)\s*(?:([+-])\s*(\d+))?\s*$")
_GLOBAL_RNG = random.Random()


class Characteristic:
    """An immutable numeric characteristic that may be an int, a dice string like "d6" / "2d3+1", or None (unknown/not applicable). See the module docstring for the API."""
    __slots__ = ("count", "sides", "flat")

    def __init__(self, value):
        # Normal form: count dice with 'sides' faces, plus 'flat'.
        # Fixed ints are count=0; None is sides=None (not applicable).
        if value is None:
            self.count, self.sides, self.flat = 0, None, 0
            return
        if isinstance(value, bool):
            raise TypeError("Characteristic cannot be a bool")
        if isinstance(value, int):
            self.count, self.sides, self.flat = 0, 0, value
            return
        if isinstance(value, str):
            s = value.strip()
            if s in ("", "-", "N/A"):
                # Not applicable (e.g. Torrent weapons have no BS)
                self.count, self.sides, self.flat = 0, None, 0
                return
            if re.fullmatch(r"[+-]?\d+", s):
                self.count, self.sides, self.flat = 0, 0, int(s)
                return
            m = _DICE_RE.match(s)
            if m:
                self.count = int(m.group(1) or 1)
                self.sides = int(m.group(2))
                z = int(m.group(4) or 0)
                self.flat = -z if m.group(3) == "-" else z
                return
        raise ValueError(f"Invalid characteristic value: {value!r}")

    # ---------- queries ----------

    def is_none(self) -> bool:
        """True if this characteristic is unknown / not applicable."""
        return self.sides is None

    def is_dice(self) -> bool:
        """True if this characteristic is a dice expression."""
        return bool(self.count)

    def value(self, rng: random.Random = None):
        """Roll (if dice) and return an int; None if not applicable."""
        if self.is_none():
            return None
        if not self.count:
            return self.flat
        rng = rng or _GLOBAL_RNG
        return sum(rng.randint(1, self.sides)
                   for _ in range(self.count)) + self.flat

    def value_avg(self):
        """Expected value: X*(Y+1)/2 + Z; None if not applicable."""
        if self.is_none():
            return None
        return self.count * (self.sides + 1) / 2 + self.flat

    # ---------- derivation ----------

    def with_delta(self, delta: int) -> "Characteristic":
        """New Characteristic with the flat part shifted by delta.
        Deltas on a None characteristic are ignored (stays None)."""
        if self.is_none() or not delta:
            return self
        out = Characteristic(0)
        out.count, out.sides, out.flat = self.count, self.sides, self.flat + delta
        return out

    def __repr__(self):
        if self.is_none():
            return "Characteristic(None)"
        if not self.count:
            return f"Characteristic({self.flat})"
        z = f"{self.flat:+d}" if self.flat else ""
        return f"Characteristic('{self.count}d{self.sides}{z}')"
