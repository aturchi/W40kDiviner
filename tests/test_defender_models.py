"""defender_models: joining the table to the combat view.

This is an index correspondence, and the reason it has a module and a
test of its own is that getting it wrong does not raise. It hands the
bodyguard's Save to the Captain and the Captain's to the bodyguard, and
every number downstream stays plausible. So the checks here are about
WHICH profile lands on WHICH model, and they run against a real roster
entry rather than a hand-made one - the ordering being verified is an
invariant of leader_core and modifier_engine, which the test must not
be allowed to fake.
"""
import copy
import json

import testpaths                      # sets up sys.path to the engine src/
import alloc_groups as ag
import analyzer_core as ac
import defender_models as dm
import leader_core as lc

data = json.load(open(testpaths.roster("space-marines.json")))
UNITS = {u["name"]: u for u in data["armies"][0]["units"]}


def entry_of(unit, leader=None):
    return lc.make_entry(UNITS[unit], UNITS[leader] if leader else None)


def rows_for(entry, wounds=None):
    """Every copy of every model group, in table order, as the assistant
    would hand them over."""
    out = []
    for mi, model in lc.entry_models(entry):
        cap = int(model.get("W") or 1)
        for c in range(int(model.get("model_count") or 1)):
            key = f"m{mi}c{c}"
            out.append({"key": key, "mi": mi,
                        "label": f"{model['name']} - {c + 1}",
                        "wounds": (wounds or {}).get(key, cap)})
    return out


def unit_of(entry, masked=None):
    """The combat-ready Unit for an entry, with 'masked' copies removed -
    the same call the assistant makes from the table state."""
    return lc.build_entry_unit(entry, masked or {}, {}, {})


def views(entry, masked=None):
    attacker = unit_of(lc.make_entry(UNITS["Captain"], None))
    return ac.build_views(attacker, unit_of(entry, masked), {}, {})


# The entry the whole exercise is about: a bodyguard squad with an
# attached Leader whose profile is not the squad's.
ENTRY = entry_of("Assault Intercessor Squad", "Captain")
_A, DVIEW = views(ENTRY)
NATIVE = dict(lc.entry_models(ENTRY))

# The indices are DERIVED and never written down. A datasheet is free to
# split its bodyguard across several model groups - the squad used here
# has one group of Intercessors and a second holding the Sergeant - and
# an earlier version of this file assumed a single group at index 0 with
# the Leader at index 1. That holds for the synthetic roster and is
# silently false for the real one, where the squad keeps its Sergeant in
# a group of its own and the Leader lands at index 2 - so the whole file
# failed at this line under --real_data instead of testing anything.
# Derived, it runs on both, and the real source makes the case HARDER:
# the correspondence then has three groups to get wrong, not two.
_attached = sorted(lc.attached_model_indices(ENTRY))
assert len(_attached) == 1, ("one attached Leader is the shape this file "
                             "is written around", _attached)
LEAD = _attached[0]                       # the Leader's model group
BODY = [i for i in sorted(NATIVE) if i != LEAD]     # the bodyguard's
assert BODY, ("the bodyguard must have at least one model group", BODY)
BODY0 = BODY[0]
BODY_COPIES = sum(NATIVE[i]["model_count"] for i in BODY)
BODY_WOUNDS = sum(NATIVE[i]["model_count"] * NATIVE[i]["W"] for i in BODY)
LEAD_KEY = f"m{LEAD}c0"


# --- 1. the unit reference is what the UNIT fixes ---------------------

ref = dm.unit_reference(DVIEW)
bodyguard_t = max(NATIVE[i]["T"] for i in BODY)
assert ref["T"] == bodyguard_t, (ref["T"], bodyguard_t)
# ... and the Captain's own Toughness is ignored even when it differs.
tough = {m["T"] for m in NATIVE.values()}
assert ref["T"] == max(NATIVE[i]["T"] for i in BODY), ref["T"]
assert ref["models"] == sum(m["model_count"] for m in NATIVE.values())
# Keywords are the UNION of the parts: the attached Captain's own
# keyword is on the combined unit, which no bodyguard model brought.
solo_kw = dm.unit_reference(views(entry_of(
    "Assault Intercessor Squad"))[1])["keywords"]
assert ref["keywords"] > solo_kw, (sorted(ref["keywords"]),
                                   sorted(solo_kw))
