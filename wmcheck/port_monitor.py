"""Exact future-port summaries for regular forbidden cycles.

R records unmarked paths; T records paths with exactly one marked test edge.
They are kept jointly, never unioned across alternative histories. Only future
edge targets need rows and only future edge sources need columns. This module
does not use SAT, completion search, or enumeration of conflict supports.
"""
from dataclasses import dataclass
import os
try:
    from . import _port_native
except ImportError:
    _port_native = None


@dataclass(frozen=True)
class PortMonitor:
    size: int
    arcs: tuple
    tests: tuple = ()
    acyclic: bool = False


def ra_port_monitors():
    # Partial DFA for (s|r)+(r|c|R c+)*. An f -> start test edge is
    # marked: a closed walk with exactly one such edge is a violation.
    coherence = PortMonitor(4, (
        ('s', ((0, 1), (1, 1))),
        ('r', ((0, 1), (1, 1), (2, 2))),
        ('c', ((1, 2), (2, 2), (3, 2))),
        ('R', ((1, 3), (2, 3))),
    ), ((1, 0), (2, 0)))
    return coherence, PortMonitor(1, (('c', ((0, 0),)),), acyclic=True)


@dataclass(frozen=True)
class PortStep:
    """All indices are fixed by the input's candidate groups, not a history."""
    width: int
    before_inputs: tuple
    before_outputs: tuple
    after_inputs: tuple
    after_outputs: tuple
    tests: tuple
    alternatives: tuple
    acyclic: bool
    native_plan: object = None

    def update(self, state, alternative):
        if self.native_plan is not None:
            return _port_native.update(self.native_plan,state,alternative)
        old_r, old_t = state
        r = [1 << i for i in range(self.width)]
        t = [0] * self.width
        for row_index, old in zip(self.before_inputs, old_r):
            while old:
                bit = old & -old; old -= bit
                r[row_index] |= 1 << self.before_outputs[bit.bit_length()-1]
        for row_index, old in zip(self.before_inputs, old_t):
            while old:
                bit = old & -old; old -= bit
                t[row_index] |= 1 << self.before_outputs[bit.bit_length()-1]

        for u, v in self.tests:
            if r[v] & (1 << u):
                return None
            successors = r[v]
            for i, row in enumerate(r):
                if row & (1 << u):
                    t[i] |= successors

        for u, v in self.alternatives[alternative]:
            if (r if self.acyclic else t)[v] & (1 << u):
                return None
            if r[u] & (1 << v):
                continue
            successors = r[v]
            predecessors = [i for i, row in enumerate(r) if row & (1 << u)]
            if not self.acyclic:
                marked_successors = t[v]
                marked_predecessors = [i for i, row in enumerate(t) if row & (1 << u)]
                # The fourth possible term uses T(v,u), already rejected.
                for i in marked_predecessors:
                    t[i] |= successors
                for i in predecessors:
                    t[i] |= marked_successors
            for i in predecessors:
                r[i] |= successors

        mask = sum(1 << j for j in self.after_outputs)
        remap = {j: 1 << k for k, j in enumerate(self.after_outputs)}

        def project(rows):
            result = []
            for i in self.after_inputs:
                bits = rows[i] & mask; value = 0
                while bits:
                    bit = bits & -bits; bits -= bit
                    value |= remap[bit.bit_length()-1]
                result.append(value)
            return tuple(result)

        return project(r), (() if self.acyclic else project(t))


def plan_ports(monitors, groups):
    """Compile future incoming/outgoing incidence from the union of candidates.

    Tests are installed at the first group mentioning their event. Incidence
    includes these future tests as well as all alternative base edges. Using
    only the selected history here would make forgetting unsound.
    """
    result = []
    for monitor in monitors:
        transitions = dict(monitor.arcs)
        seen_events = set(); operations = []
        last_in, last_out = {}, {}
        for step, (vertices, alternatives) in enumerate(groups):
            introduced = [v for v in vertices if v not in seen_events]
            seen_events.update(vertices)
            tests = tuple(((v, a), (v, b)) for v in introduced for a, b in monitor.tests)
            choices = tuple(tuple(((a, p), (b, q))
                                  for symbol, a, b in additions
                                  for p, q in transitions.get(symbol, ()))
                            for _, additions, _ in alternatives)
            all_arcs = tests + tuple(arc for choice in choices for arc in choice)
            for u, v in all_arcs:
                last_out[u] = step; last_in[v] = step
            operations.append((tests, choices, {v for arc in all_arcs for v in arc}))

        plans = []; before_i, before_o = (), ()
        for step, (tests, choices, endpoints) in enumerate(operations):
            active = sorted(set(before_i) | set(before_o) | endpoints)
            indices = {v: i for i, v in enumerate(active)}
            after_i = tuple(v for v in active if last_in.get(v, -1) > step)
            after_o = tuple(v for v in active if last_out.get(v, -1) > step)
            plans.append(PortStep(
                len(active), tuple(indices[v] for v in before_i), tuple(indices[v] for v in before_o),
                tuple(indices[v] for v in after_i), tuple(indices[v] for v in after_o),
                tuple((indices[u], indices[v]) for u, v in tests),
                tuple(tuple((indices[u], indices[v]) for u, v in choice) for choice in choices),
                monitor.acyclic,
            ))
            before_i, before_o = after_i, after_o
        if _port_native is not None and os.environ.get('WMCHECK_NATIVE_PORTS')=='1':
            from dataclasses import replace
            plans=[replace(plan,native_plan=_port_native.prepare(plan)) for plan in plans]
        result.append(plans)
    return tuple(result)
