"""Open the attack window on REAL Tk, with a target the stub cannot judge.

The headless test proves the window stays in step with the session. It
cannot prove the window is legible: column widths, the bold on the
current group, whether a four-group target still fits at a 150% font
scale. Run this on the machine that has a display:

    python3 tests/probe_attack_window.py [font_scale]

What to look at, in order:

  * the CURRENT group is the one in bold, and it moves down the panel
    only when the last model of the one above it has gone;
  * the destroyed models collect at the bottom under 'Destroyed' and
    nothing ever disappears from the panel;
  * Move up/down on the right refuses to put the CHARACTER group first
    and does not lose the selection when it refuses;
  * with the PRECISION weapon armed, 'Aim at character' marks the group
    and pressing it again clears the mark;
  * the two panels still divide sensibly at font scales 100 and 150,
    and the buttons at the bottom keep their captions.
"""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "src"))

import tkinter as tk                                        # noqa: E402
import attack_math as am                                    # noqa: E402
import attack_session as asx                                # noqa: E402
import attack_session_view as asv                           # noqa: E402
import setup_panel                                          # noqa: E402
from unit_model import Weapon                               # noqa: E402


def mech(**kw):
    m = am.WeaponMechanics()
    for k, v in kw.items():
        setattr(m, k, v)
    return m


def weapon(name, a, d, count=1, keywords=None, **mkw):
    return {"weapon": Weapon(name=name, wtype="Ranged", A=a, skill=3,
                             S=8, AP=-1, D=d, count=count,
                             keywords=list(keywords or [])),
            "mech": mech(**mkw)}


# A deliberately awkward target: two bodyguard profiles, a Leader and a
# Support, so the right panel has four groups and the order is a real
# choice rather than a formality.
def models():
    out = [{"key": f"tac{i}", "label": f"Tactical Marine {i}",
            "wounds": 2, "max": 2, "sv": 3, "invuln": None, "fnp": None,
            "character": False, "entry": 0, "scarcity": 6}
           for i in range(6)]
    out.append({"key": "sgt", "label": "Sergeant", "wounds": 2, "max": 2,
                "sv": 3, "invuln": None, "fnp": None, "character": False,
                "entry": 1, "scarcity": 1})
    out.append({"key": "term", "label": "Terminator", "wounds": 3,
                "max": 3, "sv": 2, "invuln": 4, "fnp": None,
                "character": False, "entry": 2, "scarcity": 2})
    out.append({"key": "term2", "label": "Terminator", "wounds": 3,
                "max": 3, "sv": 2, "invuln": 4, "fnp": None,
                "character": False, "entry": 2, "scarcity": 2})
    out.append({"key": "cpt", "label": "Captain (Leader)", "wounds": 5,
                "max": 5, "sv": 2, "invuln": 4, "fnp": None,
                "character": True, "entry": 3, "scarcity": 1})
    out.append({"key": "anc", "label": "Ancient (Support)", "wounds": 4,
                "max": 4, "sv": 3, "invuln": None, "fnp": 5,
                "character": True, "entry": 4, "scarcity": 1})
    return out


WEAPONS = [weapon("Bolt rifle", "2", "1", count=6),
           weapon("Frag grenade launcher", "D6", "1", blast=1),
           weapon("Missile launcher", "1", "D6", count=2),
           weapon("Sniper rifle", "1", "D3", keywords=["PRECISION"]),
           weapon("Plasma incinerator (supercharge)", "2", "2",
                  count=2, hazardous=True)]

SKIPPED = [("Heavy bolter (out of range)", "out of range"),
           ("Chainsword (melee, ranged attack)", "wrong phase")]


def main():
    root = tk.Tk()
    root.title("probe_attack_window")
    scale = float(sys.argv[1]) / 100.0 if len(sys.argv) > 1 else 1.0
    if scale != 1.0:
        # The scale lives in setup_panel, not ui_prefs, and needs the
        # root: the named fonts it rescales are Tk objects.
        setup_panel.apply_font_scale(root, scale)
    session = asx.AttackSession(
        WEAPONS, {"T": 4, "keywords": {"INFANTRY", "IMPERIUM"}}, {},
        models(), random.Random(7))
    asv.AttackSessionWindow(root, session, "Tactical Squad",
                            report, skipped=SKIPPED,
                            attacker_name="Devastator Squad")
    root.mainloop()


def report(rows, hazardous):
    print(f"written back: {len(rows)} models changed, "
          f"{sum(1 for r in rows if r['dead'])} destroyed")
    for r in rows:
        print(f"  {r['key']:8s} -> {r['wounds']} wounds"
              f"{'  (destroyed)' if r['dead'] else ''}")
    print(f"hazardous owed by the attacker: {hazardous}")


if __name__ == "__main__":
    main()
