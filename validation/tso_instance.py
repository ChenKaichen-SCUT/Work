"""Independent axiomatic checks for the actual x86-TSO subclass in the proof.

Normal read/write events and MFENCE only; no RMW/NT/mixed-size operations.
The input traces contain exactly one successful peer-flag read per round.
Flag values alternate 1,0,1,0; no unbounded epoch values are assumed.
"""
from itertools import product, permutations
from pathlib import Path
import json

from audit import Event, Instance, reach, tso_graph


def ordered_pairs(order):
    return {(a, b) for i, a in enumerate(order) for b in order[i + 1:]}


def build(p, n, payload=False):
    ev, epoch, values = {}, {}, {}
    sequences = [[] for _ in range(p)]
    round_blocks = [[] for _ in range(n)]
    flag_writes, flag_reads = {}, {}
    data_writes, data_reads = {}, []
    def add(name, kind, loc, thread, i, value=None):
        ev[name], epoch[name] = Event(kind, loc, thread), i
        if value is not None:
            values[name] = value
        if i:
            sequences[thread].append(name)
            round_blocks[i - 1].append(name)
        return name
    for t in range(p):
        add(f'init:f{t}', 'W', f'f{t}', -1, 0, 0)
    if payload:
        assert p == 4
        for x in ('x', 'y'):
            add(f'init:{x}', 'W', x, -1, 0, 0)
    for i in range(1, n + 1):
        for t in range(p):
            if payload:
                loc = 'x' if t in (0, 2) else 'y'
                w = add(f'dw:{t}:{i}', 'W', loc, t, i, 1)
                data_writes.setdefault((loc, i), []).append(w)
                if t in (0, 1):
                    other = 'y' if t == 0 else 'x'
                    r = add(f'dr:{t}:{i}', 'R', other, t, i, 0 if i == 1 else 1)
                    data_reads.append(r)
            flag_writes[t, i] = add(f'fw:{t}:{i}', 'W', f'f{t}', t, i, i % 2)
            for u in range(p):
                if t != u:
                    flag_reads[t, u, i] = add(f'fr:{t}:{u}:{i}', 'R', f'f{u}', t, i, i % 2)
            add(f'F:{t}:{i}', 'F', '', t, i)

    initial = tuple(e for e in ev if epoch[e] == 0)
    blocks = [initial] + [tuple(b) for b in round_blocks]
    memory_threads = [[e for e in seq if ev[e].kind != 'F'] for seq in sequences]
    memory_events = {e: a for e, a in ev.items() if a.kind != 'F'}
    fences = set()
    for seq in sequences:
        for j, e in enumerate(seq):
            if ev[e].kind == 'F':
                fences |= {(a, b) for a in seq[:j] for b in seq[j + 1:]
                           if ev[a].kind != 'F' and ev[b].kind != 'F'}

    # Independently construct a sparse, memory-reachability-equivalent fixed graph.
    fixed_local, fixed_global = set(), set()
    for seq in sequences:
        lastloc, lastread, lastwrite, lastfence = {}, None, None, None
        for e in seq:
            a = ev[e]
            if a.kind != 'F':
                if a.loc in lastloc:
                    fixed_local.add((lastloc[a.loc], e))
                lastloc[a.loc] = e
            if a.kind == 'R':
                for prev in (lastread, lastfence):
                    if prev is not None:
                        fixed_global.add((prev, e))
                lastread = e
            elif a.kind == 'W':
                for prev in (lastread, lastwrite, lastfence):
                    if prev is not None:
                        fixed_global.add((prev, e))
                lastwrite = e
            else:
                for prev in (lastread, lastwrite, lastfence):
                    if prev is not None:
                        fixed_global.add((prev, e))
                lastfence = e
    po = set().union(*(ordered_pairs(seq) for seq in memory_threads))
    dense_local = {(a, b) for a, b in po if ev[a].loc == ev[b].loc}
    dense_global = {(a, b) for a, b in po if ev[a].kind == 'R' or ev[b].kind == 'W'} | fences
    for sparse, dense in ((fixed_local, dense_local), (fixed_global, dense_global)):
        sparse_reach = {(a, b) for a, b in reach(ev, sparse)[1] if a in memory_events and b in memory_events}
        assert sparse_reach == reach(memory_events, dense)[1]
    return locals()


