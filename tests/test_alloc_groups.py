"""alloc_groups: the 11th ed. Save Rolls grouping (Core Rules 05.03),
the allocation order and its three constraints, and the state machine
that decides which model an attack is allocated to (05.04.01).

Pure engine-side logic: no Tkinter, no roster files, no dice.
"""
import testpaths                      # sets up sys.path to the engine src/
import alloc_groups as ag


def model(key, label, wounds, cap=1, sv=3, invuln=None, fnp=None,
          character=False, entry=0, scarcity=1):
    return {"key": key, "label": label, "wounds": wounds, "max": cap,
            "sv": sv, "invuln": invuln, "fnp": fnp,
            "character": character, "entry": entry, "scarcity": scarcity}


def squad(n, entry=0, sv=3, cap=2, wounds=None, prefix="Body",
          character=False):
    """n identical copies of one model group (scarcity = n)."""
    return [model(f"{prefix}{i}", f"{prefix} {i}",
                  cap if wounds is None else wounds, cap=cap, sv=sv,
                  entry=entry, scarcity=n, character=character)
            for i in range(n)]


# --- 1. grouping: same W/Sv/InSv merge, every CHARACTER is alone ------

bodies = squad(4, entry=0, sv=3, cap=2)
sergeant = [model("Sgt", "Sergeant", 2, cap=2, sv=3, entry=1, scarcity=1)]
captain = [model("Cpt", "Captain", 4, cap=4, sv=2, invuln=4,
                 character=True, entry=2, scarcity=1)]
apothecary = [model("Apo", "Apothecary", 3, cap=3, sv=3,
                    character=True, entry=3, scarcity=1)]
mixed = bodies + sergeant + captain + apothecary

groups = ag.build_groups(mixed)
assert len(groups) == 3, [g["label"] for g in groups]
# The sergeant shares W2/Sv3+ with the bodies, so it is NOT a group of
# its own: only a differing characteristic (or CHARACTER) splits one.
assert len(groups[0]["members"]) == 5, groups[0]
assert [g["character"] for g in groups] == [False, True, True]
assert groups[1]["ref"] == {"Sv": 2, "invuln": 4, "fnp": None, "W": 4}

# A different Sv does split the group.
shielded = bodies + [model("Shd", "Shield body", 2, cap=2, sv=2,
                           entry=1, scarcity=1)]
assert len(ag.build_groups(shielded)) == 2

# So does a different Feel No Pain. That is STRICTER than the rules,
# whose key is W/Sv/InSv only because they take FNP to be a property of
# the whole unit; this engine allows it per model, so it has to split.
fnp_split = bodies + [model("Fnp", "Tough body", 2, cap=2, sv=3, fnp=5,
                            entry=1, scarcity=1)]
assert len(ag.build_groups(fnp_split)) == 2, \
    [g["label"] for g in ag.build_groups(fnp_split)]

# A differing W splits it too, on its own: two profiles that save alike
# and shrug alike are still different groups if one is tougher.
w_split = squad(3, entry=0, cap=2, sv=3) \
    + [model("Big", "Big body", 3, cap=3, sv=3, entry=1, scarcity=1)]
assert len(ag.build_groups(w_split)) == 2, \
    [g["label"] for g in ag.build_groups(w_split)]

# A destroyed model is not grouped at all (05.03 FAQ: you cannot group
# or allocate a wound to a destroyed model).
gone = squad(3, entry=0, cap=2) + [model("Dead", "Dead", 0, cap=2,
                                         entry=1, scarcity=1)]
assert sum(len(g["members"]) for g in ag.build_groups(gone)) == 3
print("grouping follows W/Sv/InSv/FNP and isolates every CHARACTER")


# --- 2. the champion heuristic: the rare model is spent last ----------

members = groups[0]["members"]
assert mixed[members[-1]]["key"] == "Sgt", [mixed[i]["key"]
                                            for i in members]
# ... and among equally common models, the wounded one goes first.
hurt = squad(3, entry=0, cap=2)
hurt[2]["wounds"] = 1
order = ag.build_groups(hurt + sergeant)[0]["members"]
combined = hurt + sergeant
assert combined[order[0]]["key"] == "Body2", [combined[i]["key"]
                                              for i in order]
assert combined[order[-1]]["key"] == "Sgt"

# ... and scarcity is the WEAKER of the two: a wounded champion is
# spent first anyway, exactly as the rules do one level up. This is
# the case that tells the two rankings apart.
wounded_champ = squad(3, entry=0, cap=2) \
    + [model("Sgt", "Sergeant", 1, cap=2, sv=3, entry=1, scarcity=1)]
