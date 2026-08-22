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
    on their own axis only because those same abilities can give them a
    different damage law from the ordinary events;
  * mortal wounds that DO spill are pooled and applied at the END of
    the whole activation, one point at a time, passing from a destroyed
    model to the next.

What it does NOT model is the players' freedom: precision weapons
picking out a character, models out of visibility, an opponent choosing
which model to eat a wound with. Those are choices, not probabilities,
and the result is offered as an estimate.

State. Because allocation always fills one model before moving on, the
target unit is described by a single number T = wounds still standing:
the front model has ((T-1) mod W) + 1 wounds left and n - ceil(T / W)
models are already dead. The mortal pool M is carried alongside as the
second half of the state, since it stays correlated with T through the
attacks that produced both; it is spent only at the end.

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


def _apply_event(state: dict, table: list) -> dict:
    """One damage event applied to the whole state distribution. Only
    the wounds axis moves; the mortal pool is untouched."""
    out = {}
    for (t, m), p in state.items():
        for t2, q in table[t].items():
            key = (t2, m)
            out[key] = out.get(key, 0.0) + p * q
    return out


def _iterates(state: dict, table: list, upto: int) -> list:
    """[state, E(state), E2(state), ...] up to 'upto' damage events."""
    out = [state]
    for _ in range(upto):
        out.append(_apply_event(out[-1], table))
    return out


def _attack_op(state: dict, per_attack, joint: bool, tables, mcap: int):
    """One attack: its damage events land on the models, the mortal
    wounds that spill go into the pool.

    'per_attack' is the PMF of the number of damage events, or - when
    'joint' - the joint PMF {(norm, dev, pool): p}. 'tables' is the
    ordinary event operator, or the (ordinary, devastating) pair.
    """
    if not joint:
        acc, cur = {}, state
        for k, p in enumerate(per_attack):
            if p:
                for key, q in cur.items():
                    acc[key] = acc.get(key, 0.0) + p * q
            if k < len(per_attack) - 1:
                cur = _apply_event(cur, tables)
        return acc
    t_norm, t_dev = tables
    # Ordinary events first, then the devastating ones: within a single
    # attack the two only differ when a mortal-wound ability gives them
    # different damage laws, and then their relative order changes just
    # how much damage is wasted on the model that dies in between.
    norm_steps = _iterates(state, t_norm, max(k[AX_NORM]
                                              for k in per_attack))
    acc, cache = {}, {}
    for key, p in per_attack.items():
        kn, kd, m = key
        got = cache.get((kn, kd))
        if got is None:
            got = _iterates(norm_steps[kn], t_dev, kd)[kd]
            cache[(kn, kd)] = got
        for (t, pool), q in got.items():
            dest = (t, min(mcap, pool + m))
            acc[dest] = acc.get(dest, 0.0) + p * q
    return acc


def apply_weapon(state: dict, alloc: dict, w: int, tmax: int) -> dict:
    """Fire one weapon into a unit whose state distribution is 'state'.

    alloc = {'per_attack', 'joint', 'event_damage', 'attacks_pmf',
    'single'} as produced by attack_math.analyze_weapon(alloc=True).
    """
    joint = bool(alloc.get("joint"))
    tables = event_table(w, tmax, alloc["event_damage"])
    if joint:
        tables = (tables, event_table(w, tmax,
                                      alloc.get("event_damage_dev")
                                      or alloc["event_damage"]))
    attacks, per_attack = alloc["attacks_pmf"], alloc["per_attack"]

    def step(st, law):
        return _attack_op(st, law, joint, tables, tmax)

    single = alloc.get("single")
    if single:
        # ONE re-roll for the whole activation: with probability
        # (1-p_fail)^k none of the k attacks failed and there is nothing
        # to re-roll; the rest of the mass gets one extra attack. Both
        # branches are tracked, exactly as the damage chain does, so the
        # extra never lands on a sequence where nothing failed.
        pf, ok_law, x_law = (single["p_fail"], single["per_attack_ok"],
                             single["extra"])
        cur_ok = dict(state)
    acc, cur = {}, dict(state)
    for k, pk in enumerate(attacks):
        if pk:
            if single and k:
                w0 = (1.0 - pf) ** k
                rest = {}
                for key, p in cur.items():
                    v = p - w0 * cur_ok.get(key, 0.0)
                    if v > 0.0:
                        rest[key] = v
                part = step(rest, x_law)
                for key, p in cur_ok.items():
                    part[key] = part.get(key, 0.0) + w0 * p
            else:
                part = cur
            for key, p in part.items():
                acc[key] = acc.get(key, 0.0) + pk * p
        if k < len(attacks) - 1:
            cur = step(cur, per_attack)
            if single:
                cur_ok = step(cur_ok, ok_law)
    return acc


