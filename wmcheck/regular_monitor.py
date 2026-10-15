"""Exact cyclic-rotation automata and all-state product reachability summaries.

This deliberately small implementation uses regular words, not intersection of
path languages as a substitute for intersection of binary relations.
"""
from collections import deque
from dataclasses import dataclass
from functools import lru_cache


def alt(*xs): return ('or',)+xs
def seq(*xs): return ('seq',)+xs
def star(x): return ('star', x)
def plus(x): return seq(x, star(x))


@dataclass(frozen=True)
class Automaton:
    size: int
    final: frozenset
    transitions: tuple

    @property
    def initial_rows(self):
        return tuple(1 << i for i in range(self.size))

    @property
    def accept_pairs(self):
        return tuple((0, q) for q in sorted(self.final))

    @property
    def edge_map(self):
        return {s: tuple(enumerate(targets)) for s, targets in self.transitions}


@dataclass(frozen=True)
class PairedMonitor:
    size: int
    initial_rows: tuple
    accept_pairs: tuple
    arcs: tuple

    @property
    def edge_map(self):
        return dict(self.arcs)


def paired_rotation(size, starts, finals, arcs):
    """Share the guessed rotation pivot through a paired acceptance test.

    Two copies of A, an epsilon bridge F_0 -> I_1, and acceptance pairs
    (p_0,p_1). The pivot need not be duplicated into every automaton state:
    all-state product reachability already remembers both endpoints.
    """
    rows = [1 << i for i in range(2*size)]
    for f in finals:
        for i in starts:
            rows[f] |= 1 << (size+i)
    return PairedMonitor(2*size, close(rows), tuple((p, p+size) for p in range(size)),
                         tuple((s, tuple(edges)+tuple((a+size, b+size) for a, b in edges))
                               for s, edges in sorted(arcs.items())))


def rotation_automaton(expression):
    """Thompson NFA -> Rot(L) NFA -> DFA -> language-equivalence quotient."""
    edges = {}; count = 0
    def fresh():
        nonlocal count
        q = count; count += 1; return q
    def edge(a, symbol, b):
        edges.setdefault((a, symbol), set()).add(b)
    def build(expr):
        a, b = fresh(), fresh()
        if isinstance(expr, str):
            edge(a, expr, b)
        elif expr[0] == 'or':
            for x in expr[1:]:
                u, v = build(x); edge(a, None, u); edge(v, None, b)
        elif expr[0] == 'seq':
            last = a
            for x in expr[1:]:
                u, v = build(x); edge(last, None, u); last = v
            edge(last, None, b)
        elif expr[0] == 'star':
            u, v = build(expr[1]); edge(a, None, b); edge(a, None, u)
            edge(v, None, u); edge(v, None, b)
        else:
            raise ValueError('Unsupported expression')
        return a, b
    start, end = build(expression)
    alphabet = sorted({s for _, s in edges if s is not None})
    def epsilon(seeds, adjacency):
        seen, todo = set(seeds), list(seeds)
        while todo:
            for q in adjacency.get((todo.pop(), None), ()):
                if q not in seen:
                    seen.add(q); todo.append(q)
        return frozenset(seen)
    # Remove epsilon first, keeping every possible cut state and accepting
    # endpoint. Unreachable/dead pivots cause no accepted words.
    closures = [epsilon([q], edges) for q in range(count)]
    initial = closures[start]
    finals = {q for q in range(count) if end in closures[q]}
    epsilon_free = {}
    for q in range(count):
        for symbol in alphabet:
            reached = set()
            for p in closures[q]:
                for t in edges.get((p, symbol), ()):
                    reached.update(closures[t])
            if reached:
                epsilon_free[q, symbol] = reached
    # (pivot, phase, state), phase 0: pivot -> F, phase 1: I -> pivot.
    rotated = {}
    accept = set()
    starts = []
    for pivot in range(count):
        starts.append((pivot, 0, pivot)); accept.add((pivot, 1, pivot))
        # Populate with explicit composite keys to avoid tuple ambiguity.
        for (q, symbol), targets in epsilon_free.items():
            for phase in (0, 1):
                rotated[((pivot, phase, q), symbol)] = {(pivot, phase, t) for t in targets}
        for q in finals:
            rotated[((pivot, 0, q), None)] = {(pivot, 1, t) for t in initial}
    # The state space above is modest for the fixed RA axioms. Determinize only
    # reachable subsets; minimize before using event x automaton products.
    root = epsilon(starts, rotated)
    subsets = [root]; indices = {root: 0}; delta = []; final_dfa = set()
    for subset in subsets:
        row = []
        if subset & accept:
            final_dfa.add(indices[subset])
        for symbol in alphabet:
            dst = set()
            for q in subset:
                dst.update(rotated.get((q, symbol), ()))
            target = epsilon(dst, rotated)
            if target not in indices:
                indices[target] = len(subsets); subsets.append(target)
            row.append(indices[target])
        delta.append(tuple(row))
    partition = [int(i in final_dfa) for i in range(len(subsets))]
    while True:
        ids = {}; new = []
        for i, row in enumerate(delta):
            signature = (i in final_dfa, tuple(partition[t] for t in row))
            new.append(ids.setdefault(signature, len(ids)))
        if new == partition:
            break
        partition = new
    groups = sorted(set(partition), key=lambda g: (g != partition[0], g))
    remap = {g: i for i, g in enumerate(groups)}
    representatives = [partition.index(g) for g in groups]
    transitions = tuple((symbol, tuple(remap[partition[delta[i][j]]] for i in representatives))
                        for j, symbol in enumerate(alphabet))
    return Automaton(len(groups), frozenset(remap[partition[i]] for i in final_dfa), transitions)