wc_order = ag.build_groups(wounded_champ)[0]["members"]
assert wounded_champ[wc_order[0]]["key"] == "Sgt", \
    [wounded_champ[i]["key"] for i in wc_order]

# The heuristic has to BEAT the table order, not merely agree with it:
# here the rare model is listed first and must still be spent last.
inverted = [model("Champ", "Champion", 2, cap=2, sv=3, entry=0,
                  scarcity=1)] + squad(4, entry=1, cap=2, prefix="Line")
inv_order = ag.build_groups(inverted)[0]["members"]
assert inverted[inv_order[-1]]["key"] == "Champ", \
    [inverted[i]["key"] for i in inv_order]
print("champion heuristic: rare profile last, wounded first among equals")


# --- 3. the default allocation order and its three constraints --------

order = ag.default_order(groups, mixed)
assert ag.order_problem(groups, order, mixed) is None
assert order[0] == 0, order            # the bodyguard group comes first

# A CHARACTER group can never come before a non-CHARACTER one.
bad = [1, 0, 2]
assert ag.order_problem(groups, bad, mixed) == ag.ERR_CHARACTER_EARLY

# A wounded CHARACTER group must precede an unwounded one. Wound the
# Apothecary (group 2) and the default must put it ahead of the Captain.
mixed_hurt = [dict(m) for m in mixed]
mixed_hurt[-1]["wounds"] = 1
g2 = ag.build_groups(mixed_hurt)
o2 = ag.default_order(g2, mixed_hurt)
assert [g2[i]["label"] for i in o2][1] == "Apothecary", o2
assert ag.order_problem(g2, [o2[0], o2[2], o2[1]], mixed_hurt) \
    == ag.ERR_WOUNDED_LATE

# A wounded non-CHARACTER group must precede an unwounded one.
two = squad(2, entry=0, sv=3, cap=2) \
    + squad(2, entry=1, sv=4, cap=2, prefix="Light")
two[2]["wounds"] = 1                   # one Light body is hurt
gt = ag.build_groups(two)
ot = ag.default_order(gt, two)
assert two[gt[ot[0]]["members"][0]]["key"].startswith("Light"), ot
assert ag.order_problem(gt, list(reversed(ot)), two) == ag.ERR_WOUNDED_LATE

# Anything that is not a permutation is refused outright.
assert ag.order_problem(groups, [0, 0, 1], mixed) == ag.ERR_PERMUTATION

# Where the rules leave the order free -- two untouched non-CHARACTER
# groups -- the scarcity rule decides: the rank and file is spent
# before the small group with its own save profile.
free = squad(1, entry=0, sv=2, cap=2, prefix="Elite") \
    + squad(4, entry=1, sv=4, cap=2, prefix="Grunt")
gf = ag.build_groups(free)
of = ag.default_order(gf, free)
assert free[gf[of[0]]["members"][0]]["key"].startswith("Grunt"), of
assert ag.order_problem(gf, list(reversed(of)), free) is None  # legal too

# An illegal order is refused when the state is BUILT, not silently kept.
try:
    ag.Allocation(mixed, order=[1, 0, 2])
    raise AssertionError("Allocation accepted a CHARACTER-first order")
except ValueError:
    pass
print("allocation order: three constraints enforced, default legal")


# --- 4. the current group only changes when its last model dies -------

a = ag.Allocation(mixed)
assert a.current_group() == 0
seen = []
for _ in range(10):                    # 5 bodies x 2W = 10 damage
    i = a.current_model()
    assert i is not None
    seen.append(mixed[i]["key"])
    a.allocate(1)
# The Captain was never reachable while a bodyguard model stood.
assert "Cpt" not in seen and "Apo" not in seen, seen
assert a.current_group() in (1, 2)
# ... and the wounded-CHARACTER rule decides which of the two is next.
assert a.killed() == 5
print("current group advances only once every model in it is destroyed")


# --- 4b. the model count BLAST reads is state, not a constant --------

a = ag.Allocation(mixed)
assert a.standing() == 7, a.standing()
a.allocate(2)                          # one two-wound body removed
assert a.standing() == 6, a.standing()
a.allocate(1)                          # the next one only wounded
assert a.standing() == 6, a.standing()
print("standing() counts the models left, for BLAST and CLEAVE")


# --- 5. waste, spill and leftover -------------------------------------