# The roster this suite ships is degenerate on Toughness - every
# attachable profile is T4 - so the case that tells the rule apart is
# BUILT here. The doctoring is the characteristics only: the entry is
# still assembled by leader_core and the view by modifier_engine, which
# is where the ordering invariant under test actually lives.
tough_unit = copy.deepcopy(UNITS["Assault Intercessor Squad"])
second = copy.deepcopy(tough_unit["models"][0])
second.update(name="Heavy body", model_count=2, T=5)
tough_unit["models"].append(second)
tough_leader = copy.deepcopy(UNITS["Captain"])
tough_leader["models"][0]["T"] = 6
mixed = lc.make_entry(tough_unit, tough_leader)
mixed_ref = dm.unit_reference(ac.build_views(
    unit_of(lc.make_entry(UNITS["Captain"], None)), unit_of(mixed),
    {}, {})[1])
# Highest among the BODYGUARD models: not 6, which is the highest in the
# unit, and not 4, which is the lowest among the bodyguard.
assert mixed_ref["T"] == 5, mixed_ref["T"]
# The union really is a union. In a real roster no model carries
# keywords of its own - all 966 of them inherit the unit's - so walking
# every model gives the same answer as reading the first, and nothing
# would tell the two apart. A synthetic view does: one model of the unit
# holds a keyword the others do not, and ANTI-X keys on the UNIT, which
# has all the keywords of all its models.
class _FakeModel:
    def __init__(self, tough, keywords, count=1):
        self.T = tough
        self.model_count = count
        self._kw = set(keywords)

    def effective_keywords(self, unit_keywords):
        return set(unit_keywords) | self._kw


class _FakeView:
    keywords = {"INFANTRY"}

    def __init__(self, models, bodyguard=None):
        self._models = list(models)
        self._bodyguard = bodyguard

    def models(self):
        return list(self._models)

    def bodyguard_models(self):
        return list(self._bodyguard if self._bodyguard is not None
                    else self._models)


plain = _FakeModel(4, set(), count=4)
odd = _FakeModel(4, {"Character"}, count=1)
ref = dm.unit_reference(_FakeView([plain, odd]))
assert "CHARACTER" in ref["keywords"], ref["keywords"]
assert "INFANTRY" in ref["keywords"]
assert ref["models"] == 5, ref
# Toughness is the bodyguard's, and the highest of them, even when a
# tougher model is standing in the unit.
led = _FakeView([plain, _FakeModel(9, set())], bodyguard=[plain])
assert dm.unit_reference(led)["T"] == 4, dm.unit_reference(led)
print("the unit reference carries bodyguard Toughness and united keywords")


# --- 2. every model gets ITS OWN save, from the combat view -----------

recs, problem = dm.records(rows_for(ENTRY), ENTRY, DVIEW)
assert problem is None, problem
assert len(recs) == sum(m["model_count"] for m in NATIVE.values())
by_key = {r["key"]: r for r in recs}
captain = [r for r in recs if r["character"]]
bodies = [r for r in recs if not r["character"]]
assert len(captain) == 1 and captain[0]["entry"] == LEAD
assert len(bodies) == BODY_COPIES
assert captain[0]["max"] == NATIVE[LEAD]["W"], captain[0]
assert bodies[0]["max"] == NATIVE[BODY0]["W"], bodies[0]
assert captain[0]["invuln"] == NATIVE[LEAD]["invuln"]
assert bodies[0]["invuln"] == NATIVE[BODY0]["invuln"]
assert captain[0]["invuln"] != bodies[0]["invuln"], "the case is degenerate"
# Scarcity is the count at FULL strength, not the copies still standing.
assert bodies[0]["scarcity"] == NATIVE[BODY0]["model_count"]
assert captain[0]["scarcity"] == 1
# And it is the profile as MODIFIED, not as printed: a save modifier on
# the defender has to reach the record, or the window would roll the
# datasheet's save while the analyzer used the modified one.
_a, dv_mod = ac.build_views(
    unit_of(lc.make_entry(UNITS["Captain"], None)), unit_of(ENTRY), {},
    {"defender_model": {"Sv": -1}})
recs_mod, problem = dm.records(rows_for(ENTRY), ENTRY, dv_mod)
assert problem is None, problem
assert recs_mod[0]["sv"] != NATIVE[BODY0]["Sv"], (recs_mod[0]["sv"],
                                                  NATIVE[BODY0]["Sv"])
assert recs_mod[0]["sv"] == NATIVE[BODY0]["Sv"] - 1
print("each model carries the profile of its own group, not the unit's")


# --- 3. the CHARACTER flag comes from the structure, not a keyword ----