def flag_co(b):
    co = set()
    for t in range(b['p']):
        co |= ordered_pairs([f'init:f{t}'] + [b['flag_writes'][t, i] for i in range(1, b['n'] + 1)])
    return co


def flag_matching_audit():
    b = build(2, 4)
    reads = list(b['flag_reads'].values())
    candidates = {r: [w for w, a in b['ev'].items() if a.kind == 'W'
                      and a.loc == b['ev'][r].loc and b['values'][w] == b['values'][r]] for r in reads}
    checked = accepted = 0
    exact = {r: b['flag_writes'][u, i] for (t, u, i), r in b['flag_reads'].items()}
    for sources in product(*(candidates[r] for r in reads)):
        rf = dict(zip(reads, sources))
        valid = tso_graph(b['memory_events'], b['memory_threads'], rf, flag_co(b), b['fences'])
        checked += 1
        if valid:
            accepted += 1
            assert rf == exact
    assert accepted == 1
    return {'threads': 2, 'rounds': 4, 'raw_flag_rf_combinations': checked,
            'tso_valid_flag_rf_combinations': accepted, 'matching_mismatches': 0}


def payload_audit():
    b = build(4, 2, payload=True)
    ev, epoch = b['ev'], b['epoch']
    fixed_rf = {r: b['flag_writes'][u, i] for (t, u, i), r in b['flag_reads'].items()}
    fixed_edges = {(w, r) for r, w in fixed_rf.items()}
    kl = b['fixed_local'] | fixed_edges
    kg = b['fixed_global'] | fixed_edges
    _, gr = reach(ev, kg)
    _, lr = reach(ev, kl)
    writes = [e for e, a in ev.items() if a.kind == 'W']
    d = {(w, v) for w in writes for v in writes if w != v and ev[w].loc == ev[v].loc
         and ((w, v) in gr or (w, v) in lr or epoch[w] == 0)}
    assert all((w, v) in d for w in writes for v in writes
               if ev[w].loc == ev[v].loc and epoch[w] < epoch[v])
    candidates = {r: (w,) for r, w in fixed_rf.items()}
    for r in b['data_reads']:
        raw = [w for w in writes if ev[w].loc == ev[r].loc and b['values'][w] == b['values'][r]]
        keep = []
        for w in raw:
            rf_cycle = (r, w) in lr or (ev[r].thread != ev[w].thread and (r, w) in gr)
            fr_cycle = any((w, v) in d and ((v, r) in gr or (v, r) in lr) for v in writes)
            if not rf_cycle and not fr_cycle:
                keep.append(w)
        assert keep
        assert all(epoch[w] in (epoch[r] - 1, epoch[r]) for w in keep)
        candidates[r] = tuple(keep)
    local = Instance(ev, b['blocks'], candidates, kl)
    global_ = Instance(ev, b['blocks'], candidates, kg)
    choices = [(loc, i) for i in range(1, 3) for loc in ('x', 'y')]
    checked = accepted = 0
    for orders in product(*(list(permutations(b['data_writes'][key])) for key in choices)):
        co = flag_co(b)
        byloc = {loc: [f'init:{loc}'] for loc in ('x', 'y')}
        for (loc, i), order in zip(choices, orders):
            byloc[loc].extend(order)
        for order in byloc.values():
            co |= ordered_pairs(order)
        for sources in product(*(candidates[r] for r in b['data_reads'])):
            rf = fixed_rf | dict(zip(b['data_reads'], sources))
            reference = tso_graph(b['memory_events'], b['memory_threads'], rf, co, b['fences'])
            got_l = local.check(rf, co, ('all', True, True))
            got_g = global_.check(rf, co, ('ext', True, True))
            assert reference == (got_l and got_g)
            checked += 1
            accepted += reference
    assert accepted > 0
    max_interfaces = [max(len(frame[3]) for frame in inst.frames) for inst in (local, global_)]
    return {'threads': 4, 'rounds': 2, 'full_execution_choices_checked': checked,
            'tso_valid_choices': accepted, 'summary_mismatches': 0,
            'max_interface_nodes_local_global': max_interfaces,
            'matching_flag_rf_proved_then_fixed': len(fixed_rf),
            'sparse_fixed_relation_reachability_matches_dense': True}


def main():
    report = {'scope': 'Independent relational x86-TSO oracle, not a herd7 execution.',
              'alternating_flag_matching': flag_matching_audit(),
              'actual_tso_payload_instance': payload_audit()}
    Path(__file__).with_name('tso_results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
