"""Field kinds shared by condition_specs, effect_specs and spec_forms.

CHOICE   -> stored as {"title": ..., "key": ...}
ENUM     -> plain string from a fixed list
TEXT     -> free string (numbers kept as strings, dice notation allowed)
BOOL     -> real boolean
KEYWORDS -> list of uppercase strings (comma-separated in the UI)
"""

CHOICE = "choice"
ENUM = "enum"
TEXT = "text"
BOOL = "bool"
KEYWORDS = "keywords"
COMBO = "combo"     # free string with suggested values (editable combobox)
