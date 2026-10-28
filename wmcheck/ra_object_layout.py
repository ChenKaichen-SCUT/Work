"""Check address ownership and acyclic object traversal, then build a layout.

The certificate concerns candidate incidence, not a selected execution or an
assumed happens-before order. Initial writes remain original RF/CO events.
Compilation must use elide_init_hb=True for the advertised interface bound.
"""
from collections import Counter, defaultdict
import heapq


def object_layout(inst, location_owner):
    locations = {e.loc for e in inst.events}
    if set(location_owner) != locations:
        raise ValueError('Every address needs exactly one object owner')
    owner = {e.id: location_owner[e.loc] for e in inst.events}
    objects = set(owner.values())
    adjacency = {obj: set() for obj in objects}
    indegree = dict.fromkeys(objects, 0)
    for a, b in inst.sb:
        u, v = owner[a], owner[b]
        if u != v and v not in adjacency[u]:
            adjacency[u].add(v)
            indegree[v] += 1
    # Stable string object identifiers are part of the input certificate.
    if any(not isinstance(obj, str) for obj in objects):
        raise ValueError('Object identifiers must be strings')
    ready = [obj for obj in objects if not indegree[obj]]
    heapq.heapify(ready)
    topo = []
    while ready:
        obj = heapq.heappop(ready)
        topo.append(obj)
        for nxt in sorted(adjacency[obj]):
            indegree[nxt] -= 1
            if not indegree[nxt]:
                heapq.heappush(ready, nxt)
    if len(topo) != len(objects):
        raise ValueError('Object traversal has a directed cycle (including reuse)')
    initial = set(inst.initial)
    buckets = defaultdict(list)
    for i in inst.initial:
        buckets[owner[i]].append(i)
    for seq in inst.threads:
        for v in seq:
            buckets[owner[v]].append(v)
    order = tuple(v for obj in topo for v in buckets[obj])
    noninitial = Counter(owner[v] for v in inst.event if v not in initial)
    initials = Counter(owner[v] for v in initial)
    p = sum(bool(t) for t in inst.threads)
    c = max(noninitial.values(), default=0)
    s = max(initials.values(), default=0)
    return dict(order=order, object_order=tuple(topo), event_owner=owner,
                threads=p, objects=len(objects), max_events_per_object=c,
                max_initials_per_object=s, interface_bound=p+c+s,
                requires_elide_init_hb=True)
