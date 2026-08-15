"""session_io: file format, program guard, and the join records that let
the attack analyzer rebuild its [JOINED] entries after a reload.
Headless: session_io imports tkinter lazily, so only the pure half runs
here (the dialogs are compile-checked with the GUIs).
"""
import fnmatch, json, os, tempfile
import testpaths                      # sets up sys.path to the engine src/
import session_io as si
import leader_core as lc
import unit_model as um

data = json.load(open(testpaths.roster("space-marines.json")))
units = um.units_from_native(data)
leaders, rest = lc.split_leaders(units)
supports, others = lc.split_supports(rest)

tmp = os.path.join(tempfile.mkdtemp(),
                   "s" + si.ext_for("attack_analyzer"))

# --- round trip --------------------------------------------------------
state = {"data": data, "panels": {"att": {"army": "x", "joined": []}}}
si.save(tmp, "attack_analyzer", state)
assert si.load(tmp, "attack_analyzer") == state
print("round trip keeps the state")

# --- the program guard rejects the other program's session -------------
try:
    si.load(tmp, "game_assistant")
    raise AssertionError("cross-program load should fail")
except si.SessionError:
    pass
# --- and a plain roster JSON is not a session --------------------------
plain = os.path.join(os.path.dirname(tmp), "roster.json")
with open(plain, "w") as fh:
    json.dump(data, fh)
try:
    si.load(plain, "attack_analyzer")
    raise AssertionError("a roster is not a session")
except si.SessionError:
    pass
print("format and program guards hold")

# --- each program has its own extension, the dialogs never overlap -----
assert si.ext_for("attack_analyzer") != si.ext_for("game_assistant")
pats = {}
for prog in ("attack_analyzer", "game_assistant"):
    ext = si.ext_for(prog)
    types = si.filetypes_for(prog)
    assert ext.startswith(".")
    # exactly one pattern, and it is this program's extension: no
    # "All files" entry, or the load dialog would list the other
    # program's sessions through the filter dropdown
    assert len(types) == 1, types
    assert types[0][1] == "*" + ext, types
    pats[prog] = types[0][1]
assert not any("*.*" in p or p == "*" for p in pats.values()), pats
assert pats["attack_analyzer"] != pats["game_assistant"], pats
# neither pattern can ever match the other program's file
for prog, pat in pats.items():
    other = si.ext_for("game_assistant" if prog == "attack_analyzer"
                       else "attack_analyzer")
    assert not fnmatch.fnmatch("session" + other, pat), (prog, pat)
    assert fnmatch.fnmatch("session" + si.ext_for(prog), pat), (prog, pat)
assert si.ext_for("nope") == si.EXT          # fallback, never a crash
print("per-program extensions are distinct and mutually exclusive")

# --- joins survive a save/load cycle -----------------------------------
leader = next(l for l in leaders if any(u.can_attach(l) for u in others))
unit = next(u for u in others if u.can_attach(leader))
joined = [(unit.attach_leader(leader), leader, unit, None)]
recs = si.joined_records(joined)
assert recs == [{"unit": unit.name, "leader": leader.name,
                 "support": None}], recs
back, missing = si.rebuild_joins(json.loads(json.dumps(recs)),
                                 leaders, others, supports)
assert not missing and len(back) == 1
# a slot holds a LIST of helpers now (a session file written when it held
# at most one still reads back correctly, and is written the same way)
combined, l2, u2, s2 = back[0]
assert l2 == [leader] and u2 is unit and s2 == []
assert combined.attached_leader is leader
assert sum(m.model_count for m in combined.models()) == \
    sum(m.model_count for m in joined[0][0].models())
print("joins rebuild from names alone")

# --- several helpers in one slot survive the cycle too -----------------
# The roster has a single Leader, so clone it under another name (the
# rules forbid attaching duplicates) and open a second slot on the unit,
# as an attachmentSlots ability would.
raw = json.loads(json.dumps(data))
squad_d = next(u for a in raw["armies"] for u in a["units"]
               if u["name"] == unit.name)
squad_d["leader_slots"] = 2
leader_d = next(u for a in raw["armies"] for u in a["units"]
                if u["name"] == leader.name)
clone_d = json.loads(json.dumps(leader_d))
clone_d["name"] = leader_d["name"] + " (second)"
raw["armies"][0]["units"].append(clone_d)
u2s = um.units_from_native(raw)
l2s, r2 = lc.split_leaders(u2s)
s2s, o2s = lc.split_supports(r2)
squad = next(u for u in o2s if u.name == unit.name)
ld_a = next(l for l in l2s if l.name == leader.name)
ld_b = next(l for l in l2s if l.name == clone_d["name"])
assert squad.slot_capacity("leader") == 2
two = squad.attach_leader(ld_a)
assert two.can_attach(ld_b), "the second Leader must fit"
assert not two.can_attach(ld_a), "a duplicate Leader must be refused"
two = two.attach_leader(ld_b)
recs2 = si.joined_records([(two, [ld_a, ld_b], squad, [])])
assert recs2 == [{"unit": squad.name,
                  "leader": [ld_a.name, ld_b.name],
                  "support": None}], recs2
back2, missing2 = si.rebuild_joins(json.loads(json.dumps(recs2)),
                                   l2s, o2s, s2s)
assert not missing2 and len(back2) == 1, (back2, missing2)
assert [u.name for u in back2[0][1]] == [ld_a.name, ld_b.name]
assert len(back2[0][0].attached_leaders) == 2
print("a two-Leader join survives the save/load cycle")

# --- a roster that no longer holds the parts reports them, not crashes -
back, missing = si.rebuild_joins(
    [{"unit": "No Such Unit", "leader": leader.name, "support": None},
     {"unit": unit.name, "leader": "No Such Leader", "support": None}],
    leaders, others, supports)
assert back == [] and len(missing) == 2, (back, missing)
# an incompatible pairing is reported too, never silently attached
bad = next((u for u in others if not u.can_attach(leader)), None)
if bad is not None:
    back, missing = si.rebuild_joins(
        [{"unit": bad.name, "leader": leader.name, "support": None}],
        leaders, others, supports)
    assert back == [] and missing, (back, missing)
print("missing or incompatible joins are reported, not dropped silently")

print("ALL SESSION-IO TESTS PASS")
