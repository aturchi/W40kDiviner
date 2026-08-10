"""Keywords configuration.

Loads keywords_config.json (searched in the project root, i.e. next to
the executables, then in src/). Provides the unit / model / weapon
keyword vocabularies used by the editors and by effect_specs
(setKeyword option list). Falls back to empty lists when the file is
missing or broken, so the editor still starts.
"""

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_SEARCH = [os.path.join(os.path.dirname(_HERE), "keywords_config.json"),
           os.path.join(_HERE, "keywords_config.json")]

_EMPTY = {"unit_keywords": [], "model_keywords": [], "weapon_keywords": []}


def load() -> dict:
    """Load and cache the keyword-vocabulary config (unit/model/weapon keyword lists) used by the editor list dialogs."""
    for path in _SEARCH:
        try:
            with open(path, encoding="utf-8") as f:
                cfg = json.load(f)
            return {k: list(cfg.get(k, [])) for k in _EMPTY}
        except (OSError, json.JSONDecodeError):
            continue
    return dict(_EMPTY)


def all_keywords(cfg: dict = None) -> list:
    """Merged, sorted union of all three vocabularies."""
    cfg = cfg or load()
    return sorted(set(cfg["unit_keywords"]) | set(cfg["model_keywords"])
                  | set(cfg["weapon_keywords"]))


def vocabulary_for(node_kind: str, key: str):
    """Vocabulary backing one list property of the editor: keywords
    follow the node type; a unit's leadership and support lists point at
    UNIT keywords (they name the unit types the leader/support can attach
    to)."""
    cfg = load()
    if key in ("leadership", "support"):
        return cfg.get("unit_keywords", [])
    return cfg.get({"units": "unit_keywords", "models": "model_keywords",
                    "weapons": "weapon_keywords"}.get(node_kind,
                                                      "unit_keywords"), [])
