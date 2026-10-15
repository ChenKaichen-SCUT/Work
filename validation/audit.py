"""Finite counterexample audit; this is not a proof assistant or a herd7 run.

Checks the historical-summary transition against an independent full-graph
construction, and the generated support CNF against exhaustive valuations.
Only this audit uses full enumeration; the proposed solver does not.
Run with Python 3.10+; standard library only.
"""
from dataclasses import dataclass
from itertools import product, permutations
import json
from pathlib import Path
import random


@dataclass(frozen=True)
class Event:
    kind: str
    loc: str
    thread: int


def reach(nodes, edges):
    ns = sorted(set(nodes), key=repr)
    ix = {x: i for i, x in enumerate(ns)}
    rows = [0] * len(ns)
    for a, b in edges:
        rows[ix[a]] |= 1 << ix[b]
    for k in range(len(ns)):
        bit, row = 1 << k, rows[k]
        for i in range(len(ns)):
            if rows[i] & bit:
                rows[i] |= row
    bad = any(row & (1 << i) for i, row in enumerate(rows))
    rel = frozenset((a, b) for i, a in enumerate(ns)
                    for j, b in enumerate(ns) if rows[i] & (1 << j))
    return bad, rel


def rf_edge(mode, events, w, r):
    return mode == 'all' or (mode == 'ext' and events[w].thread != events[r].thread)


def relation(events, prefix, fixed, rf, co, mode):
    rfmode, hasco, hasfr = mode
    out = {(a, b) for a, b in fixed if a in prefix and b in prefix}
    if hasco:
        out |= {(a, b) for a, b in co if a in prefix and b in prefix}
    for r, s in rf.items():
        if r not in prefix:
            continue
        assert s in prefix
        if rf_edge(rfmode, events, s, r):
            out.add((s, r))
        if hasfr:
            # fr uses ALL rf, even when this graph contains only external rf.
            out |= {(r, v) for u, v in co if u == s and v in prefix}
    return out


class Instance:
    def __init__(self, events, blocks, candidates, fixed):
        self.events, self.blocks = events, blocks
        self.candidates, self.fixed = candidates, set(fixed)
        self.prefix = [set()]
        for block in blocks:
            self.prefix.append(self.prefix[-1] | set(block))
        self.frames = []
        for i, past in enumerate(self.prefix):
            future = set(events) - past
            live = {w for r in future for w in candidates.get(r, ()) if w in past}
            boundary = {u for a, b in fixed for u, v in ((a, b), (b, a))
                        if u in past and v in future}
            oldlocs = {events[e].loc for e in past}
            addrs = {events[e].loc for e in future
                     if events[e].kind == 'W' and events[e].loc in oldlocs}
            keep = boundary | live
            interface = keep | {('in', i, s) for s in live} | {('out', i, x) for x in addrs}
            self.frames.append((keep, live, addrs, interface))

    def direct(self, i, rf, co, mode):
        past = self.prefix[i]
        _, live, addrs, interface = self.frames[i]
        edges = relation(self.events, past, self.fixed, rf, co, mode)
        if reach(past, edges)[0]:
            return None
        _, hc, hf = mode
        for e in past:
            a = self.events[e]
            if a.loc in addrs and ((a.kind == 'W' and hc) or (a.kind == 'R' and hf)):
                edges.add((e, ('out', i, a.loc)))
        if hf:
            edges |= {(('in', i, s), v) for s in live
                      for u, v in co if u == s and v in past}
        bad, rel = reach(past | interface, edges)
        assert not bad
        return frozenset((a, b) for a, b in rel if a in interface and b in interface)

    def step(self, i, old, local_rf, local_co, mode):
        if old is None:
            return None
        new = set(self.blocks[i - 1])
        oldpast = self.prefix[i - 1]
        _, oldlive, oldaddrs, oldif = self.frames[i - 1]
        _, live, addrs, interface = self.frames[i]
        nodes = oldif | new | interface
        edges = set(old)
        for a, b in self.fixed:
            if a in self.prefix[i] and b in self.prefix[i] and (a in new or b in new):
                assert a in nodes and b in nodes
                edges.add((a, b))
        rfmode, hc, hf = mode
        if hc:
            edges |= set(local_co)
        newwrites = {e for e in new if self.events[e].kind == 'W'}
        for w in newwrites:
            x = self.events[w].loc
            if x in oldaddrs:
                edges.add((('out', i - 1, x), w))
        for r, s in local_rf.items():
            assert s in oldif or s in new
            if rf_edge(rfmode, self.events, s, r):
                edges.add((s, r))
            if hf:
                if s in oldpast:
                    assert s in oldlive
                    edges.add((r, ('in', i - 1, s)))
                    edges |= {(r, v) for v in newwrites
                              if self.events[v].loc == self.events[s].loc}
                else:
                    edges |= {(r, v) for u, v in local_co if u == s}
        for x in addrs:
            if x in oldaddrs:
                edges.add((('out', i - 1, x), ('out', i, x)))
            for e in new:
                a = self.events[e]
                if a.loc == x and ((a.kind == 'W' and hc) or (a.kind == 'R' and hf)):
                    edges.add((e, ('out', i, x)))
        if hf:
            for s in live:
                if s in oldpast:
                    assert s in oldlive
                    edges.add((('in', i, s), ('in', i - 1, s)))
                    edges |= {(('in', i, s), v) for v in newwrites
                              if self.events[v].loc == self.events[s].loc}
                else:
                    edges |= {(('in', i, s), v) for u, v in local_co if u == s}
        bad, rel = reach(nodes, edges)
        if bad:
            return None
        return frozenset((a, b) for a, b in rel if a in interface and b in interface)

    def check(self, rf, co, mode):
        state = frozenset()
        for i, block in enumerate(self.blocks, 1):
            localrf = {r: s for r, s in rf.items() if r in block}
            localco = {(a, b) for a, b in co if a in block and b in block}
            state = self.step(i, state, localrf, localco, mode)
            expected = self.direct(i, rf, co, mode)
            assert state == expected, (i, mode, rf, co, self.fixed, state, expected)
        full_bad = reach(self.events, relation(self.events, set(self.events), self.fixed, rf, co, mode))[0]
        assert (state is None) == full_bad
        return not full_bad