@lru_cache(None)
def ra_monitors(compact=False):
    h = alt('s', 'r')
    e = alt('r', 'c', seq('R', plus('c')))
    # Four-state partial DFA for H+ E*: 0=start, 1=H+, 2=E*, 3=R awaiting c.
    first = paired_rotation(4, (0,), (1, 2),
                            {'s': ((0, 1), (1, 1)),
                             'r': ((0, 1), (1, 1), (2, 2)),
                             'c': ((1, 2), (2, 2), (3, 2)),
                             'R': ((1, 3), (2, 3))}) if compact else rotation_automaton(seq(plus(h), star(e)))
    return (first,
            rotation_automaton(plus('c')), rotation_automaton(seq('q', plus('c'))))


def close(rows):
    rows = list(rows)
    for k in range(len(rows)):
        bit, outgoing = 1 << k, rows[k]
        for i, incoming in enumerate(rows):
            if incoming & bit:
                rows[i] |= outgoing
    return tuple(rows)


def project(rows, indices):
    mapping = {old: new for new, old in enumerate(indices)}
    keep = sum(1 << i for i in indices)
    out = []
    for i in indices:
        bits = rows[i] & keep; value = 0
        while bits:
            low = bits & -bits; bits -= low
            value |= 1 << mapping[low.bit_length()-1]
        out.append(value)
    return tuple(out)


def update(monitor, rows, before, active, after, additions, incremental=True):
    q = monitor.size; index = {v: i for i, v in enumerate(active)}
    expanded = [row << (i*q) for i in range(len(active)) for row in monitor.initial_rows]
    old_indices = [index[v]*q+p for v in before for p in range(q)]
    for i, bits in enumerate(rows):
        while bits:
            low = bits & -bits; bits -= low
            expanded[old_indices[i]] |= 1 << old_indices[low.bit_length()-1]
    transitions = monitor.edge_map
    for symbol, a, b in additions:
        if symbol not in transitions:
            continue
        for p, target in transitions[symbol]:
            u, v = index[a]*q+p, index[b]*q+target
            if incremental:
                # R is reflexively closed. Inserting u->v adds exactly
                # R(*,u) x R(v,*), including when it creates a cycle.
                if not expanded[u] & (1 << v):
                    successors = expanded[v]
                    predecessors = [i for i, row in enumerate(expanded) if row & (1 << u)]
                    for i in predecessors:
                        expanded[i] |= successors
            else:
                expanded[u] |= 1 << v
    closed = tuple(expanded) if incremental else close(expanded)
    if any(closed[i*q+p] & (1 << (i*q+r)) for i in range(len(active)) for p, r in monitor.accept_pairs):
        return None
    return project(closed, [index[v]*q+p for v in after for p in range(q)])
