"""A shared stand-in for the attacker unit view.

analyzer_core.select_weapons_split and close_quarters_attacker read
three things off the view: its own keyword list, its model groups, and
one keyword set PER MODEL (Unit.model_keywords, which reads each model
against the unit it came from rather than against a merged one). Three
test files used to carry their own hand-written copy of that shape, and
when model_keywords() joined the contract two of them silently answered
the old one and the third failed at import time with an AttributeError
that said nothing about the cause.

So the shape lives here once. check_contract() below fails loudly if
the real Unit renames or drops any part of it, which turns the next
change into a clear message in one place instead of an AttributeError
in several.

This is a stub and not a real view on purpose: these tests are about
WHICH WEAPONS are selected, and building a roster, a Unit and a
modifier-engine view for each of two dozen weapon combinations would
bury the thing under test. Tests that are about the MERGE itself
(test_hazardous.py, the attached-unit section of test_close_quarters.py)
use real units built with Unit.attach_leader instead - a stub cannot
prove anything about a mechanism it is imitating.
"""
import testpaths                      # sets up sys.path to the engine src/
import unit_model as um


class Model:
    """One model group: the weapons it carries, and its own keywords."""

    def __init__(self, weapons=(), keywords=()):
        self.weapons = list(weapons)
        self.keywords = list(keywords)


class View:
    """A unit view with models() and model_keywords().

    Two ways to build one:

      View(weapons, keywords)          one model group carrying all the
                                       weapons, reading the unit's own
                                       keyword set - a single-datasheet
                                       unit;
      View(per_model=[(weapons, kws),  one group per entry, each with
                      ...])            its own keyword set - the shape
                                       an ATTACHED unit produces.

    With per_model, 'keywords' is the unit-level set (the UNION the
    merge produces) and is what close_quarters_attacker reads; the
    per-model sets are what the per-model rules read.
    """

    def __init__(self, weapons=(), keywords=(), per_model=None):
        if per_model is None:
            self._m = [Model(weapons, keywords)]
        else:
            self._m = [Model(ws, kws) for ws, kws in per_model]
        self.keywords = list(keywords)

    def models(self):
        return list(self._m)

    def model_keywords(self):
        return [set(m.keywords) for m in self._m]


def check_contract():
    """Fail if the real Unit no longer matches what this stub imitates."""
    missing = [name for name in ("models", "model_keywords",
                                 "bodyguard_models")
               if not callable(getattr(um.Unit, name, None))]
    if missing:
        raise AssertionError(
            f"unit_model.Unit no longer provides {missing}: the view "
            f"stub in viewstub.py imitates a contract that has changed, "
            f"so every test using it is now testing a shape the engine "
            f"does not have")
    for name in ("keywords", "models", "model_keywords"):
        if not hasattr(View((), ()), name):
            raise AssertionError(f"viewstub.View is missing {name}")


check_contract()
