"""How many MODELS an attack sequence destroys.

Total damage is not the currency a player thinks in: eleven damage into
a squad of two-wound models may be five dead models or four, depending
on how it lands. Nor is it a division - flooring the total damage by W
systematically OVERSTATES the kills, because it ignores the damage
wasted on a model that dies with wounds to spare.

The chain is exact under the allocation the rules prescribe:

  * damage is allocated one EVENT at a time - one successful attack -
    onto a single model until it is destroyed, then onto the next.
    Three hits of 2 damage are not one hit of 6: each is capped
    separately by the wounds left on the model it lands on, so the
    number of events matters as much as their total;
  * DEVASTATING WOUNDS produces mortal wounds - every ability keyed on
    mortal wounds applies to them, and attack_math thins them
    accordingly - but they are ALLOCATED like ordinary damage: onto one
    model, capped by its wounds, with no spill-over. They are counted
    on their own axis because those same abilities can give them a
    different damage law from the ordinary events, and because 06.02
    puts them in a LATER PHASE: "when resolving attack dice, if those
    attacks inflict a mixture of both mortal wounds and normal damage,
    resolve all of the normal damage first, then resolve all of the
    mortal wounds". "Those attacks" is the whole group of identical
    attacks - one weapon profile against one target - so the phase runs
    across the weapon and not inside a single attack. See _flush_dev;
  * mortal wounds that DO spill are pooled and applied at the END OF
    EACH WEAPON (11th ed. 4.3: "at the end of each group of identical
    attacks", not at the end of the unit's shooting), one point at a
    time, passing from a destroyed model to the next. See _spend_pool.

What it does NOT model is the players' freedom: precision weapons
picking out a character, models out of visibility, an opponent choosing
which model to eat a wound with. Those are choices, not probabilities,
and the result is offered as an estimate.

State. Because allocation always fills one model before moving on, the
target unit is described by a single number T = wounds still standing:
the front model has ((T-1) mod W) + 1 wounds left and n - ceil(T / W)
models are already dead. The mortal pool M is carried alongside as the
second half of the state, since it stays correlated with T through the
attacks that produced both; it is spent at the end of the weapon that
built it, which is also what leaves M at zero between weapons.

Inside a weapon the state carries a THIRD number, D: how many
devastating events the attacks so far still owe. They cannot be
allocated as they are produced, because 06.02 puts them after every
ordinary event of the same weapon, and they cannot be counted apart
from T either, because how many of them one attack yields is
correlated with how much ordinary damage that same attack did. So they
are carried and spent at the end of the weapon, before the pool.

The per-attack laws come from attack_math.analyze_weapon(alloc=True);
everything here works on plain dicts and lists, so the module carries
no dependency of its own.
"""


def front_wounds(total: int, w: int) -> int:
    """Wounds left on the model the next damage event will hit."""
    return ((total - 1) % w) + 1 if total > 0 else 0


