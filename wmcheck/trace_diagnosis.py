"""Diagnose incomplete RF/CO provenance logs with an exact support oracle.

The client reports all still feasible read sources and order directions. For
an inconsistent log it computes a deletion-minimal conflict and every repair
that changes exactly one recorded field. It never treats a witness as the set
of all possibilities, or assumes independent supports can be combined.
"""


def support_snapshot(registry, query, observations=()):
    ok, forced = query(tuple(observations))
    if not ok:
        return dict(consistent=False)
    sources = {r: [] for r in registry.inst.reads}
    orders = []
    for v, (kind, a, b) in registry.by_id.items():
        if kind == 'rf' and -v not in forced:
            sources[b].append(a)
        elif kind == 'co':
            orders.append(dict(pair=[a, b], directions=([1] if v in forced else
                                [-1] if -v in forced else [-1, 1])))
    return dict(consistent=True, sources=sources, orders=orders, forced=sorted(forced))


def diagnose(registry, query, observations):
    """One RF field records a source; one CO field records a direction.

    RF observations must be positive source identities. For a withdrawn RF
    field one support query returns *all* alternative sources for that read.
    Repairs are individually feasible, not necessarily jointly feasible.
    """
    observations = tuple(observations)
    if len(set(observations)) != len(observations):
        raise ValueError('Duplicate observations')
    for lit in observations:
        if abs(lit) not in registry.by_id or (lit < 0 and registry.by_id[-lit][0] == 'rf'):
            raise ValueError('Expected positive RF source or signed CO direction')
    snapshot = support_snapshot(registry, query, observations)
    if snapshot['consistent']:
        return dict(snapshot=snapshot, conflict=[], repairs=[])
    core = list(observations)
    for lit in observations:
        candidate = tuple(x for x in core if x != lit)
        if not query(candidate)[0]:
            core.remove(lit)
    repairs = []
    for lit in observations:
        remaining = tuple(x for x in observations if x != lit)
        ok, forced = query(remaining)
        if not ok:
            continue
        kind, a, b = registry.by_id[abs(lit)]
        if kind == 'rf':
            replacements = [registry.literal(('rf', w, b)) for w in registry.inst.candidates[b]
                            if w != a and -registry.literal(('rf', w, b)) not in forced]
        else:
            replacements = [-lit] if lit not in forced else []
        repairs.append(dict(remove=lit, replacements=replacements))
    return dict(snapshot=snapshot, conflict=core, repairs=repairs)


def publication_logs(inst, rounds):
    """Generated incomplete logs for the repeated-publication trace family.

    Each episode compares an early/late publication claim against a payload
    source and a recorded CO direction. These are controlled test logs, not
    production telemetry. The client itself is independent of this generator.
    """
    from .ra import RARegistry
    registry = RARegistry(inst)
    logs = [dict(name='unobserved', observations=[])]
    for stage in range(2, rounds + 1):
        for t in range(2):
            loc = 'x' if t == 0 else 'y'
            own = registry.literal(('rf', f't{t}_{stage}_{loc}', f't{t}_{stage}_read'))
            early = registry.literal(('rf', f't{1-t}_{stage-1}_pub0', f't{t}_{stage}_wait'))
            late = registry.literal(('rf', f't{1-t}_{stage-1}_pub1', f't{t}_{stage}_wait'))
            order = registry.literal(('co', f't{1-t}_{stage-1}_{loc}', f't{t}_{stage}_{loc}'))
            for name, obs in (('early', [own, early]), ('late', [own, late]),
                              ('early_inverted', [own, early, -order]),
                              ('late_inverted', [own, late, -order])):
                logs.append(dict(name=f's{stage}_t{t}_{name}', observations=obs))
    return logs
