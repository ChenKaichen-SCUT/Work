"""Independent dense-path checks and original-interface regression tests."""
import random
import unittest
from itertools import product

from wmcheck.model import Event
from wmcheck.port_monitor import PortMonitor, plan_ports
from wmcheck.regular_monitor import close
from wmcheck.ra import RAInstance, pipeline, producers
from wmcheck.ra_frontier import compile_frontier
from tests import test_ra_construction


class PortPaths(unittest.TestCase):
    def audit(self, monitor, groups):
        plans = plan_ports((monitor,), groups)[0]
        table = dict(monitor.arcs)
        nodes = sorted({(v, p) for vs, _ in groups for v in vs for p in range(monitor.size)})
        ids = {v: j for j, v in enumerate(nodes)}
        for choices in product(*(range(len(options)) for _, options in groups)):
            state = ((), ()); base = set(); tests = set(); seen = set()
            for step, ((vs, alternatives), choice) in enumerate(zip(groups, choices)):
                for v in vs:
                    if v not in seen:
                        tests.update(((v, a), (v, b)) for a, b in monitor.tests)
                seen.update(vs)
                _, additions, _ = alternatives[choice]
                base.update(((a, p), (b, q)) for symbol, a, b in additions for p, q in table.get(symbol, ()))
                raw = [1 << j for j in range(len(nodes))]
                for a, b in base:
                    raw[ids[a]] |= 1 << ids[b]
                r = close(raw)
                t = [0] * len(nodes)
                for a, b in tests:
                    for j, row in enumerate(r):
                        if row & (1 << ids[a]):
                            t[j] |= r[ids[b]]
                bad = (any(r[ids[b]] & (1 << ids[a]) for a, b in base) if monitor.acyclic
                       else any(row & (1 << j) for j, row in enumerate(t)))
                actual = plans[step].update(state, choice)
                self.assertEqual(actual is None, bad, (monitor, groups, choices, step))
                if bad:
                    break
                # Compute suffix incidence independently, including test edges
                # for events which have not yet appeared.
                future = set(); introduced = set(seen)
                for later_vs, options in groups[step+1:]:
                    for v in later_vs:
                        if v not in introduced:
                            future.update(((v, a), (v, b)) for a, b in monitor.tests)
                    introduced.update(later_vs)
                    for _, additions, _ in options:
                        future.update(((a, p), (b, q)) for symbol, a, b in additions
                                      for p, q in table.get(symbol, ()))
                inputs = sorted({b for _, b in future if b[0] in seen})
                outputs = sorted({a for a, _ in future if a[0] in seen})
                # Some product nodes of a seen event have never had an arc;
                # their identity is implicit until their first incidence.
                encountered = {v for arc in base | tests for v in arc}
                # Candidate endpoints are introduced even in an unchosen arm.
                for _, options in groups[:step+1]:
                    for _, additions, _ in options:
                        encountered.update(v for symbol, a, b in additions
                                           for p, q in table.get(symbol, ())
                                           for v in ((a, p), (b, q)))
                inputs = [v for v in inputs if v in encountered]
                outputs = [v for v in outputs if v in encountered]
                def projected(rows):
                    return tuple(sum(1 << j for j, b in enumerate(outputs) if rows[ids[a]] & (1 << ids[b]))
                                 for a in inputs)
                self.assertEqual(actual, (projected(r), () if monitor.acyclic else projected(t)))
                state = actual

    def test_dense_reference_for_random_candidate_streams(self):
        rng = random.Random(90153)
        for trial in range(80):
            acyclic = trial % 4 == 0
            q = 1 if acyclic else 3
            arcs = (('x', tuple((a, b) for a in range(q) for b in range(q) if rng.random() < .45)),)
            mon = PortMonitor(q, arcs, () if acyclic else ((2, 0),), acyclic)
            groups = []
            for _ in range(5):
                a, b = rng.sample('abcd', 2)
                groups.append(((a, b), [((), (), ()), ((), (('x', a, b),), ())]))
            self.audit(mon, groups)

    def test_two_marked_segments_must_not_be_composed(self):
        mon = PortMonitor(4, (('x', ((0, 3), (2, 1))),), ((1, 0), (3, 2)))
        self.audit(mon, [(('a',), [((), (('x', 'a', 'a'),), ())])])
        plan = plan_ports((mon,), [(('a',), [((), (('x', 'a', 'a'),), ())])])[0][0]
        self.assertEqual(plan.update(((), ()), 0), ((), ()))

    def test_forbidden_start_forgotten_before_cycle_is_completed(self):
        mon = PortMonitor(4, (('a', ((0, 1),)), ('b', ((1, 2),)), ('c', ((2, 3),))), ((3, 0),))
        groups = [((u, v), [((), ((symbol, u, v),), ())]) for symbol, u, v in
                  (('a', 'old', 'left'), ('c', 'right', 'old'), ('b', 'left', 'right'))]
        self.audit(mon, groups)
        plans = plan_ports((mon,), groups)[0]
        state = ((), ())
        for step in plans[:2]:
            state = step.update(state, 0)
            self.assertIsNotNone(state)
        self.assertIsNone(plans[2].update(state, 0))

    def test_acyclic_bipartite_histories_merge_before_generation(self):
        mon = PortMonitor(1, (('x', ((0, 0),)),), acyclic=True)
        left, right = ('a', 'b', 'c'), ('d', 'e', 'f')
        groups = [((a, b), [((), (), ()), ((), (('x', a, b),), ())]) for a in left for b in right]
        groups += [((a, 'z'), [((), (('x', a, 'z'),), ())]) for a in left+right]
        states = {((), ())}
        for step in plan_ports((mon,), groups)[0]:
            states = {step.update(s, j) for s in states for j in range(len(step.alternatives))}
            self.assertNotIn(None, states)
            self.assertEqual(len(states), 1)


class RAPorts(unittest.TestCase):
    # Reuse only the independent execution/UP/witness checker, not its tests.
    compare = test_ra_construction.RAConstruction.compare

    def test_all_partial_assignments_and_support_cnf(self):
        inst = producers((1, 1))
        c = compile_frontier(inst, co_mode='direct', summary_mode='ports', early_degrees=True, cnf=True)
        self.assertEqual(self.compare(inst, [c], exhaustive=True), 2187)

    def test_mixed_ra_and_non_sc_pipeline(self):
        rng = random.Random(449003)
        cases = [pipeline(1), producers((2, 1)), producers((1, 1, 1))]
        for _ in range(45):
            es = [Event('ix', 'W', 'x', -1, 0), Event('iy', 'W', 'y', -1, 0)]
            ts = []
            for t in range(2):
                thread = []
                for j in range(3):
                    eid = f'e{t}{j}'; thread.append(eid)
                    es.append(Event(eid, rng.choice(('W', 'R')), rng.choice(('x', 'y')), t, rng.randrange(2)))
                ts.append(tuple(thread))
            cases.append(RAInstance(tuple(es), tuple(ts), ('ix', 'iy')))
        for inst in cases:
            full, ports = [compile_frontier(inst, co_mode='direct', summary_mode=mode,
                                            early_degrees=True, cnf=True) for mode in ('full', 'ports')]
            self.compare(inst, [full, ports], count=50)
            if 'layer_states' in full.stats:
                self.assertEqual(len(full.layers), len(ports.layers))
                self.assertTrue(all(len(a) >= len(b) for a, b in zip(full.layers, ports.layers)))


if __name__ == '__main__':
    unittest.main()
