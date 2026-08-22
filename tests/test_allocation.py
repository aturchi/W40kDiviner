"""Assisted wound allocation.

The arithmetic behind the "Apply to defender" dialog. What is checked
here is that it follows the SAME allocation rules the estimate is built
on (kill_chain), because a program that predicts four dead models and
then removes five is worse than one that predicts nothing:

  * one event at a time, capped by the wounds of the model it lands on,
    with the excess wasted - three attacks of 2 are not one of 6;
  * a model that has already lost wounds takes damage first;
  * devastating wounds do not spill, real mortal wounds do and are
    applied last, one point at a time.

The last check is the strong one: for a squad of identical models with
no mortal wounds in play, the number of models this module removes must
equal the number kill_chain counts from the same events.

No tkinter, no external data.
"""
import testpaths                      # sets up sys.path to the engine src/
import allocation as al
import kill_chain


class W:
    """The little of a weapon the allocator reads."""

    def __init__(self, name, keywords=()):
        self.name, self.keywords = name, list(keywords)


def copies(n, wounds, w=2, first=None):
    """n model copies of 'w' wounds each, all at 'wounds' except the
    first, which is set to 'first' when given."""
    out = [{"iid": f"c{i}", "label": f"Model {i + 1}", "wounds": wounds,
            "max": w} for i in range(n)]
    if first is not None:
        out[0]["wounds"] = first
    return out


def res(events, attacks=0):
    return {"attacks": attacks, "events": events, "self_damage": 0,
            "warnings": []}


def dmg(*amounts):
    return [{"kind": "damage", "amount": a} for a in amounts]


# --- 1. reading the events off a resolution ---------------------------

events = al.events_from_results([
    (W("rifle"), False, res(dmg(2, 2) + [
        {"kind": "mortal", "amount": 3, "spills": False},      # devastating
        {"kind": "mortal", "amount": 2, "spills": True},       # real MW
        {"kind": "damage", "amount": 0}])),                    # dropped
    (W("sniper", ["Precision"]), False, res(dmg(1)))])
assert [e["amount"] for e in events] == [2, 2, 3, 2, 1], events
assert [e["spills"] for e in events] == [False, False, False, True, False]
assert events[-1]["precision"] and not events[0]["precision"]
t = al.totals(events)
assert (t["plain"], t["plain_events"]) == (5, 3)
assert (t["devastating"], t["dev_events"]) == (3, 1)
assert t["spill"] == 2 and t["precision"] == 1 and t["damage"] == 10
print("events read off the resolution, devastating kept apart from mortal")

# --- 2. one event at a time, and the excess is wasted -----------------

plan = al.allocate(copies(3, 2), al.events_from_results(
    [(W("gun"), False, res(dmg(2, 2, 2)))]))
assert [s["after"] for s in plan["state"]] == [0, 0, 0]
assert plan["killed"] == 3 and plan["wasted"] == 0

# the same six damage in two events of 3: two models die, 2 is wasted
plan = al.allocate(copies(3, 2), al.events_from_results(
    [(W("gun"), False, res(dmg(3, 3)))]))
assert [s["after"] for s in plan["state"]] == [0, 0, 2], plan["state"]
assert plan["killed"] == 2 and plan["wasted"] == 2, plan
print("damage is capped per event, and the excess is wasted")

# --- 3. the wounded model goes first ----------------------------------

three = [{"iid": "c0", "label": "A", "wounds": 2, "max": 2},
         {"iid": "c1", "label": "B", "wounds": 1, "max": 2},
         {"iid": "c2", "label": "C", "wounds": 2, "max": 2}]
plan = al.allocate(three, al.events_from_results(
    [(W("gun"), False, res(dmg(1)))]))
assert [s["after"] for s in plan["state"]] == [2, 0, 2], plan["state"]
assert plan["state"][1]["dead"]
print("the model that has already lost wounds is allocated to first")

# --- 4. the order is the player's ------------------------------------

three = copies(3, 2)
plan = al.allocate(three, al.events_from_results(
    [(W("gun"), False, res(dmg(2)))]), order=[2, 1, 0])
assert [s["after"] for s in plan["state"]] == [2, 2, 0], plan["state"]
# ...but it cannot override the wounded-first rule
hurt = [{"iid": "c0", "label": "A", "wounds": 1, "max": 2},
        {"iid": "c1", "label": "B", "wounds": 2, "max": 2}]
plan = al.allocate(hurt, al.events_from_results(
    [(W("gun"), False, res(dmg(1)))]), order=[1, 0])
assert [s["after"] for s in plan["state"]] == [0, 2], plan["state"]
print("the order is the player's, the wounded-first rule is not")

# --- 5. spilling mortal wounds go last, and do spill ------------------

mixed = [(W("gun"), False, res(dmg(1) + [
    {"kind": "mortal", "amount": 4, "spills": True}]))]
plan = al.allocate(copies(3, 2), al.events_from_results(mixed))
# 1 damage on model 1, then the pool of 4: 1 finishes it, 2 kills the
# second, 1 wounds the third. Nothing wasted.
assert [s["after"] for s in plan["state"]] == [0, 0, 1], plan["state"]
assert plan["wasted"] == 0 and plan["killed"] == 2

# a devastating wound of the same size wastes instead of spilling
dev = [(W("gun"), False, res([{"kind": "mortal", "amount": 4,
                              "spills": False}]))]
plan = al.allocate(copies(3, 2), al.events_from_results(dev))
assert [s["after"] for s in plan["state"]] == [0, 2, 2], plan["state"]
assert plan["wasted"] == 2, plan
print("spilling mortal wounds pass over, devastating ones do not")

# --- 6. more damage than models ---------------------------------------

plan = al.allocate(copies(2, 2), al.events_from_results(
    [(W("gun"), False, res(dmg(2, 2, 2) + [
        {"kind": "mortal", "amount": 3, "spills": True}]))]))
assert plan["killed"] == 2 and plan["leftover"] == 5, plan
assert any("destroyed" in h for h in al.hints(
    al.events_from_results([(W("g"), False, res(dmg(9)))]),
    copies(1, 2), plan))
print("leftover damage on a wiped unit is reported, not spread")

# --- 7. the hints name what the player has to decide ------------------

hints = al.hints(events, copies(2, 2, first=1), al.allocate(
    copies(2, 2, first=1), events))
joined = " ".join(hints)
assert "Already wounded" in joined and "Model 1" in joined
assert "DEVASTATING" in joined and "spill" in joined
assert "PRECISION" in joined and "champion" in joined
print("hints cover the wounded model, devastating, spill and precision")

# --- 8. same rules as the estimate ------------------------------------
# Five events of 2 damage into six one-wound models: whatever the two
# modules do, they must remove the same number of models.

for w, n, amounts in ((1, 6, (2, 2, 2, 2, 2)),
                      (2, 4, (1, 3, 2, 2)),
                      (3, 3, (4, 1, 1, 5)),
                      (2, 5, (2, 2, 1, 1, 2, 2))):
    plan = al.allocate(copies(n, w, w=w), al.events_from_results(
        [(W("gun"), False, res(dmg(*amounts)))]))
    total = n * w
    for a in amounts:                      # kill_chain's own arithmetic
        total -= min(a, kill_chain.front_wounds(total, w))
    assert plan["killed"] == kill_chain.kills_from_total(total, w, n), \
        (w, n, amounts, plan["killed"])
print("models removed agree with the kill-chain estimate")

print("OK: allocation")
