"""Session-wide interface preferences.

Deliberately separate from rules_config: that module holds what the GAME
says, this one what the WINDOW does, and mixing them would mean a
re-reading of the rules and a change of taste landing in the same file.
Like the caps, these live for the process only - they are not written to
the session file, because a session records an analysis and not the shape
of the desk it was run on.

Kept free of tkinter so the preference can be read by the pure modules
and asserted headlessly.

- EMBED_DISTRIBUTION: whether the analyzer's result page carries the
  combined chart inline. Off by default: the page then holds the table
  and the numbers, and the chart of the whole unit is one double-click on
  the TOTAL row - the same gesture that opens a single weapon's chart, so
  there is one rule to remember instead of two.
"""

EMBED_DISTRIBUTION = False


def set_prefs(embed_distribution="unchanged") -> None:
    """Override the preferences. The sentinel is a string rather than
    None because None is a legal value for a preference."""
    global EMBED_DISTRIBUTION
    if embed_distribution != "unchanged":
        EMBED_DISTRIBUTION = bool(embed_distribution)
