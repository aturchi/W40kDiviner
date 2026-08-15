"""Roster entries with MORE than one helper in a slot.

A slot ('leader' / 'support') used to hold at most one unit dict. It now
holds a list, kept in a compact form (None / one dict / a list) so that
older session files and older code keep working. What must hold:

  * label, points and free-slot counts see every helper;
  * the global model indexing that the tables use gives each helper its
    own segment, so masking a model of the second leader does not touch
    the first;
  * build_entry_unit attaches them in order, and stops at capacity;
  * ArmyJoinState joins several at once and gives them all back on
    unjoin.

Headless (no tkinter): this is the logic under the join dialogs.
"""
import copy
import json

import testpaths                      # sets up sys.path to the engine src/
import leader_core as lc
import unit_model as um

data = json.load(open(testpaths.roster("space-marines.json")))
units = um.units_from_native(data)
leaders, rest = lc.split_leaders(units)
supports, others = lc.split_supports(rest)

# The roster has a single Leader, and the rules forbid attaching
# duplicates, so clone it under another name and open a second slot on a
# unit it can lead - exactly what an 'attachmentSlots' ability does.
squad_u = next(u for u in others if any(u.can_attach(l) for l in leaders))
raw = copy.deepcopy(data)
squad_d = next(u for a in raw["armies"] for u in a["units"]
               if u["name"] == squad_u.name)
squad_d["leader_slots"] = 2
leader_d = next(u for a in raw["armies"] for u in a["units"]
                if u["name"] == next(l.name for l in leaders
                                     if squad_u.can_attach(l)))
clone_d = copy.deepcopy(leader_d)
clone_d["name"] = leader_d["name"] + " (second)"
raw["armies"][0]["units"].append(clone_d)

# --- 1. free slots and the compact storage of a slot -------------------
entry = lc.make_entry(squad_d)
assert lc.free_slots(entry, "leader") == 2, "the datasheet field must count"
assert lc.free_slots(entry, "support") == 1, "the other slot is untouched"
assert lc.helpers(entry, "leader") == []

one = lc.set_helpers(entry, "leader", [leader_d])
assert one["leader"] == leader_d, "a single helper is stored as a bare dict"
assert lc.helpers(one, "leader") == [leader_d]
assert lc.free_slots(one, "leader") == 1

two = lc.set_helpers(entry, "leader", [leader_d, clone_d])
assert isinstance(two["leader"], list), "several helpers are stored as a list"
assert lc.free_slots(two, "leader") == 0, "no room left"
assert lc.set_helpers(two, "leader", [])["leader"] is None
print("a slot stores none / one / several helpers and counts what is free")

# --- 2. label, points, models -----------------------------------------
# Several helpers of a kind are summarised, so the label stays short.
label = lc.entry_label(two)
assert label == f"{squad_d['name']} + 2 leaders [JOINED]", label
one_label = lc.entry_label(one)
assert one_label == f"{squad_d['name']} + {leader_d['name']} [JOINED]", \
    one_label
assert lc.entry_label(lc.make_entry(squad_d)) == squad_d["name"]
assert lc.entry_points(two) == (squad_d.get("points", 0)
                                + 2 * leader_d.get("points", 0))
n_squad = len(squad_d["models"])
n_leader = len(leader_d["models"])
assert len(lc.entry_models(two)) == n_squad + 2 * n_leader
print("label, points and model list cover every helper")

# --- 3. each helper gets its own segment of the global indexing --------
# Mask every model copy of the SECOND leader only; the first must
# survive. masked_copies is {global_model_index: copies_removed}.
second_start = n_squad + n_leader
masked = {second_start + i: m["model_count"]
          for i, m in enumerate(clone_d["models"])}
built = lc.build_entry_unit(two, masked, set(), {})
names = [m.name for m in built.models()]
assert len(built.attached_leaders) == 1, \
    "masking the second leader must not remove the first"
assert sum(m.model_count for m in built.bodyguard_models()) \
    == sum(m.model_count for m in squad_u.models())
# Nothing masked: both leaders attach, in order.
full = lc.build_entry_unit(two, {}, set(), {})
assert [u.name for u in full.attached_leaders] == [leader_d["name"],
                                                   clone_d["name"]]