alone = entry_of("Assault Intercessor Squad")
_a, dv = views(alone)
recs_alone, problem = dm.records(rows_for(alone), alone, dv)
assert problem is None
assert not any(r["character"] for r in recs_alone)
# The point, stated as strongly as it can be: in the LED unit every
# model has exactly the same effective keywords, so no keyword test of
# any kind could have picked the Captain out. Only the structure can.
sets = [frozenset(m.effective_keywords(DVIEW.keywords))
        for m in DVIEW.models()]
assert len(set(sets)) == 1, [sorted(s) for s in sets]
assert sum(1 for r in recs if r["character"]) == 1
print("the attached models are found by structure, never by the keyword")


# --- 4. a masked group shifts the indices, and is followed -----------

# The Captain masked off: the view has one model group, the table one
# surviving index, and the bodyguard profile must not move onto it.
# Masking every copy of the Captain's group is how the table says he is
# gone: build_entry_unit then drops the group entirely.
_a, dv_solo = views(ENTRY, masked={LEAD: NATIVE[LEAD]["model_count"]})
rows = [r for r in rows_for(ENTRY) if r["mi"] in BODY]
recs2, problem = dm.records(rows, ENTRY, dv_solo)
assert problem is None, problem
assert all(r["entry"] in BODY for r in recs2)
assert recs2[0]["max"] == NATIVE[BODY0]["W"]
assert not any(r["character"] for r in recs2)
print("masking a group shifts the correspondence, and it follows")


# --- 5. a correspondence that cannot be trusted is REPORTED -----------

# Two surviving groups on the table but a view built from one: the join
# is impossible, and the records come back from the datasheet with a
# reason rather than from a guess.
recs3, problem = dm.records(rows_for(ENTRY), ENTRY, dv_solo)
assert problem and "model groups" in problem, problem
assert len(recs3) == len(rows_for(ENTRY))
assert recs3[-1]["max"] == NATIVE[LEAD]["W"], "fallen back to the datasheet"
assert recs3[-1]["character"] is True, "the structure still holds"

# A view of the right LENGTH but the wrong models is caught by name:
# claim the surviving groups arrive in a different order and the join
# must refuse rather than swap the two profiles over.
#
# The list HAS to be the right length here, or the length check fires
# first and this proves nothing about names. That is what a hardcoded
# two-element list did once the squad turned out to have three model
# groups: the assertion still passed, on the wrong reason.
true_order = sorted(NATIVE)
mapping, why = dm.view_by_model_index(true_order, ENTRY, DVIEW)
assert mapping and why is None, ("the true order must join cleanly",
                                 mapping, why)
swapped = [true_order[1], true_order[0]] + true_order[2:]
mapping, why = dm.view_by_model_index(swapped, ENTRY, DVIEW)
assert mapping == {} and why and "on the table" in why, (mapping, why)
print("a join that cannot be trusted is reported, not patched over")


# --- 6. the records go straight into the allocation groups ------------

groups = ag.build_groups(recs)
assert len(groups) == 2, [g["label"] for g in groups]
assert [g["character"] for g in groups] == [False, True]
order = ag.default_order(groups, recs)
assert ag.order_problem(groups, order, recs) is None
assert groups[order[0]]["character"] is False, "the CHARACTER is not first"
alloc = ag.Allocation(recs)
# The Captain is unreachable while a single bodyguard model stands.
seen = set()
for _ in range(BODY_WOUNDS):
    seen.add(alloc.models[alloc.current_model()]["key"])
    alloc.allocate(1)
assert not any(k.startswith(f"m{LEAD}") for k in seen), seen
assert alloc.current_model() is not None
assert alloc.models[alloc.current_model()]["character"] is True
print("the records feed the allocation groups and the rules hold")


# --- 7. wounds already lost come from the table, not the profile ------

hurt = rows_for(ENTRY, wounds={f"m{BODY0}c0": 1, LEAD_KEY: 2})
recs4, problem = dm.records(hurt, ENTRY, DVIEW)
assert problem is None
got = {r["key"]: r["wounds"] for r in recs4}
assert got[f"m{BODY0}c0"] == 1 and got[LEAD_KEY] == 2, got
assert got[f"m{BODY0}c1"] == NATIVE[BODY0]["W"]
# A cell holding something that is not a number is read as no wounds
# left rather than as a full model: a model at zero is simply not
# grouped, which is the safe way to be wrong here.
odd = rows_for(ENTRY)
odd[0]["wounds"] = "dead?"
recs5, _p = dm.records(odd, ENTRY, DVIEW)
assert recs5[0]["wounds"] == 0
assert len(ag.build_groups(recs5)[0]["members"]) == BODY_COPIES - 1
print("wounds come from the table, and unreadable ones do not inflate it")

print("defender_models: all checks passed")
