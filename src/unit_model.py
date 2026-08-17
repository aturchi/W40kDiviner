"""Unit / Model / Weapon object model (native format).

Profiles are immutable by convention: nothing mutates a constructed
object after loading. Combat-time modifications happen on copies built
by modifier_engine (Unit.against delegates there).

Conventions:
- AP follows the datasheet convention: negative or zero (e.g. -4).
- M, LD, OC, RNG are carried but typically None for now.
"""

from characteristics import Characteristic

import re as _re


def _kw_singular(word):
    """Best-effort English singular of one lowercased word, covering the
    plural forms seen in 40k keywords: '-ies'->'-y' (allies->ally),
    '-ves'->'-f' (wolves->wolf), '-ses/-xes/-zes/-ches/-shes'->drop '-es',
    trailing '-s'->drop. Idempotent-ish: returns the word unchanged when no
    rule applies. Used so a leadership entry word 'Battlesuits' matches the
    unit keyword 'Battlesuit'."""
    w = word
    if len(w) > 3 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("ves"):
        return w[:-3] + "f"
    if len(w) > 3 and w.endswith("es") and w[-3:-2] in ("s", "x", "z") \
            or w.endswith(("ches", "shes")):
        return w[:-2]
    if len(w) > 1 and w.endswith("s"):
        return w[:-1]
    return w


def _kw_key(word):
    """Normalized comparison key for a keyword word: lowercased, stripped of
    punctuation, singularized. 'Battlesuits' and 'Battlesuit' -> 'battlesuit';
    the curly apostrophe in T'au is normalized to a straight one."""
    w = _re.sub(r"[^\w'\u2019]", "", word.lower()).replace("\u2019", "'")
    return _kw_singular(w)


def _covers(words, keyword_words):
    """True if the word list can be tiled by whole keywords, in order.
    'keyword_words' is the set of keywords already split into words."""
    n = len(words)
    reach = [False] * (n + 1)
    reach[0] = True
    for i in range(n):
        if not reach[i]:
            continue
        for seq in keyword_words:
            j = i + len(seq)
            if seq and j <= n and tuple(words[i:j]) == seq:
                reach[j] = True
    return reach[n]


def _entry_matches_keywords(entry, keywords):
    """True if a leadership/support ENTRY matches a unit's keyword list.
    Two datasheet conventions both occur, so either satisfies a match:
      (A) whole-entry: the entry equals a keyword -- Space Marines store the
          full unit name as a single keyword ('Assault Intercessor Squad').
      (B) piece-by-piece: the entry splits into a SEQUENCE of keywords --
          T'au store split keywords ('Crisis','Fireknife','Battlesuit')
          while the entry is the full name 'Crisis Fireknife Battlesuits'.
          A keyword may itself be several words, so 'Wolf Guard
          Headtakers' matches the pair 'WOLF GUARD' + 'HEADTAKERS'.
    All comparisons use _kw_key (lowercased, singular/plural-insensitive).
    An empty entry never matches."""
    e = entry.strip()
    if not e:
        return False
    # (A) whole-entry equals a keyword
    if _entry_key(e) in {_entry_key(k) for k in keywords}:
        return True
    # (B) the entry's words are covered by keywords, in order
    words = [_kw_key(w) for w in _re.split(r"\s+", e) if w.strip()]
    kw_words = {tuple(_kw_key(w) for w in _re.split(r"\s+", str(k))
                      if w.strip())
                for k in keywords}
    return bool(words) and _covers(words, kw_words)


def _entry_key(text):
    """Whole-string comparison key: lowercased, apostrophes normalized, and
    each word singularized, so 'Assault Intercessor Squads' == 'Assault
    Intercessor Squad'."""
    words = [_kw_singular(_re.sub(r"[^\w'\u2019]", "", w.lower())
                          .replace("\u2019", "'"))
             for w in _re.split(r"\s+", text.strip()) if w.strip()]
    return " ".join(words)


def _any_entry_matches(entries, keywords):
    """True if ANY entry of the list matches the keyword set."""
    return any(_entry_matches_keywords(e, keywords) for e in entries)


