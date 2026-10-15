"""Fixed-event RA input. Separate from the historical block-ordered TSO API.

All non-initial writes are release; all reads acquire. No RMW, fences, SC,
non-atomics, dynamic addresses or optional events. Original RF/CO identities
are retained even when recognition proves their values constant.
"""
from dataclasses import dataclass
from itertools import combinations
from .model import Event


@dataclass
class RAInstance:
    events: tuple
    threads: tuple
    initial: tuple

    def __post_init__(self):
        self.event = {e.id: e for e in self.events}
        if len(self.event) != len(self.events):
            raise ValueError('Duplicate event identity')
        initial = set(self.initial)
        flat = [v for t in self.threads for v in t]
        if len(flat) != len(set(flat)) or set(flat) & initial or set(flat) | initial != set(self.event):
            raise ValueError('Threads and initialization must partition events')
        if any(e.kind not in ('R', 'W') or e.loc is None or
               (e.kind == 'W' and e.value is None) for e in self.events):
            raise ValueError('Only fixed-address RA events and constant writes are supported')
        locs = {e.loc for e in self.events}
        if len(initial) != len(locs) or {self.event[i].loc for i in initial} != locs:
            raise ValueError('Exactly one initialization write per address')
        if any(self.event[i].kind != 'W' for i in initial):
            raise ValueError('Initialization must write')
        for t in self.threads:
            if len({self.event[v].thread for v in t}) > 1:
                raise ValueError('Thread sequence mixes identities')
        owners = [self.event[t[0]].thread for t in self.threads if t]
        if len(owners) != len(set(owners)):
            raise ValueError('A thread must have one sequence')
        self.writes = tuple(e.id for e in self.events if e.kind == 'W')
        self.write_set = frozenset(self.writes)
        self.reads = tuple(e.id for e in self.events if e.kind == 'R')
        self.candidates = {r: tuple(w for w in self.writes
                                   if self.event[w].loc == self.event[r].loc
                                   and (self.event[r].value is None or
                                        self.event[w].value == self.event[r].value)) for r in self.reads}
        self.sb = {(a, b) for t in self.threads for a, b in zip(t, t[1:])}


class RARegistry:
    def __init__(self, inst):
        self.inst = inst
        keys = [('rf', w, r) for r in inst.reads for w in inst.candidates[r]]
        keys += [('co', a, b) for a, b in combinations(sorted(inst.writes), 2)
                 if inst.event[a].loc == inst.event[b].loc]
        self.by_id = dict(enumerate(keys, 1))
        self.by_key = {k: v for v, k in self.by_id.items()}
        self.nvars = len(keys)

    def literal(self, key):
        kind, a, b = key
        if kind == 'rf':
            return self.by_key.get(key, False)
        if kind != 'co':
            raise ValueError('Expected RF or CO')
        if a == b or a not in self.inst.write_set or b not in self.inst.write_set:
            return False
        if self.inst.event[a].loc != self.inst.event[b].loc:
            return False
        return self.by_key[key] if a < b else -self.by_key[('co', b, a)]


def closure(edges):
    result = set(edges)
    vertices = {v for e in result for v in e}
    for k in vertices:
        before = {u for u, v in result if v == k}
        after = {v for u, v in result if u == k}
        result.update((u, v) for u in before for v in after)
    return result


