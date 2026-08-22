"""Test ui_utils.wrap_lines, the word-wrap behind the merge dialog's
wrapped lists, without instantiating Tk: the function only needs an object
with a measure() method, so a fixed-width stub font stands in for the real
one (same approach as test_dialog_logic.py, which drives dialog logic on a
stub).
"""
import testpaths                      # noqa: F401  (sets sys.path to src/)
import tkstub

# ui_utils imports tkinter at module level. The wrap logic itself needs
# none of it, so on a Python built without tkinter the stub stands in
# rather than the whole test being lost to a missing optional package.
tkstub.install_if_missing()

import ui_utils as ui                 # noqa: E402  (must follow the stub)


class StubFont:
    """Monospace stand-in: every character is CHAR_PX wide."""

    CHAR_PX = 7

    def measure(self, text):
        return self.CHAR_PX * len(text)


F = StubFont()
COLS = 40                             # wrap width, in characters
PX = COLS * StubFont.CHAR_PX
IND = ui.WrappedList.INDENT

# Short enough: returned untouched, as a single line.
assert ui.wrap_lines("short row", F, PX) == ["short row"]

# Width unknown (widget not mapped yet): never wrap, never crash.
assert ui.wrap_lines("x " * 200, F, 0) == ["x " * 200]

LONG = ("keywords: ANTI-INFANTRY 4+ added to weapon Bolt rifle "
        "of model Intercessor Sergeant")
out = ui.wrap_lines(LONG, F, PX, IND)
print("wrapped into", len(out), "lines")
for line in out:
    print("   ", repr(line))

# Every line fits the width...
assert all(F.measure(line) <= PX for line in out), out
# ... continuation lines are indented ...
assert all(line.startswith(IND) for line in out[1:]), out
# ... and nothing was lost or reordered.
assert " ".join(line.strip() for line in out) == LONG

# A single word wider than the box is kept whole rather than cut mid-word
# (the horizontal scrollbar deals with it).
word = "X" * (COLS + 20)
assert ui.wrap_lines(f"start {word} end", F, PX, IND)[1] == IND + word

print("wrap_lines test PASS")