class Weapon:
    """One weapon profile on a model. Characteristics (A, S, AP, D, RNG and
    the hit skill) are wrapped in :class:`Characteristic` so dice notation
    is supported. 'skill' is stored once and surfaced as WS (Melee) or BS
    (Ranged) via properties. 'count' is how many copies of this weapon the
    model group carries. 'effects' is empty on profiles and populated only
    on the combat-view copies built by :mod:`modifier_engine`."""

    def __init__(self, name, wtype, A, skill, S, AP, D, RNG=None,
                 count=1, keywords=None, abilities=None):
        self.name = name
        self.type = wtype                     # 'Melee' or 'Ranged'
        self.A = Characteristic(A)
        self._skill = Characteristic(skill)   # WS or BS depending on type
        self.S = Characteristic(S)
        self.AP = Characteristic(AP)
        self.D = Characteristic(D)
        self.RNG = Characteristic(RNG)
        self.count = count                    # copies of this weapon in the unit
        self.keywords = list(keywords or [])
        self.abilities = list(abilities or [])
        self.effects = []                     # populated only on combat views

    @property
    def WS(self):
        """Weapon Skill: the hit characteristic for a Melee weapon, else None."""
        return self._skill if self.type == "Melee" else Characteristic(None)

    @property
    def BS(self):
        """Ballistic Skill: the hit characteristic for a Ranged weapon, else None."""
        return self._skill if self.type == "Ranged" else Characteristic(None)

    def __repr__(self):
        return f"Weapon({self.name!r}, {self.type})"


class Model:
    """A group of identical models within a unit ('model_count' copies).
    Carries the defensive/movement characteristics (M, T, Sv, W, LD, OC,
    plus optional invuln and fnp) and its weapons. Characteristics accept
    dice notation via :class:`Characteristic`. Damage reduction is not a
    characteristic here: it is modelled as a defender ability
    (damageReduction / damageSetZero) resolved by the attack maths."""

    def __init__(self, name, model_count=1, M=None, T=None, Sv=None, W=None,
                 LD=None, OC=None, invuln=None, fnp=None,
                 keywords=None, weapons=None, abilities=None):
        self.name = name
        self.model_count = model_count
        self.M = Characteristic(M)
        self.T = Characteristic(T)
        self.Sv = Characteristic(Sv)
        self.W = Characteristic(W)
        self.LD = Characteristic(LD)
        self.OC = Characteristic(OC)
        self.invuln = invuln                  # int (N+) or None -> ignored
        self.fnp = fnp                        # int (N+) or None -> ignored
        # NOTE: damage reduction is no longer a static model attribute. It
        # is expressed entirely through 'damageReduction'/'damageSetZero'
        # defender abilities, resolved per-attack by the attack maths.
        self.keywords = list(keywords or [])      # as written on the model:
        #   plain token -> ADD to the inherited unit keywords;
        #   "-TOKEN"    -> SUPPRESS that inherited keyword.
        self.inherited_keywords = []          # set at build time from the
        #                                       owning unit (see
        #                                       units_from_native)
        self.weapons = list(weapons or [])
        self.abilities = list(abilities or [])
        self.effects = []                     # populated only on combat views

    def effective_keywords(self, unit_keywords=None) -> set:
        """Resolved keyword set: unit keywords inherited by default, the
        model's own plain keywords added, and any '-TOKEN' on the model
        suppressing the inherited TOKEN. Comparison is case-insensitive
        on the suppression token; the returned set preserves the casing
        of the surviving keywords.

        unit_keywords, when given, replaces the load-time inherited set as
        the base - the attack engine passes the CURRENT unit-view keywords
        so that combat-time modifications (e.g. setKeyword on the unit)
        are reflected. When omitted, the load-time inherited set is used
        (suitable for display/inspection of a static profile)."""
        base = self.inherited_keywords if unit_keywords is None \
            else unit_keywords
        suppress = {k[1:].upper() for k in self.keywords
                    if k.startswith("-")}
        add = [k for k in self.keywords if not k.startswith("-")]
        result = {k for k in base
                  if k.upper() not in suppress}
        result |= set(add)
        return result

    def __repr__(self):
        return f"Model({self.name!r} x{self.model_count})"


