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


def _entry_matches_keywords(entry, keywords):
    """True if a leadership/support ENTRY matches a unit's keyword list.
    Two datasheet conventions both occur, so either satisfies a match:
      (A) whole-entry: the entry equals a keyword -- Space Marines store the
          full unit name as a single keyword ('Assault Intercessor Squad').
      (B) word-by-word: EVERY word of the entry is some keyword -- T'au
          store split keywords ('Crisis','Fireknife','Battlesuit') while the
          entry is the full name 'Crisis Fireknife Battlesuits'.
    All comparisons use _kw_key (lowercased, singular/plural-insensitive).
    An empty entry never matches."""
    e = entry.strip()
    if not e:
        return False
    kw = {_kw_key(k) for k in keywords}
    # (A) whole-entry equals a keyword
    if _entry_key(e) in {_entry_key(k) for k in keywords}:
        return True
    # (B) every word of the entry is a keyword
    words = [_kw_key(w) for w in _re.split(r"\s+", e) if w.strip()]
    return bool(words) and all(w in kw for w in words)


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
                 support=None):
        self.name = name
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
        self.leader_effects = list(leader_effects or [])
        self.apply_leader_effects_to_self = apply_leader_effects_to_self
        self.attached_leader = None           # set on combined units only
        self.attached_support = None          # set on combined units only
        self.effects = []                     # populated only on combat views

    def is_leader(self) -> bool:
        """True only for a unit that BOTH can lead (non-empty leadership
        list) AND is currently attached to a unit. In practice this is
        the combined unit built by attach_leader (it inherits the
        leader's leadership list and carries attached_leader). A
        standalone, unattached leader returns False. Currently unused,
        kept for future rules expansions."""
        return bool(self.leadership) and self.attached_leader is not None

    # ---------- model access ----------

    def models(self):
        """All model groups: the unit's own, plus any attached leader's
        and attached support's (a unit may carry one of each)."""
        out = list(self._models)
        if self.attached_leader is not None:
            out += self.attached_leader.models()
        if self.attached_support is not None:
            out += self.attached_support.models()
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
        return _any_entry_matches(leader.leadership, self.keywords)

    def can_support(self, support: "Unit") -> bool:
        """True if 'support' can support this unit: some entry of the
        support's support list matches this unit's keywords. Mirrors
        can_attach for the separate support slot."""
        return _any_entry_matches(support.support, self.keywords)

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
        kept_leader = self.attached_leader
        kept_support = self.attached_support
        if slot == "leader":
            kept_leader = helper
        else:
            kept_support = helper
        combined = Unit(
            name=f"{self.name} + {helper.name}",
            models=base_models,
            keywords=sorted(base_keywords | set(helper.keywords)),
            abilities=base_abilities + helper.abilities,
            points=self.points + helper.points,
            leader_effects=base_effects + helper.leader_effects,
            apply_leader_effects_to_self=True,
            profile_name=self.profile_name,
            damageable=self.damageable,
            leadership=self.leadership or helper.leadership,
            support=self.support or helper.support)
        combined.attached_leader = kept_leader
        combined.attached_support = kept_support
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