def resolve(allocs, wounds: int, models: int) -> dict:
    """Fire every weapon into one target unit and read off what happened.

    'allocs' are the per-weapon allocation dicts, IN FIRING ORDER: a
    weapon fires into the unit the previous ones left behind, which is
    what makes the wasted damage add up the way it does at the table.
    The spilling mortal pool built up along the way is spent last, as
    the rules require.

    Returns {'kills', 'removed', 'p_wipe'}:
      kills    PMF of the number of models destroyed;
      removed  PMF of the wounds ACTUALLY taken off the unit - damage
               wasted on a model that died with wounds to spare is not
               counted, so this is the exact version of what the 'net
               damage' column estimates by capping each event at W;
      p_wipe   probability the unit is wiped out.
    """
    w, n = max(1, int(wounds or 1)), max(1, int(models or 1))
    tmax = w * n
    state = {(tmax, 0): 1.0}               # untouched unit, empty pool
    for alloc in allocs:
        if alloc:
            state = apply_weapon(state, alloc, w, tmax)
    kills, removed = [0.0] * (n + 1), [0.0] * (tmax + 1)
    for (t, pool), p in state.items():
        if p:
            left = max(0, t - pool)
            kills[kills_from_total(left, w, n)] += p
            removed[tmax - left] += p
    # The joint convolutions drop masses below their epsilon, so the
    # vectors can drift a fraction of a part per million off 1.
    mass = sum(kills)
    if mass:
        kills = [p / mass for p in kills]
        removed = [p / mass for p in removed]
    return {"kills": kills, "removed": removed,
            "p_wipe": kills[-1] if kills else 0.0}


def kills_pmf(allocs, wounds: int, models: int) -> list:
    """PMF of the number of models destroyed (see resolve())."""
    return resolve(allocs, wounds, models)["kills"]


def _mean_event_damage(alloc: dict) -> float:
    """Average size of one damage event of this weapon."""
    dmg = (alloc or {}).get("event_damage") or [1.0]
    return sum(v * p for v, p in enumerate(dmg))


def best_order(allocs, wounds: int, models: int, candidates=None):
    """Pick a firing order that kills more models, without searching
    every permutation.

    Order matters because a big damage event wastes its excess on a
    model that was already wounded, so the rule of thumb is to fire the
    heavy weapons first, while the models are at full wounds, and let
    the light ones finish off what is left. That is a heuristic, not a
    theorem, so the two orders it suggests are simply evaluated against
    the one the caller gave and the best of the three is returned - the
    exact optimum would cost a factorial number of chain runs for a
    gain that is usually a fraction of a model.

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
    best_mean = sum(k * p for k, p in enumerate(given["kills"]))
    for cand in cands:
        if list(cand) == best_idx:
            continue
        res = resolve([allocs[i] for i in cand], wounds, models)
        mean = sum(k * p for k, p in enumerate(res["kills"]))
        if mean > best_mean + 1e-12:
            best_idx, best_res, best_mean = list(cand), res, mean
    return best_idx, best_res, given


def survivors_pmf(kills: list, models: int) -> list:
    """Mirror image of kills_pmf: the number of models left standing."""
    n = max(1, int(models or 1))
    out = [0.0] * (n + 1)
    for k, p in enumerate(kills):
        out[n - k] += p
    return out
