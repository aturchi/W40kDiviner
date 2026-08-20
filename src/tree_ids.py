"""Row-id grammar of the game assistant table.

A Treeview row id encodes the position of the roster item it shows, so
the table needs no parallel bookkeeping:

    u{ui}                  roster entry (unit, with its helpers)
    u{ui}m{mi}             model group, mi = GLOBAL model index of the
                           entry (leader_core.entry_models)
    u{ui}m{mi}w{wi}        weapon wi of that model group
    u{ui}m{mi}c{ci}        one physical copy of that model group
    u{ui}a:{key}           ability of the entry, keyed by
                           leader_core.entry_ability_keys - the
                           ability's own 'id' when it has a usable one,
                           so the row keeps pointing at the same ability
                           even if the entry's parts change
    u{ui}m{mi}sep, u{ui}asep    decoration, never parsed

The ':' before an ability key is what keeps the abilities separator
('u3asep') from parsing as the ability named 'sep'.

The module is deliberately free of tkinter: the grammar is the contract
between the table and the roster, and it is tested headless.
"""

import re

_STRUCT_RE = re.compile(r"u(\d+)(?:m(\d+))?(?:w(\d+))?(?:c(\d+))?$")
_ABILITY_RE = re.compile(r"u(\d+)a:(.+)$", re.DOTALL)


# ---------------- builders ----------------


def unit_iid(ui):
    return f"u{ui}"


def model_iid(ui, mi):
    return f"u{ui}m{mi}"


def weapon_iid(ui, mi, wi):
    return f"u{ui}m{mi}w{wi}"


def copy_iid(ui, mi, ci):
    return f"u{ui}m{mi}c{ci}"


def ability_iid(ui, key):
    return f"u{ui}a:{key}"


def models_sep_iid(ui, mi):
    return f"u{ui}m{mi}sep"


def abilities_sep_iid(ui):
    return f"u{ui}asep"


# ---------------- parsers ----------------


def parse(iid):
    """'u3m1w2' -> (3, 1, 2, None); (None, None, None, None) for a row
    that is not a unit/model/weapon/copy (separators, ability rows)."""
    m = _STRUCT_RE.fullmatch(iid or "")
    if m is None:
        return (None, None, None, None)
    return tuple(None if g is None else int(g) for g in m.groups())


def parse_ability(iid):
    """'u3a:1f2e' -> (3, '1f2e'); (None, None) for any other row - note
    that the abilities separator 'u3asep' must NOT parse as an ability
    (it carries no ':')."""
    m = _ABILITY_RE.fullmatch(iid or "")
    if m is None:
        return (None, None)
    return (int(m.group(1)), m.group(2))


def entry_index(iid):
    """The roster index of any structural row (unit, model, weapon,
    copy or ability), or None for decoration."""
    ui = parse(iid)[0]
    return ui if ui is not None else parse_ability(iid)[0]


def is_separator(iid):
    """True for the decoration rows, which carry no roster item."""
    return bool(iid) and iid.endswith("sep")