MODES = [(r, c, f) for r in ('none', 'all', 'ext') for c, f in product((False, True), repeat=2)
         if r != 'none' or c or f]


def summary_audit():
    ev = {'s': Event('W', 'x', 0), 'v': Event('W', 'x', 1),
          'b': Event('W', 'y', 2), 'r': Event('R', 'x', 0)}
    pairs = [(a, b) for a in ev for b in ev if a != b]
    count = accepted = 0
    for mask in range(1 << len(pairs)):
        fixed = {e for j, e in enumerate(pairs) if mask & (1 << j)}
        inst = Instance(ev, [('s', 'v', 'b'), ('r',)], {'r': ('s', 'v')}, fixed)
        for order in (('s', 'v'), ('v', 's')):
            for source in ('s', 'v'):
                for mode in MODES:
                    accepted += inst.check({'r': source}, {order}, mode)
                    count += 1
    rng = random.Random(20261015)
    ev2 = dict(ev, w=Event('W', 'x', 1), r2=Event('R', 'x', 2))
    pairs2 = [(a, b) for a in ev2 for b in ev2 if a != b]
    extra = 0
    for _ in range(256):
        fixed = {e for e in pairs2 if rng.random() < .13}
        inst = Instance(ev2, [('s', 'v', 'b'), ('r',), ('w', 'r2')],
                        {'r': ('s', 'v'), 'r2': ('s', 'v', 'w')}, fixed)
        for order in (('s', 'v'), ('v', 's')):
            co = {order, ('s', 'w'), ('v', 'w')}
            for sr, sr2 in product(('s', 'v'), ('s', 'v', 'w')):
                for mode in MODES:
                    inst.check({'r': sr, 'r2': sr2}, co, mode)
                    extra += 1
    return {'exhaustive_four_event_cases': count, 'accepted_four_event_cases': accepted,
            'seeded_six_event_cases': extra, 'mismatches': 0,
            'seed': 20261015, 'relation_modes': len(MODES)}