def kills_from_total(total: int, w: int, n: int) -> int:
    """Models destroyed when 'total' wounds are still standing."""
    return n - -(-total // w)          # n - ceil(total / w)


AX_NORM, AX_DEV, AX_POOL = 0, 1, 2


def event_table(w: int, tmax: int, damage) -> list:
    """table[t] = {t': p}: the unit's remaining wounds after ONE damage
    event, whose size is drawn from 'damage'. Built once per weapon."""
    table = []
    for t in range(tmax + 1):
        if t == 0:
            table.append({0: 1.0})
            continue
        left, row = front_wounds(t, w), {}
        for d, p in enumerate(damage):
            if p:
                dest = t - min(d, left)
                row[dest] = row.get(dest, 0.0) + p
        table.append(row)
    return table


def _merge(acc: dict, src: dict, weight: float = 1.0) -> None:
    """acc += weight * src, in place, both in the grouped layout."""
    for t, row in src.items():
        dst = acc.get(t)
        if dst is None:
            acc[t] = (dict(row) if weight == 1.0 else
                      {c: p * weight for c, p in row.items()})
            continue
        for c, p in row.items():
            dst[c] = dst.get(c, 0.0) + p * weight


def _apply_event(state: dict, table: list) -> dict:
    """One damage event applied to the whole state distribution.

    GROUPED LAYOUT, used inside apply_weapon only: {t: {carried: p}},
    where 'carried' is the mortal pool, or the (pool, owed) pair when
    the devastating axis is alive. Only T moves, so a whole carried row
    is scaled and merged as a block instead of one composite key at a
    time - which is the point of the layout: the inner loop never
    builds or hashes a tuple.
    """
    out = {}
    for t, row in state.items():
        for t2, q in table[t].items():
            dst = out.get(t2)
            if dst is None:
                out[t2] = {c: p * q for c, p in row.items()}
                continue
            for c, p in row.items():
                dst[c] = dst.get(c, 0.0) + p * q
    return out


def _iterates(state: dict, table: list, upto: int) -> list:
    """[state, E(state), E2(state), ...] up to 'upto' damage events."""
    out = [state]
    for _ in range(upto):
        out.append(_apply_event(out[-1], table))
    return out


def _attack_op(state: dict, per_attack, joint: bool, tables, mcap: int,
               dev: bool = False):
    """One attack: its damage events land on the models, the mortal
    wounds that spill go into the pool.

    'per_attack' is the PMF of the number of damage events, or - when
    'joint' - the joint PMF {(norm, dev, pool): p}. 'tables' is the
    ordinary event operator, or the (ordinary, devastating) pair.
    'dev' says whether the state carries the owed-events axis; see
    apply_weapon. States are in the grouped layout throughout.
    """
    if not joint:
        acc, cur = {}, state
        for k, p in enumerate(per_attack):
            if p:
                _merge(acc, cur, p)
            if k < len(per_attack) - 1:
                cur = _apply_event(cur, tables)
        return acc
    t_norm = tables[0]
    # Only the ORDINARY events of this attack are allocated here. The
    # devastating ones are counted onto the owed axis and spent at the
    # end of the weapon by _flush_dev, because 06.02 resolves all the
    # normal damage of a group of identical attacks before any of its
    # mortal wounds - allocating them attack by attack lands them on a
    # model the later attacks had not wounded yet, which changes how
    # much of both is wasted.
    #
    # BOTH carried counters are capped at T, the wounds still standing.
    # A pool point takes exactly one wound off and an allocation event
    # at least one - the event damage law is conditioned on getting
    # through - so T of either already leave nothing, and T only goes
    # down between here and the readout. Uncapped they would run to the
    # number of ATTACKS and the state would grow with them; capped, the
    # (T, carried) rectangle is a triangle.
    #
    # The pool cap also ESTABLISHES the invariant pool <= T that
    # _spend_pool and _read_state rely on. It used to be a flat cap and
    # those two clamped with max(0, ...) instead - a clamp that hid,
    # rather than reported, a pool the chain had let run past the unit.
    # Now the bound is stated once, here, and checked where it is used.
    norm_steps = _iterates(state, t_norm, max(k[AX_NORM]
                                              for k in per_attack))
    acc = {}
    for key, p in per_attack.items():
        kn, kd, m = key
        for t, row in norm_steps[kn].items():
            dst = acc.get(t)
            if dst is None:
                dst = acc[t] = {}
            if not dev:
                for pool, q in row.items():
                    c = min(t, pool + m)
                    dst[c] = dst.get(c, 0.0) + p * q
                continue
            for (pool, owed), q in row.items():
                c = (min(t, pool + m), min(t, owed + kd))
                dst[c] = dst.get(c, 0.0) + p * q
    return acc


def _flush_dev(state: dict, table: list) -> dict:
    """The devastating events a weapon owes, allocated after every
    ordinary event of that same weapon (06.02), and the owed axis
    dropped from the carried key.

    Evaluated as a Horner scheme over the count: with f_d the slice of
    the state owing exactly d events, the answer is sum_d DEV^d(f_d),
    read as R_d = DEV(R_{d+1}) + f_d from the top down. That costs ONE
    operator application per distinct count instead of one per (count,
    state) pair, which matters because the count reaches the wounds the
    unit still has.
    """
    slices = {}
    for t, row in state.items():
        for (pool, owed), p in row.items():
            dst = slices.setdefault(owed, {}).setdefault(t, {})
            dst[pool] = dst.get(pool, 0.0) + p
    out = {}
    for owed in range(max(slices) if slices else 0, -1, -1):
        if out:
            out = _apply_event(out, table)
        _merge(out, slices.get(owed, {}))
    return out


def _group(state: dict, dev: bool) -> dict:
    """{(t, pool): p} -> the grouped layout {t: {carried: p}}."""
    out = {}
    for (t, pool), p in state.items():
        c = (pool, 0) if dev else pool
        row = out.setdefault(t, {})
        row[c] = row.get(c, 0.0) + p
    return out


def _ungroup(state: dict) -> dict:
    """The grouped layout back to {(t, pool): p}, with the pool capped
    at T on the way out.

    _attack_op sets that cap, but _flush_dev then takes T DOWN while the
    pool rides along, so the last place the invariant can break is here
    - and here is where it is restored, before any caller sees the
    state. Capping is exact for the same reason it was in _attack_op: a
    pool bigger than the wounds left spends the same as one exactly as
    big.
    """
    out = {}
    for t, row in state.items():
        for pool, p in row.items():
            key = (t, min(t, pool))
            out[key] = out.get(key, 0.0) + p
    return out


def apply_weapon(state: dict, alloc: dict, w: int, tmax: int) -> dict:
    """Fire one weapon into a unit whose state distribution is 'state'.

    alloc = {'per_attack', 'joint', 'event_damage', 'attacks_pmf',
    'single'} as produced by attack_math.analyze_weapon(alloc=True).

    In and out the state is the plain {(t, pool): p} the rest of the
    module reads. The grouped layout lives INSIDE this function only:
    it is what makes the joint chain affordable, and confining it here
    is what keeps _spend_pool, _read_state and resolve unaware of it.
    """
    joint = bool(alloc.get("joint"))
    tables = event_table(w, tmax, alloc["event_damage"])
    per_attack = alloc["per_attack"]
    # The joint law is also built for a weapon whose only mortal wounds
    # SPILL - those go to the pool, never to the owed axis - so the
    # axis is carried only when some attack can actually owe an event.
    # Without this guard the spilling weapons, which are the expensive
    # ones already, would pay for a counter that is always zero.
    dev = joint and any(k[AX_DEV] for k in per_attack)
    if joint:
        tables = (tables, event_table(w, tmax,
                                      alloc.get("event_damage_dev")
                                      or alloc["event_damage"]))
    # The owed axis enters at zero and does not survive the weapon:
    # 06.02 scopes the phase to one group of identical attacks.
    state = _group(state, dev)
    attacks = alloc["attacks_pmf"]

    def step(st, law):
        return _attack_op(st, law, joint, tables, tmax, dev)

    # ONE re-roll for the whole activation: with probability
    # (1-p_fail)^k none of the k attacks failed and there is nothing to
    # re-roll; the rest of the mass gets one extra attack. Both branches
    # are tracked, exactly as the damage chain does, so the extra never
    # lands on a sequence where nothing failed.
    #
    # All four names are bound unconditionally, even though only the
    # 'single' path reads them: a name that exists only inside an 'if'
    # and is read outside it works right up until a guard is edited, and
    # then fails as a NameError rather than as a wrong number.
    single = alloc.get("single")
    pf = single["p_fail"] if single else 0.0
    ok_law = single["per_attack_ok"] if single else per_attack
    x_law = single["extra"] if single else per_attack
    cur_ok = {t: dict(row) for t, row in state.items()} if single else {}
    acc, cur = {}, {t: dict(row) for t, row in state.items()}
    for k, pk in enumerate(attacks):
        if pk:
            if single and k:
                w0 = (1.0 - pf) ** k
                rest = {}
                for t, row in cur.items():
                    ok_row = cur_ok.get(t) or {}
                    keep = {}
                    for c, p in row.items():
                        v = p - w0 * ok_row.get(c, 0.0)
                        if v > 0.0:
                            keep[c] = v
                    if keep:
                        rest[t] = keep
                part = step(rest, x_law)
                _merge(part, cur_ok, w0)
            else:
                part = cur
            _merge(acc, part, pk)
        if k < len(attacks) - 1:
            cur = step(cur, per_attack)
            if single:
                cur_ok = step(cur_ok, ok_law)
    # After the attack counts are mixed, not inside the loop: the phase
    # ends with the WEAPON, so a sequence of six attacks owes its six
    # possible devastating events all at once and not two at a time.
    return _ungroup(_flush_dev(acc, tables[1]) if dev else acc)


def _spend_pool(state: dict) -> dict:
    """The spilling mortal pool spent, and the state left with none.

    11th ed. 4.3 resolves mortal wounds as a batch at the END OF EACH
    GROUP OF IDENTICAL ATTACKS - one weapon profile against one target -
    and not at the very end of the unit's shooting, which is where the
    10th edition put them. That is also what the dice resolver does:
    attack_resolve.resolve_saves() spends its spill_pool before it
    returns, so the next weapon meets the unit the mortals already went
    through.

    Spending is a plain subtraction: a spilling mortal wound passes from
    a destroyed model to the next, so none of it is ever wasted and the
    unit's remaining wounds simply go down by the size of the pool. What
    the TIMING changes is the model the NEXT weapon's damage events land
    on, and therefore how much of that damage is wasted - which is why
    doing it here rather than at the readout is not cosmetic.

    A pool can never be bigger than the wounds still standing: every
    state the chain hands out has been through the cap in _attack_op and
    the one in _ungroup. So the subtraction needs no floor, and the
    assertion below says so out loud - a clamp here would have turned a
    broken cap into a plausible number instead of an error.
    """
    out = {}
    for (t, pool), p in state.items():
        assert pool <= t, f"pool {pool} past the {t} wounds still standing"
        key = (t - pool, 0)
        out[key] = out.get(key, 0.0) + p
    return out


def _read_state(state: dict, w: int, n: int, tmax: int):
    """(kills, removed) laws of a chain state, normalised.

    Factored out of resolve() so that the SAME readout can be taken from
    an intermediate state, which is what makes the per-prefix wipe
    probability cost a pass over the state instead of a re-run of the
    whole chain.

    Same invariant as _spend_pool, and the same reason for asserting it
    rather than clamping: this readout is the last thing between the
    chain and the figures the user reads.
    """
    kills, removed = [0.0] * (n + 1), [0.0] * (tmax + 1)
    for (t, pool), p in state.items():
        if p:
            assert pool <= t, (f"pool {pool} past the {t} wounds "
                               "still standing")
            left = t - pool
            kills[kills_from_total(left, w, n)] += p
            removed[tmax - left] += p
    # The joint convolutions drop masses below their epsilon, so the
    # vectors can drift a fraction of a part per million off 1.
    mass = sum(kills)
    if mass:
        kills = [p / mass for p in kills]
        removed = [p / mass for p in removed]
    return kills, removed


def resolve(allocs, wounds: int, models: int) -> dict:
    """Fire every weapon into one target unit and read off what happened.

    'allocs' are the per-weapon allocation dicts, IN FIRING ORDER: a
    weapon fires into the unit the previous ones left behind, which is
    what makes the wasted damage add up the way it does at the table.
    The spilling mortal pool a weapon builds up is spent before the next
    one fires (4.3), so it is part of what that weapon leaves behind.

    Returns {'kills', 'removed', 'p_wipe', 'spent'}:
      kills    PMF of the number of models destroyed;
      removed  PMF of the wounds ACTUALLY taken off the unit - damage
               wasted on a model that died with wounds to spare is not
               counted, so this is the exact version of what the 'net
               damage' column estimates by capping each event at W;
      p_wipe   probability the unit is wiped out;
      spent    EXPECTED NUMBER OF WEAPONS the unit costs to destroy,
               summed as the probability it is still standing before
               each weapon fires. A weapon that fires into a unit which
               is already gone was not needed, and the ones after it
               could have been pointed somewhere else - which is the
               thing a firing order is actually chosen for. It equals
               len(allocs) when the unit never falls, so it is only
               meaningful against another order of the SAME weapons.
    """
    w, n = max(1, int(wounds or 1)), max(1, int(models or 1))
    tmax = w * n
    state = {(tmax, 0): 1.0}               # untouched unit, empty pool
    spent = 0.0
    for alloc in allocs:
        # Read BEFORE firing: this weapon was spent on whatever was
        # still standing when its turn came.
        spent += 1.0 - _read_state(state, w, n, tmax)[0][-1]
        if alloc:
            # ...and the mortal wounds this weapon spilled are spent
            # before the next one fires (4.3), so the next weapon's
            # events land on the model they left wounded.
            state = _spend_pool(apply_weapon(state, alloc, w, tmax))
    kills, removed = _read_state(state, w, n, tmax)
    return {"kills": kills, "removed": removed, "spent": spent,
            "p_wipe": kills[-1] if kills else 0.0}


def kills_pmf(allocs, wounds: int, models: int) -> list:
    """PMF of the number of models destroyed (see resolve())."""
    return resolve(allocs, wounds, models)["kills"]


def _mean_event_damage(alloc: dict) -> float:
    """Average size of one damage event of this weapon."""
    dmg = (alloc or {}).get("event_damage") or [1.0]
    return sum(v * p for v, p in enumerate(dmg))


def order_score(res: dict):
    """The key a firing order is judged by. Bigger is better.

    Two figures, in order of precedence:

      1. FEWER WEAPONS SPENT. What a firing order is chosen for is not
         how much this unit suffers - the same weapons are fired either
         way - but how many of them the job took, because the ones still
         loaded when the target falls can be pointed somewhere else.
      2. MORE WOUNDS REMOVED, to break the ties. When the target
         survives the whole volley, 'spent' is the number of weapons
         whatever the order and says nothing; the wounds actually taken
         off still do.

    Models killed is deliberately NOT in the key, and used to be the
    whole of it. It cannot express either idea: a shot fired into a unit
    that is already gone kills nobody but is spent all the same, and the
    damage wasted on an over-killed model never shows up in a body
    count. The two are not always aligned - an order that frees a weapon
    can kill slightly fewer models - and where they disagree this
    prefers the freed weapon, which is the question the player asked.
    """
    removed = sum(k * p for k, p in enumerate(res["removed"]))
    return (-res["spent"], removed)


def best_order(allocs, wounds: int, models: int, candidates=None):
    """Pick a firing order that spends fewer weapons on this target,
    without searching every permutation.

    Order matters because a big damage event wastes its excess on a
    model that was already wounded, so the rule of thumb is to fire the
    heavy weapons first, while the models are at full wounds, and let
    the light ones finish off what is left. That is a heuristic, not a
    theorem, so the two orders it suggests are simply evaluated against
    the one the caller gave and the best of the three is returned - the
    exact optimum would cost a factorial number of chain runs for a
    gain that is usually a fraction of a weapon.

    See order_score for what "best" means here. Ties keep the order the
    caller gave: a suggestion has to be worth the player's attention.

    Returns (order, result, given): 'order' is a list of indices into
    'allocs', 'result' is resolve() for that order and 'given' is
    resolve() for the order the caller passed, so the gain is readable
    without running the chain again.
    """
    idx = list(range(len(allocs)))
    given = resolve(allocs, wounds, models)
    if len(allocs) < 2:
        return idx, given, given
    heavy = sorted(idx, key=lambda i: -_mean_event_damage(allocs[i]))
    cands = list(candidates) if candidates else [heavy,
                                                 list(reversed(heavy))]
    best_idx, best_res = idx, given
    best_key = order_score(given)
    for cand in cands:
        if list(cand) == best_idx:
            continue
        res = resolve([allocs[i] for i in cand], wounds, models)
        key = order_score(res)
        if key > best_key:
            best_idx, best_res, best_key = list(cand), res, key
    return best_idx, best_res, given


def survivors_pmf(kills: list, models: int) -> list:
    """Mirror image of kills_pmf: the number of models left standing."""
    n = max(1, int(models or 1))
    out = [0.0] * (n + 1)
    for k, p in enumerate(kills):
        out[n - k] += p
    return out
