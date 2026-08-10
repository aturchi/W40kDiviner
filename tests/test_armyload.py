"""Test ArmyLoadState: join a subset, discard-on-unselect, build union."""
import testpaths                      # sets up sys.path to the engine src/
import native_format as nf
from army_load_core import ArmyLoadState

def army(name, unit_names):
    return {"format": nf.FORMAT_TAG, "armies": [{"name": name, "units": [
        {"name": n, "models": [], "keywords": [], "leadership": [],
         "support": []} for n in unit_names]}]}

st = ArmyLoadState([army("Alpha", ["x", "shared"]),
                    army("Beta", ["y", "shared"]),
                    army("Gamma", ["z"])])
assert st.names() == ["Alpha", "Beta", "Gamma"]

# Join Alpha(0) + Beta(1) -> new army; originals removed, joined appended
st.join([0, 1], "AB")
assert st.names() == ["Gamma", "AB"], st.names()
ab = st.armies[1]["armies"][0]
names = [u["name"] for u in ab["units"]]
assert names == ["x", "shared_Alpha", "y", "shared_Beta"], names
print("join: colliding units suffixed, originals removed:", names)

# Build with only the joined army selected (Gamma discarded)
data = st.build([1])
assert len(data["armies"]) == 1 and data["armies"][0]["name"] == "AB"
print("build joined-only: Gamma discarded, imported =",
      [a["name"] for a in data["armies"]])

# Build with both -> union of two armies
data2 = st.build([0, 1])
assert [a["name"] for a in data2["armies"]] == ["Gamma", "AB"]
print("build both:", [a["name"] for a in data2["armies"]])

# Errors
try:
    st.join([0], "x"); assert False
except ValueError: pass
try:
    st.join([0, 1], "  "); assert False
except ValueError: pass
assert st.build([]) is None
print("ALL ARMYLOAD TESTS PASS")