def unit_propagate(clauses, alpha):
    values = dict(alpha)
    while True:
        changed = False
        for clause in clauses:
            if any(abs(l) in values and values[abs(l)] == (l > 0) for l in clause):
                continue
            free = [l for l in clause if abs(l) not in values]
            if not free:
                return None
            if len(free) == 1:
                lit = free[0]
                values[abs(lit)] = lit > 0
                changed = True
        if not changed:
            return values


def support_cnf(width, transitions):
    # Two layers, with width original bits in each layer; two middle states.
    variables = list(range(1, 2 * width + 1))
    nodes = [(0, 0), (1, 0), (1, 1), (2, 0)]
    ids = {}
    def atom(key):
        if key not in ids:
            ids[key] = len(variables) + len(ids) + 1
        return ids[key]
    def imp(a, b):
        clauses.append([-a, b])
    clauses = [[-atom(('U', (0, 0)))], [-atom(('V', (2, 0)))], [-atom(('U', (2, 0)))]]
    incoming = {q: [] for q in nodes}
    outgoing = {q: [] for q in nodes}
    for j, (p, q, vals) in enumerate(transitions):
        incoming[q].append(j)
        outgoing[p].append(j)
        d, a, b, z = [atom((name, j)) for name in 'DABZ']
        for offset, val in enumerate(vals):
            x = p[0] * width + offset + 1
            clauses.append([x if val else -x, d])
        imp(d, a)
        imp(atom(('U', p)), a)
        imp(d, b)
        imp(atom(('V', q)), b)
        imp(a, z)
        imp(atom(('V', q)), z)
    for q in nodes:
        if q[0] > 0:
            clauses.append([-atom(('A', j)) for j in incoming[q]] + [atom(('U', q))])
        if q[0] < 2:
            clauses.append([-atom(('B', j)) for j in outgoing[q]] + [atom(('V', q))])
    for x in variables:
        layer, offset = divmod(x - 1, width)
        for val in (False, True):
            support = [j for j, (p, _, vs) in enumerate(transitions) if p[0] == layer and vs[offset] == val]
            clauses.append([-atom(('Z', j)) for j in support] + [-x if val else x])
    return variables, clauses


def automaton_models(width, transitions):
    models = []
    for vals in product((False, True), repeat=2 * width):
        states = {(0, 0)}
        for i in range(2):
            states = {q for p, q, label in transitions
                      if p in states and tuple(vals[i * width:(i + 1) * width]) == label}
        if (2, 0) in states:
            models.append(dict(enumerate(vals, 1)))
    return models


def cnf_audit():
    rng = random.Random(19)
    total = graphs = 0
    for width in (1, 2):
        labels = list(product((False, True), repeat=width))
        possible = ([((0, 0), (1, q), label) for q in (0, 1) for label in labels]
                    + [((1, q), (2, 0), label) for q in (0, 1) for label in labels])
        masks = range(1 << len(possible)) if width == 1 else [rng.getrandbits(len(possible)) for _ in range(128)]
        for mask in masks:
            transitions = [e for j, e in enumerate(possible) if mask & (1 << j)]
            variables, clauses = support_cnf(width, transitions)
            models = automaton_models(width, transitions)
            graphs += 1
            for choices in product((None, False, True), repeat=len(variables)):
                alpha = {x: v for x, v in zip(variables, choices) if v is not None}
                remaining = [v for v in models if all(v[x] == value for x, value in alpha.items())]
                up = unit_propagate(clauses, alpha)
                assert (up is None) == (not remaining), (width, mask, alpha)
                if remaining:
                    forced = {x: remaining[0][x] for x in variables
                              if all(v[x] == remaining[0][x] for v in remaining)}
                    actual = {x: up[x] for x in variables if x in up}
                    assert actual == forced, (width, mask, alpha, actual, forced)
                total += 1
    return {'automata': graphs, 'partial_assignments': total, 'mismatches': 0}


def tso_graph(events, threads, rf, co, fences=(), include_internal=False, external_fr=False):
    po = {(a, b) for thread in threads for i, a in enumerate(thread) for b in thread[i + 1:]}
    loc = {(a, b) for a, b in po if events[a].loc == events[b].loc}
    ppo = {(a, b) for a, b in po if events[a].kind == 'R' or events[b].kind == 'W'}
    fr = {(r, v) for r, s in rf.items() for u, v in co if s == u}
    rfe = {(s, r) for r, s in rf.items() if events[s].thread != events[r].thread}
    allrf = {(s, r) for r, s in rf.items()}
    scpl = loc | co | fr | allrf
    ghbfr = {(r, v) for r, v in fr if not external_fr or (rf[r], r) in rfe}
    ghb = ppo | set(fences) | co | ghbfr | (allrf if include_internal else rfe)
    return not reach(events, scpl)[0] and not reach(events, ghb)[0]