def combined_name(base, leaders, supports) -> str:
    """Name of a combined unit: 'base + helper' with one helper of a
    kind, 'base + N leaders' with several, because listing three or four
    names makes the roster lists unreadable. 'leaders'/'supports' are
    Units or anything with a .name (or a plain name string).
    """
    def _n(x):
        return x if isinstance(x, str) else x.name

    parts = [base]
    for helpers, word in ((list(leaders), "leader"),
                          (list(supports), "support")):
        if len(helpers) == 1:
            parts.append(_n(helpers[0]))
        elif helpers:
            parts.append(f"{len(helpers)} {word}s")
    return " + ".join(parts)


class Unit:
    """A datasheet unit: one or more :class:`Model` groups plus unit-level
    data. Profiles are immutable by convention. Two independent attachment
    slots exist -- a leader (``leadership`` list) and a support (``support``
    list) -- so a unit may carry one of each; :meth:`attach_leader` /
    :meth:`attach_support` return a NEW combined Unit and never mutate the
    originals. ``leader_effects`` are the abilities a leader/support applies
    to the whole combined unit. Display-only text (unit_composition,
    wargear_options, notes) is ignored by the combat maths."""

    def __init__(self, name, models=None, keywords=None, abilities=None,
                 points=0, leader_effects=None,
                 apply_leader_effects_to_self=False, profile_name=None,
                 leadership=None, damageable=False,
                 unit_composition="", wargear_options="", notes="",
                 support=None, leader_slots=1, support_slots=1):
        self.name = name
        self.base_name = name       # name without the attached helpers;
        #   _attach carries the original one over so the combined name is
        #   rebuilt from scratch each time instead of growing.
        self.profile_name = profile_name or name
        self._models = list(models or [])
        self.keywords = list(keywords or [])
        self.abilities = list(abilities or [])
        self.points = points
        # Reference-only prose shown when inspecting a unit; ignored by the
        # combat maths. unit_composition and wargear_options are the source
        # sections verbatim; notes is a free field for anything else.
        self.unit_composition = unit_composition or ""
        self.wargear_options = wargear_options or ""
        self.notes = notes or ""
        self.damageable = bool(damageable)    # True -> the unit has a
        #   "Damaged" bracket; when the per-session damaged flag is set
        #   in the analyzer/assistant it takes -1 to its Hit rolls.
        self.leadership = list(leadership or [])  # keywords of the units
        #   this unit can lead (empty -> not a leader). A unit-level
        #   property: every model of the unit shares it.
        self.support = list(support or [])    # keywords of the units this
        #   unit can support (empty -> not a support). Mirrors leadership:
        #   a support attaches like a leader but fills a SEPARATE slot, so
        #   a unit may carry one leader AND one support at once.
        # How many helpers may be attached in each slot. Both default to
        # 1; a datasheet that allows more (e.g. a 20-model unit taking two
        # Leaders) either carries a different number here or an
        # 'attachmentSlots' ability - see slot_capacity().
        self.leader_slots = int(leader_slots)
        self.support_slots = int(support_slots)
        self.leader_effects = list(leader_effects or [])
        self.apply_leader_effects_to_self = apply_leader_effects_to_self
        self.attached_leaders = []            # set on combined units only
        self.attached_supports = []           # set on combined units only
        self.effects = []                     # populated only on combat views

    # Historical single-slot accessors: the FIRST helper of each slot, or
    # None. Kept because most of the code only ever needs "is this unit
    # led, and by whom".
    @property
    def attached_leader(self):
        return self.attached_leaders[0] if self.attached_leaders else None

    @property
    def attached_support(self):
        return self.attached_supports[0] if self.attached_supports else None

    def slot_capacity(self, slot: str) -> int:
        """How many helpers fit in 'slot' ('leader' or 'support'): the
        unit's own number, changed by any ENABLED 'attachmentSlots'
        ability. Structural, so it is read at join time and the ability's
        activation conditions are ignored (the enable/disable toggle is
        the switch)."""
        n = self.leader_slots if slot == "leader" else self.support_slots
        for ab in self.abilities:
            if not ab.get("enabled", True):
                continue
            eff = ab.get("effect") or {}
            if eff.get("type") != "attachmentSlots":
                continue
            d = eff.get("data", {})
            which = d.get("slot")
            which = which.get("key") if isinstance(which, dict) else which
            if str(which or "leader").lower() != slot:
                continue
            op = d.get("operator")
            op = op.get("key") if isinstance(op, dict) else op
            try:
                value = int(d.get("value"))
            except (TypeError, ValueError):
                continue
            n = value if str(op or "add").lower() == "set" else n + value
        return max(0, n)

    def is_leader(self) -> bool:
        """True only for a unit that BOTH can lead (non-empty leadership
        list) AND is currently attached to a unit. In practice this is
        the combined unit built by attach_leader (it inherits the
        leader's leadership list and carries attached_leader). A
        standalone, unattached leader returns False. Currently unused,
        kept for future rules expansions."""
        return bool(self.leadership) and bool(self.attached_leaders)

    # ---------- model access ----------

    def models(self):
        """All model groups: the unit's own, plus any attached leader's
        and attached support's (a unit may carry one of each)."""
        out = list(self._models)
        for helper in self.attached_leaders + self.attached_supports:
            out += helper.models()
        return out

    def bodyguard_models(self):
        """The unit's OWN model groups, i.e. models() without those of an
        attached leader or support. For a unit with nothing attached this
        is the same list as models(). The rules use this set to fix the
        unit's Toughness characteristic when a leader is attached."""
        return list(self._models)

    def __iter__(self):
        return iter(self.models())

    def model(self, name):
        """First model group whose name matches (None if absent)."""
        return next((m for m in self.models() if m.name == name), None)

    # ---------- leader / support attachment ----------

    def can_attach(self, leader: "Unit") -> bool:
        """True if 'leader' can lead this unit: some entry of the leader's
        leadership list matches this unit's keywords (see
        _entry_matches_keywords)."""
        return (len(self.attached_leaders) < self.slot_capacity("leader")
                # "provided those Leaders are not duplicates"
                and all(l.name != leader.name for l in self.attached_leaders)
                and _any_entry_matches(leader.leadership, self.keywords))

    def can_support(self, support: "Unit") -> bool:
        """True if 'support' can support this unit: some entry of the
        support's support list matches this unit's keywords. Mirrors
        can_attach for the separate support slot."""
        return (len(self.attached_supports) < self.slot_capacity("support")
                and all(x.name != support.name
                        for x in self.attached_supports)
                and _any_entry_matches(support.support, self.keywords))

    def _attach(self, helper: "Unit", slot: str) -> "Unit":
        """Return a NEW combined unit (originals untouched) with 'helper'
        joined in 'slot' ('leader' or 'support'). helper.leader_effects
        become active on the whole combined unit. A helper already attached
        in the OTHER slot is preserved, so a unit can carry one leader AND
        one support at once. Effects from both helpers are merged."""
        base_models = self._models
        base_keywords = set(self.keywords)
        base_abilities = list(self.abilities)
        base_effects = list(self.leader_effects)
        kept_leaders = list(self.attached_leaders)
        kept_supports = list(self.attached_supports)
        (kept_leaders if slot == "leader" else kept_supports).append(helper)
        combined = Unit(
            name=combined_name(self.base_name, kept_leaders, kept_supports),
            models=base_models,
            keywords=sorted(base_keywords | set(helper.keywords)),
            abilities=base_abilities + helper.abilities,
            points=self.points + helper.points,
            leader_effects=base_effects + helper.leader_effects,
            apply_leader_effects_to_self=True,
            profile_name=self.profile_name,
            damageable=self.damageable,
            leadership=self.leadership or helper.leadership,
            support=self.support or helper.support,
            leader_slots=self.leader_slots,
            support_slots=self.support_slots)
        combined.base_name = self.base_name
        combined.attached_leaders = kept_leaders
        combined.attached_supports = kept_supports
        return combined

    def attach_leader(self, leader: "Unit") -> "Unit":
        """Return a NEW combined unit (originals untouched). The leader's
        leader_effects become active on the whole combined unit."""
        if not self.can_attach(leader):
            raise ValueError(f"{leader.name} cannot lead {self.name}")
        return self._attach(leader, "leader")

    def attach_support(self, support: "Unit") -> "Unit":
        """Return a NEW combined unit (originals untouched). The support's
        leader_effects become active on the whole combined unit. Fills the
        support slot, leaving any attached leader in place."""
        if not self.can_support(support):
            raise ValueError(f"{support.name} cannot support {self.name}")
        return self._attach(support, "support")

    # ---------- combat view ----------

    def against(self, defender: "Unit" = None, context=None,
                role: str = "attacker"):
        """Build an immutable CombatView of this unit with all static
        ability conditions evaluated against (defender, context).
        role: 'attacker' or 'defender' (for profileRole conditions)."""
        import modifier_engine
        return modifier_engine.build_view(self, defender, context, role)

    def __repr__(self):
        return f"Unit({self.name!r}, {len(self.models())} model groups)"


