"""From the table and the combat view to the records alloc_groups wants.

The game assistant knows two halves of the defender and neither is
enough on its own. The TABLE knows how many wounds every physical model
has left and which rows the player has masked off; the COMBAT VIEW knows
what the profiles are once every modifier has been applied. The Save
Rolls step needs both at once - the wounds to know what is left, the
Save and the invulnerable of the model an attack is allocated to, and
the structure to know which models are the attached CHARACTERs.

Putting that join here rather than in the window has a reason beyond
tidiness. It is an INDEX correspondence, and an index correspondence
that goes wrong does not raise: it quietly hands the bodyguard's 3+ to
the Captain and the Captain's 2+ to the bodyguard, and every number that
follows is plausible. It is checked, and it is checked where a test with
a real roster can reach it without a display.

WHY THE CORRESPONDENCE EXISTS AT ALL. build_entry_unit() assembles the
combat view from the unit's own model groups, then the attached leaders,
then the attached supports - the same order entry_models() walks - and
drops a group only when every copy of it is masked. The view's models
are therefore a SUBSEQUENCE of the entry's, in the same order, and the
caller knows which groups survived because it just walked the table.
That is an invariant of two modules that do not import each other, so
it is verified on every call, by position AND by name, rather than
trusted.

WHAT IS UNIT-WIDE AND WHAT IS NOT. Toughness is a property of the whole
target and does not move: for an Attached unit it is the highest among
the BODYGUARD models, for as long as the attacking unit is resolving
its attacks. Keywords are unit-wide too, and are the union of every
model's - which is why the CHARACTER keyword cannot be used to find the
CHARACTER models, and the structure is used instead. The Save, the
invulnerable, Feel No Pain and the wounds belong to the model the attack
was allocated to.
"""


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _characteristic(model, name, default=None):
    """A characteristic of a combat-view model, whose fields are
    Characteristic objects rather than plain numbers."""
    got = getattr(model, name, None)
    value = got.value() if hasattr(got, "value") else got
    return default if value is None else value


def unit_reference(dview) -> dict:
    """What the whole target unit fixes, in the shape the resolver
    reads: Toughness, keywords and a model count.

    The count is a starting value only. It is what BLAST and CLEAVE
    read, and it is taken again at every weapon activation from the
    models still standing, so the session overwrites it.
    """
    models = list(dview.models())
    getter = getattr(dview, "bodyguard_models", None)
    pool = (list(getter()) if getter is not None else []) or models
    tough = [_characteristic(m, "T") for m in pool]
    tough = [t for t in tough if isinstance(t, (int, float))]
    keywords = set()
    for m in models:
        keywords |= {str(k).strip().upper()
                     for k in m.effective_keywords(dview.keywords)}
    return {"T": max(tough) if tough else None, "keywords": keywords,
            "models": sum(m.model_count for m in models)}


def view_by_model_index(surviving, entry, dview, native=None):
    """{model index: combat-view model}, or ({}, why) when the two lists
    cannot be matched up.

    'surviving' are the model-group indices that still have an unmasked
    copy, in table order. A mismatch is reported rather than patched:
    guessing here would silently give a model somebody else's Save.
    """
    import leader_core as lc

    native = dict(lc.entry_models(entry)) if native is None else native
    view = list(dview.models())
    if len(view) != len(surviving):
        return {}, (f"the combat view has {len(view)} model groups and "
                    f"the table {len(surviving)}")
    out = {}
    for model, mi in zip(view, surviving):
        want = str((native.get(mi) or {}).get("name", ""))
        if want and str(getattr(model, "name", "")) != want:
            return {}, (f"model group {mi} is '{want}' on the table and "
                        f"'{getattr(model, 'name', '?')}' in the view")
        out[mi] = model
    return out, None


def records(rows, entry, dview):
    """([alloc_groups model records], problem).

    'rows' are the unmasked model copies in table order, each
    {'key', 'mi', 'label', 'wounds'} - 'key' being whatever the caller
    wants back (the tree row id, in the assistant).

    'problem' is None when every profile came from the combat view. When
    it is not, the records still come back, built from the datasheet
    instead: an attack resolved against the printed profile is wrong by
    whatever the modifiers were worth, which is far better than an
    attack resolved against the wrong model's profile, and the caller
    can say so.
    """
    import leader_core as lc

    native = dict(lc.entry_models(entry))
    attached = lc.attached_model_indices(entry)
    surviving = []
    for row in rows:
        if row["mi"] not in surviving:
            surviving.append(row["mi"])
    by_index, problem = view_by_model_index(surviving, entry, dview,
                                            native)
    out = []
    for row in rows:
        mi = row["mi"]
        model = by_index.get(mi)
        raw = native.get(mi) or {}
        if model is not None:
            cap = _int(_characteristic(model, "W", 1), 1)
            sv = _characteristic(model, "Sv")
            invuln, fnp = model.invuln, model.fnp
        else:
            cap = _int(raw.get("W"), 1)
            sv = raw.get("Sv")
            invuln, fnp = raw.get("invuln"), raw.get("fnp")
        out.append({"key": row["key"], "label": row["label"],
                    "wounds": max(0, _int(row["wounds"])),
                    "max": max(1, cap), "sv": sv, "invuln": invuln,
                    "fnp": fnp,
                    # NOT the CHARACTER keyword: an Attached unit gives
                    # that keyword to every model it contains.
                    "character": mi in attached,
                    "entry": mi,
                    # How many copies the group had at FULL strength,
                    # which is what makes the lone Sergeant the model
                    # worth keeping alive.
                    "scarcity": max(1, _int(raw.get("model_count"), 1))})
    return out, problem