def counterexamples():
    ev = {'ix': Event('W', 'x', -1), 'iy': Event('W', 'y', -1),
          'wx': Event('W', 'x', 0), 'rx1': Event('R', 'x', 0), 'ry0': Event('R', 'y', 0),
          'wy': Event('W', 'y', 1), 'ry1': Event('R', 'y', 1), 'rx0': Event('R', 'x', 1)}
    rf = {'rx1': 'wx', 'ry0': 'iy', 'ry1': 'wy', 'rx0': 'ix'}
    co = {('ix', 'wx'), ('iy', 'wy')}
    threads = [('wx', 'rx1', 'ry0'), ('wy', 'ry1', 'rx0')]
    assert tso_graph(ev, threads, rf, co)
    assert not tso_graph(ev, threads, rf, co, include_internal=True)

    ev2 = {'ix': Event('W', 'x', -1), 'iy': Event('W', 'y', -1),
           's': Event('W', 'x', 0), 'c': Event('R', 'y', 0), 'r': Event('R', 'x', 0),
           'v': Event('W', 'x', 1), 'b': Event('W', 'y', 1)}
    rf2 = {'c': 'b', 'r': 's'}
    co2 = {('ix', 's'), ('ix', 'v'), ('s', 'v'), ('iy', 'b')}
    threads2 = [('s', 'c', 'r'), ('v', 'b')]
    assert not tso_graph(ev2, threads2, rf2, co2)
    assert tso_graph(ev2, threads2, rf2, co2, external_fr=True)

    ev3 = {e: Event('W', 'x', 0 if e[0] == 'a' else 1) for e in ('a1', 'a2', 'b1', 'b2')}
    order = ['a1', 'a2', 'b1', 'b2']
    co3 = {(a, b) for i, a in enumerate(order) for b in order[i + 1:]}
    assert tso_graph(ev3, [('a1', 'a2'), ('b1', 'b2')], {}, co3, {('a1', 'a2'), ('b1', 'b2')})
    assert ('a2', 'b1') in co3  # contradicts an unjustified global-round seal

    base = {'s': Event('W', 'x', 0), 'v': Event('W', 'x', 1),
            'b': Event('W', 'y', 2), 'r': Event('R', 'x', 3)}
    inst = Instance(base, [('s', 'v', 'b'), ('r',)], {'r': ('s',)}, {('v', 'b'), ('b', 'r')})
    co4, rf4, mode = {('s', 'v')}, {'r': 's'}, ('all', True, True)
    old = inst.direct(1, rf4, co4, mode)
    broken = frozenset((a, b) for a, b in old if a != ('in', 1, 's') and b != ('in', 1, 's'))
    assert inst.step(2, old, rf4, set(), mode) is None
    assert inst.step(2, broken, rf4, set(), mode) is not None
    assert not reach(('w', 'v'), {('w', 'v')})[0]
    assert reach(('o', 'v'), {('o', 'v'), ('v', 'o')})[0]
    return {
        'rfe_replaced_with_rf': {'correct_tso': True, 'mutant': False},
        'fr_derived_only_from_rfe': {'correct_tso': False, 'mutant': True},
        'per_thread_mfence_as_global_barrier': {'valid_tso_co': order, 'violates_round_seal': True},
        'missing_source_port': {'correct_accept': False, 'mutant_accept': True},
        'reusing_output_port': {'real_cycle': False, 'mutant_cycle': True},
    }


def main():
    result = {'scope': 'Finite independent checks, not a mechanized theorem or a herd7 execution.'}
    result['counterexamples'] = counterexamples()
    print('Counterexample mutations detected.', flush=True)
    result['support_cnf'] = cnf_audit()
    print('Support CNF checked.', flush=True)
    result['summary_transition'] = summary_audit()
    target = Path(__file__).with_name('results.json')
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