def recognize(inst, *, chain=True):
    """Permanent, sound necessary-condition kernel; never reads query assumptions.

    The returned transcript can be replayed by recomputing this deterministic
    kernel. It is not a certificate of consistency or of bounded frontier.
    """
    D = {r: set(ws) for r, ws in inst.candidates.items()}
    mandatory = set()
    trace = []
    init_edges = {(i, e.id) for i in inst.initial for e in inst.events if e.id not in inst.initial}
    while True:
        old = (frozenset(mandatory), tuple((r, tuple(sorted(D[r]))) for r in inst.reads))
        H = closure(inst.sb | mandatory | init_edges)
        L = closure({(a, b) for a, b in H if a in inst.writes and b in inst.writes
                     and inst.event[a].loc == inst.event[b].loc})
        if any(a == b for a, b in H) or any(not D[r] for r in D):
            return dict(status='PROVED_UNSAT', domains=D, H=H, L=L, mandatory=mandatory, trace=trace)
        for r in inst.reads:
            for w in sorted(D[r]):
                witness = next((v for v in inst.writes if (w, v) in L and (v, r) in H), None)
                if (r, w) in H or witness is not None:
                    D[r].remove(w)
                    trace.append(('remove', w, r, 'hb-cycle' if (r, w) in H else 'fr-hb', witness))
        if chain:
            # A single-reader thread's same-address subsequence is an H chain.
            # Apply only when the entire address write set is already L-total.
            for loc in sorted({e.loc for e in inst.events}):
                ws = [w for w in inst.writes if inst.event[w].loc == loc]
                if any((a, b) not in L and (b, a) not in L for a, b in combinations(ws, 2)):
                    continue
                ws.sort(key=lambda w: sum((v, w) in L for v in ws))
                pos = {w: i for i, w in enumerate(ws)}
                for t in inst.threads:
                    rs = [r for r in t if r in D and inst.event[r].loc == loc]
                    if not rs:
                        continue
                    earliest, lower = [], 0
                    for r in rs:
                        lower = min((pos[w] for w in D[r] if pos[w] >= lower), default=len(ws))
                        earliest.append(lower)
                    latest, upper = [], len(ws)-1
                    for r in reversed(rs):
                        upper = max((pos[w] for w in D[r] if pos[w] <= upper), default=-1)
                        latest.append(upper)
                    for r, lo, hi in zip(rs, earliest, reversed(latest)):
                        for w in sorted(D[r]):
                            if not lo <= pos[w] <= hi:
                                D[r].remove(w)
                                trace.append(('remove', w, r, 'ordered-source-chain', (tuple(rs), lo, hi)))
        for r in inst.reads:
            if len(D[r]) == 1:
                w = next(iter(D[r]))
                if (w, r) not in mandatory:
                    mandatory.add((w, r)); trace.append(('must-rf', w, r))
        new = (frozenset(mandatory), tuple((r, tuple(sorted(D[r]))) for r in inst.reads))
        if old == new:
            break
    c = {(a, b) for a in inst.writes for b in inst.writes
         if a != b and b not in inst.initial and inst.event[a].loc == inst.event[b].loc
         and (b, a) not in L and not any((a, z) in L and (z, b) in L for z in inst.writes)}
    return dict(status='RECOGNIZED', domains=D, H=H, L=L, mandatory=mandatory, successors=c, trace=trace)


def producers(lengths=(2, 2), reader_values=((1, 1),), write_values=None):
    events = [Event('init', 'W', 'x', -1, 0)]
    threads = []
    for t, n in enumerate(lengths):
        seq = []
        for i in range(n):
            v = f'w{t}_{i}'
            events.append(Event(v, 'W', 'x', t, 1 if write_values is None else write_values[t][i]))
            seq.append(v)
        threads.append(tuple(seq))
    for j, values in enumerate(reader_values):
        seq = []
        for i, val in enumerate(values):
            v = f'r{j}_{i}'
            events.append(Event(v, 'R', 'x', len(lengths)+j, val)); seq.append(v)
        threads.append(tuple(seq))
    return RAInstance(tuple(events), tuple(threads), ('init',))


def pipeline(rounds=1):
    """Two-thread RA instance with genuinely non-SC accepted assignments."""
    events = [Event('i'+x, 'W', x, -1, 0) for x in ('x', 'y', 'fa', 'fb')]
    threads = []
    for t in range(2):
        seq = []
        for i in range(1, rounds+1):
            order = ('x', 'y') if t == 0 else ('y', 'x')
            spec = [('W', x, 1, x) for x in order]
            spec += [('R', 'x', 1, 'read'), ('W', 'fa' if t == 0 else 'fb', i % 2, 'flag'),
                     ('R', 'fb' if t == 0 else 'fa', (i-1) % 2, 'wait')]
            for kind, loc, value, suffix in spec:
                v = f't{t}_{i}_{suffix}'
                seq.append(v); events.append(Event(v, kind, loc, t, value))
        threads.append(tuple(seq))
    return RAInstance(tuple(events), tuple(threads), tuple('i'+x for x in ('x', 'y', 'fa', 'fb')))
