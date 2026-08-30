"""Indirect Shooting: the spotter needs the attacker stationary too.

10.07 drops the unmodified floor from 6 to 4 only when BOTH hold - a
friendly unit can see the target AND the attacking unit Remained
Stationary. The setup panel keeps them as two separate ticks, because
'stationary' also feeds HEAVY and the ability conditions and coupling
the widgets would make one of them lie; the pairing is applied in the
engine instead, where both programs pass through.

Asserted here: the rule itself, that the analyzer's context really uses
it, that the game assistant builds the same context, and that the panel
marks the tick that is still missing.
"""
import sys

import testpaths                                          # noqa: F401
import analyzer_core as ac
import native_format as nf
import unit_model as um

TOL = 1e-9


# --- the rule ---------------------------------------------------------

TRUTH = {(False, False): False, (True, False): False,
         (False, True): False, (True, True): True}
for (spotter, stationary), expected in TRUTH.items():
    got = ac.spotter_ctx({"spotter": spotter,
                          "attacker_stationary": stationary})
    assert got is expected, (spotter, stationary, got)
# The two really are read as separate keys: 'spotter' alone is what the
# old interface accepted, and it must no longer be enough.
assert ac.spotter_ctx({"spotter": True}) is False
assert ac.spotter_ctx({"attacker_stationary": True}) is False
assert ac.spotter_ctx({}) is False
print("spotter_ctx: both halves, or nothing")


# --- the analyzer's context -------------------------------------------

def model(name, weapons):
    return {"name": name, "model_count": 1, "M": 6, "T": 4, "Sv": 6,
            "W": 1, "LD": 6, "OC": 1, "invuln": None, "fnp": None,
            "keywords": [], "abilities": [], "weapons": weapons}


def unit(name, weapons):
    return {"name": name, "profile_name": name, "points": 0,
            "keywords": [], "abilities": [], "core_abilities": [],
            "faction_abilities": [], "leader_effects": [], "leadership": [],
            "support": [], "models": [model(name + " model", weapons)]}


MORTAR = {"name": "mortar", "type": "Ranged", "RNG": 48, "A": 6, "BS": 3,
          "S": 8, "AP": -6, "D": 1, "count": 1,
          "keywords": ["INDIRECT FIRE"], "abilities": []}

ROSTER = {"format": nf.FORMAT_TAG,
          "armies": [{"name": "Test", "units": [unit("Gunner", [MORTAR]),
                                                unit("Target", [])]}]}
UNITS = {u.name: u for u in um.units_from_native(ROSTER)}


def damage(flags):
    """Mean damage of one indirect weapon under 'flags', through the
    analyzer's own path - so the flags-to-context translation is part of
    what is measured, not just the maths behind it."""
    aview, dview = ac.build_views(UNITS["Gunner"], UNITS["Target"], flags)
    ref = ac.reference_options(dview)[0][1]
    out = ac.run_analysis(aview, dview, ref, flags, "ranged", kills=False)
    return out["totals"]["damage"]["mean"]


BASE = {"indirect": True}
floor6 = damage(BASE)
floor4 = damage(dict(BASE, spotter=True, attacker_stationary=True))
half = damage(dict(BASE, spotter=True))
stationary_only = damage(dict(BASE, attacker_stationary=True))

# 6 attacks, S8 vs T4 (wounds on 2+ = 5/6), AP-6 against Sv6 so nothing
# is saved, D1: the hit stage is the only moving part. Floor 6 lets one
# die in six through, floor 4 lets three.
Q_W = 5 / 6
assert abs(floor6 - 6 * (1 / 6) * Q_W) < TOL, floor6
assert abs(floor4 - 6 * (3 / 6) * Q_W) < TOL, floor4
assert abs(half - floor6) < TOL, \
    "a spotter without a stationary attacker must not relax the floor"
assert abs(stationary_only - floor6) < TOL, \
    "standing still without a spotter must not relax it either"
print(f"analyzer: floor 6 -> {floor6:.2f} dmg, both ticks -> {floor4:.2f}, "
      f"spotter alone -> {half:.2f}")


# --- the game assistant builds the same context -----------------------

import tkstub                                             # noqa: E402

tkstub.install()
sys.path.insert(0, testpaths.REPO_ROOT)

import game_assistant                                     # noqa: E402
import inspect                                            # noqa: E402

# Read rather than run: cmd_attack opens a modal attack window, so
# there is no headless path through it. What is checked is exactly the
# shape of the two versions - the raw flag COPIED into the context (what
# it used to do) against the shared derivation - so the check still
# fails if the old line comes back.
source = inspect.getsource(game_assistant.GameAssistantApp.cmd_attack)
assert "analyzer_core.spotter_ctx(flags)" in source, \
    "the game assistant must derive the spotter the same way"
assert '"indirect", "spotter"' not in source, \
    "the raw spotter flag must not be copied into the context"
print("the game assistant shares the derivation")


# --- the panel marks the tick that is missing -------------------------

import tkinter as tk                                      # noqa: E402
import setup_panel as sp                                  # noqa: E402

root = tk.Tk()
panel = sp.SetupPanel(root)
stationary = panel._flag_checks["attacker_stationary"]


def style_of():
    return stationary.cget("style")


assert style_of() == sp.PLAIN_CHECK_STYLE, style_of()

# The spotter box is dead until indirect fire is chosen.
assert panel._flag_checks["spotter"].cget("state") == tk.DISABLED
panel.flag_vars["indirect"].set(True)
assert panel._flag_checks["spotter"].cget("state") == tk.NORMAL
assert style_of() == sp.PLAIN_CHECK_STYLE, "nothing is wrong yet"

# Spotter alone: the tick it is waiting for is flagged.
panel.flag_vars["spotter"].set(True)
assert style_of() == sp.WARN_CHECK_STYLE, style_of()

# Ticking the other half clears it.
panel.flag_vars["attacker_stationary"].set(True)
assert style_of() == sp.PLAIN_CHECK_STYLE, style_of()

# And un-ticking it brings the warning back.
panel.flag_vars["attacker_stationary"].set(False)
assert style_of() == sp.WARN_CHECK_STYLE, style_of()

# Leaving indirect fire drops the spotter with it, so nothing is left
# flagged for a rule that is no longer in play.
panel.flag_vars["indirect"].set(False)
assert panel.flag_vars["spotter"].get() is False
assert style_of() == sp.PLAIN_CHECK_STYLE, style_of()
print("the panel flags the missing tick, and only while it matters")

# The two ticks are NOT coupled: stationary must stay usable on its own,
# because HEAVY and the ability conditions read it.
panel.flag_vars["attacker_stationary"].set(True)
assert panel.flag_vars["spotter"].get() is False
assert panel.get_flags()["attacker_stationary"] is True
print("stationary stands on its own, as HEAVY needs it to")
print("ALL SPOTTER TESTS PASS")