a = ag.Allocation(squad(2, cap=2))
a.allocate(5)                          # one event, capped at 2 wounds
assert a.wasted == 3 and a.left[0] == 0 and a.left[1] == 2, a.left

a = ag.Allocation(squad(2, cap=2))
a.allocate(5, spill=True)              # mortal wounds pass model to model
assert a.wasted == 0 and a.left == [0, 0] and a.leftover == 1, a.left

# Nothing standing: the damage is reported as leftover, not as waste.
a = ag.Allocation(squad(1, cap=1))
a.allocate(1)
a.allocate(3)
assert a.wiped() and a.leftover == 3 and a.wasted == 0
# An explicit target overrides the automatic choice - what a caller
# that rolled a save against a model it picked FIRST has to be able to
# say - and names one model only: a spilling wound that outlives it
# carries on by the usual sequence.
a = ag.Allocation(mixed)
a.allocate(2, target=mixed.index(captain[0]))
assert a.result()[mixed.index(captain[0])]["after"] == 2, a.result()
a = ag.Allocation(squad(3, cap=1))
a.allocate(3, spill=True, target=2)
assert a.left == [0, 0, 0], a.left           # started at 2, then 0, 1
# A target with nothing left is ignored, not obeyed into a black hole.
a = ag.Allocation(squad(2, cap=1))
a.allocate(1, target=0)
a.allocate(1, target=0)
assert a.left == [0, 0] and a.leftover == 0, (a.left, a.leftover)
print("waste, spill and leftover accounted separately")


# --- 6. mortal wounds follow 06.02, not the declared order ------------

# Order the groups so the CHARACTER is second, then hurt it: a spilling
# mortal wound still goes to a wounded NON-CHARACTER first (06.02), and
# only reaches the character once no other model is standing.
mw = squad(2, entry=0, cap=2) + [model("Cpt", "Captain", 1, cap=4, sv=2,
                                       character=True, entry=1,
                                       scarcity=1)]
mw[1]["wounds"] = 1
a = ag.Allocation(mw)
assert a.mortal_model() == 1, a.mortal_model()      # the hurt body
a.allocate(5, spill=True)              # 1 + 2 on the bodies, 2 on the Cpt
assert a.left == [0, 0, 0], a.left

# The two sequences really are distinct, not the same walk under two
# names. With the group order reversed (legal: neither group is hurt)
# the next ATTACK lands on the Elite, while the next spilling MORTAL
# wound still goes to the Grunts - 06.02 knows nothing about the order
# the defender declared.
a = ag.Allocation(free, order=list(reversed(ag.default_order(gf, free))))
assert free[a.current_model()]["key"].startswith("Elite")
assert free[a.mortal_model()]["key"].startswith("Grunt")
# Same again with PRECISION, which CAN put a CHARACTER at the front.
a = ag.Allocation(mixed)
a.set_precision(1)
assert mixed[a.current_model()]["key"] == "Cpt"
assert mixed[a.mortal_model()]["key"] != "Cpt"
print("spilling mortal wounds follow their own selection sequence")


# --- 7. PRECISION: an override, never a reordering --------------------

a = ag.Allocation(mixed)
assert a.character_groups() == [1, 2]
a.set_precision(1)                     # the Captain
assert a.current_model() == mixed.index(captain[0])
a.allocate(4)                          # exactly his four wounds
assert a.current_group() == 0          # override spent, order resumes
try:
    a.set_precision(0)                 # not a CHARACTER group
    raise AssertionError("PRECISION accepted a bodyguard group")
except ValueError:
    pass
print("PRECISION reaches a chosen CHARACTER and lapses when it dies")


# --- 8. moving models and groups --------------------------------------

a = ag.Allocation(mixed)
# Inside a group anything goes: same W/Sv/InSv, so no roll changes.
first = a.groups[0]["members"][0]
assert a.move_member(0, 0, 1)
assert a.groups[0]["members"][1] == first
# Between groups the constraints still hold.
pos = a.order.index(1)                 # the Captain's group
assert not a.move_group(pos, -1), a.order
assert a.move_group(a.order.index(2), -1)      # two CHARACTER groups swap
assert ag.order_problem(a.groups, a.order, a.models) is None
print("model order free inside a group, group order still constrained")


# --- 9. result rows cover every record, destroyed models included -----

a = ag.Allocation(gone)
rows = a.result()
assert len(rows) == len(gone)
assert rows[-1]["before"] == 0 and rows[-1]["dead"] is False
a.allocate(2)
assert a.result()[0]["dead"] is True
print("result reports one row per record passed in")

print("alloc_groups: all checks passed")