assert sum(m.model_count for m in full.models()) \
    > sum(m.model_count for m in built.models()), (names,)
print("global model indices give each helper its own segment")

# --- 4. capacity is enforced when the unit is rebuilt ------------------
one_slot = lc.set_helpers(lc.make_entry(copy.deepcopy(squad_d)), "leader",
                          [leader_d, clone_d])
one_slot["unit"]["leader_slots"] = 1
capped = lc.build_entry_unit(one_slot, {}, set(), {})
assert len(capped.attached_leaders) == 1, \
    "the second leader must be refused when there is only one slot"
print("build_entry_unit stops at the unit's capacity")

# --- 5. ArmyJoinState: join several at once, unjoin gives them back ----
pool = [u for a in raw["armies"] for u in a["units"]]
st = lc.ArmyJoinState(pool)
target = next(u for u in st.others if u["name"] == squad_d["name"])
lds = [u for u in st.leaders
       if u["name"] in (leader_d["name"], clone_d["name"])]
assert len(lds) == 2
before = len(st.leaders)
st.join_combo(target, lds, None)
assert len(st.joined) == 1
assert len(lc.helpers(st.joined[0], "leader")) == 2
assert len(st.leaders) == before - 2, "both leaders left their pool"
assert st.free_slots(0, "leader") == 0
st.unjoin(0)
assert len(st.leaders) == before and not st.joined, \
    "unjoin must return every part to its pool"

# and one at a time, through add_to_joined
st = lc.ArmyJoinState(pool)
target = next(u for u in st.others if u["name"] == squad_d["name"])
first = next(u for u in st.leaders if u["name"] == leader_d["name"])
st.join_combo(target, first, None)
assert st.free_slots(0, "leader") == 1, "one slot still free"
second = next(u for u in st.leaders if u["name"] == clone_d["name"])
st.add_to_joined(0, second, "leader")
assert len(lc.helpers(st.joined[0], "leader")) == 2
assert st.free_slots(0, "leader") == 0
print("ArmyJoinState fills a slot in one go or one helper at a time")

# --- 6. attach_all: what the Join buttons actually run -----------------
# This is the pure half of the analyzer's cmd_join and of the dialog's
# _join: attach what fits, and say why the rest did not.
u2s = um.units_from_native(raw)
l2s, r2 = lc.split_leaders(u2s)
s2s, o2s = lc.split_supports(r2)
squad = next(u for u in o2s if u.name == squad_d["name"])
ld_a = next(l for l in l2s if l.name == leader_d["name"])
ld_b = next(l for l in l2s if l.name == clone_d["name"])
other = next(u for u in o2s if u.name != squad.name
             and not u.can_attach(ld_a))

# both leaders in one go
combined, taken, refused = lc.attach_all(squad, [("leader", ld_a),
                                                 ("leader", ld_b)])
assert len(taken) == 2 and not refused, (taken, refused)
assert len(combined.attached_leaders) == 2
assert combined.name == f"{squad.name} + 2 leaders", combined.name

# one at a time: the second lands on the already-combined unit
step, taken, refused = lc.attach_all(squad, [("leader", ld_a)])
assert len(taken) == 1 and not refused
step, taken, refused = lc.attach_all(step, [("leader", ld_b)])
assert len(taken) == 1 and not refused, refused
assert len(step.attached_leaders) == 2
assert step.name == combined.name, (step.name, combined.name)

# a third leader, a duplicate and an incompatible one: each is refused
# with its own reason, and nothing is attached
_x, taken, refused = lc.attach_all(step, [("leader", ld_a)])
assert not taken and "already attached" in refused[0][1], refused
_x, taken, refused = lc.attach_all(squad, [("leader", ld_a),
                                           ("leader", ld_a)])
assert len(taken) == 1 and "already attached" in refused[0][1], refused
_x, taken, refused = lc.attach_all(other, [("leader", ld_a)])
assert not taken and "cannot leader" in refused[0][1], refused
print("attach_all takes what fits and explains what it refuses")

print("ALL MULTI-SLOT JOIN TESTS PASS")