# ---------- loader from native format ----------

def _as_dicts(items):
    """Ability list where any legacy bare-name string is wrapped into an
    ability dict (native_format normalises on load; this guards direct
    callers that pass an un-normalised dict)."""
    from native_format import wrap_ability
    return [wrap_ability(x) if isinstance(x, str) else x
            for x in (items or [])]


def units_from_native(native: dict) -> list:
    """Build Unit objects from a native-format dict (v2 with 'armies';
    a bare {'units': [...]} dict is accepted as a single unnamed army).
    Each Unit gets an 'army' attribute with its army name."""
    out = []
    armies = native.get("armies",
                        [{"name": None, "units": native.get("units", [])}])
    for army in armies:
        for u in army.get("units", []):
            models = []
            for md in u.get("models", []):
                weapons = [Weapon(
                    name=w.get("name", "?"), wtype=w.get("type", "Ranged"),
                    A=w.get("A"),
                    skill=w.get("WS") if w.get("type") == "Melee" else w.get("BS"),
                    S=w.get("S"), AP=w.get("AP"), D=w.get("D"), RNG=w.get("RNG"),
                    count=w.get("count", 1), keywords=w.get("keywords", []),
                    abilities=w.get("abilities", []))
                    for w in md.get("weapons", [])]
                models.append(Model(
                    name=md.get("name", "?"),
                    model_count=md.get("model_count", 1),
                    M=md.get("M"), T=md.get("T"), Sv=md.get("Sv"), W=md.get("W"),
                    LD=md.get("LD"), OC=md.get("OC"),
                    invuln=md.get("invuln"), fnp=md.get("fnp"),
                    keywords=md.get("keywords", []), weapons=weapons,
                    abilities=md.get("abilities", [])))
            # core_abilities / faction_abilities are stored separately (an
            # organisational distinction) but fed to the engine as ordinary
            # unit-scope abilities, so every dynamic applies to them alike.
            # _as_dicts tolerates legacy name-string entries (files not
            # loaded through native_format.load) by wrapping them.
            unit = Unit(
                name=u.get("name", "?"), models=models,
                keywords=u.get("keywords", []),
                abilities=(_as_dicts(u.get("abilities"))
                           + _as_dicts(u.get("core_abilities"))
                           + _as_dicts(u.get("faction_abilities"))),
                points=u.get("points", 0),
                leadership=u.get("leadership", []),
                support=u.get("support", []),
                leader_effects=u.get("leader_effects", []),
                apply_leader_effects_to_self=bool(
                    u.get("apply_leader_effects_to_self", False)),
                profile_name=u.get("profile_name"),
                damageable=bool(u.get("damageable", False)),
                leader_slots=u.get("leader_slots", 1),
                support_slots=u.get("support_slots", 1),
                unit_composition=u.get("unit_composition", ""),
                wargear_options=u.get("wargear_options", ""),
                notes=u.get("notes", ""))
            # Models inherit their unit's keywords by default; their own
            # keywords add to (or, with '-TOKEN', suppress) the inherited
            # set via Model.effective_keywords().
            for m in models:
                m.inherited_keywords = list(unit.keywords)
            unit.army = army.get("name")
            out.append(unit)
    return out
