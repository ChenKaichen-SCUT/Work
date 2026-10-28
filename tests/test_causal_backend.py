"""Semantic acceptance of external certificates and non-SB candidate plans."""
import itertools
import unittest

from pysat.solvers import Solver
from wmcheck.model import Event
from wmcheck.ra import RAInstance, RARegistry, recognize
from wmcheck.ra_oracle import enumerate_assignments
from wmcheck.ra_frontier import prepare_frontier, compile_frontier
from wmcheck.graph_solver import GraphSolver
from wmcheck.compiler import ResourceLimit


def crossing():
    return RAInstance((Event('i', 'W', 'x', -1, 0), Event('a', 'W', 'x', 0, 1),
        Event('r', 'R', 'x', 0, 1), Event('z', 'W', 'x', 0, 1),
        Event('b', 'W', 'x', 1, 1)), (('a', 'r', 'z'), ('b',)), ('i',))


class CausalBackend(unittest.TestCase):
    def test_all_assignments_right_sb_endpoint_first_and_constants(self):
        inst = crossing()
        cert = recognize(inst, source_covers=True)
        # z is the real right SB endpoint of r, introduced in the first bag.
        plan = prepare_frontier(inst, certificate=cert, co_mode='direct', summary_mode='ports',
            bags=(('i', 'a', 'b', 'z'), ('i', 'a', 'b', 'z', 'r')), early_degrees=True)
        self.assertLess(plan.stats['event_first']['z'], plan.stats['event_first']['r'])
        self.assertLessEqual(plan.stats['actual_K'], 5)
        compiled = compile_frontier(inst, prepared=plan, cnf=True)
        graph = GraphSolver(compiled)
        reg = compiled.registry
        models = {tuple(m[v] for v in reg.by_id) for m in enumerate_assignments(inst, reg)}
        self.assertGreater(len(models), 1)
        with Solver(name='minisat22', bootstrap_with=compiled.clauses) as sat:
            for bits in itertools.product((False, True), repeat=reg.nvars):
                alpha = [v if bits[v-1] else -v for v in reg.by_id]
                expected = bits in models
                self.assertEqual(graph.propagate(alpha)[0], expected, alpha)
                self.assertEqual(sat.solve(assumptions=alpha), expected, alpha)
        # The impossible future source remains registered and queryable.
        future = reg.literal(('rf', 'z', 'r'))
        initial_co = reg.literal(('co', 'i', 'b'))
        self.assertFalse(graph.propagate([future])[0])
        self.assertFalse(graph.propagate([-initial_co])[0])

    def test_correlation_and_retraction_after_retirement(self):
        inst = crossing()
        plan = prepare_frontier(inst, order=('i', 'z', 'b', 'a', 'r'),
                                co_mode='direct', summary_mode='ports')
        graph = GraphSolver(compile_frontier(inst, prepared=plan))
        reg = plan.registry
        peer = reg.literal(('rf', 'b', 'r'))
        own = reg.literal(('rf', 'a', 'r'))
        reverse = reg.literal(('co', 'b', 'a'))
        sequence = [(), (peer,), (peer, reverse), (peer,), (), (own, reverse), ()]
        models = list(enumerate_assignments(inst, reg))
        for alpha in sequence:
            live = [m for m in models if all(m[abs(l)] == (l > 0) for l in alpha)]
            ok, forced = graph.propagate(alpha)
            self.assertEqual(ok, bool(live))
            if live:
                expected = {v if live[0][v] else -v for v in reg.by_id
                            if all(m[v] == live[0][v] for m in live)}
                self.assertEqual(forced, expected)
        self.assertTrue(graph.propagate([peer])[0])
        self.assertTrue(graph.propagate([reverse])[0])
        self.assertFalse(graph.propagate([peer, reverse])[0])
        # Recompiling the exact same fixed plan is deterministic.
        self.assertEqual(compile_frontier(inst, prepared=plan).edges,
                         compile_frontier(inst, prepared=plan).edges)

    def test_bad_plan_rejected_and_resource_failure_distinguished(self):
        inst = crossing()
        kwargs = dict(co_mode='direct', summary_mode='ports')
        with self.assertRaisesRegex(ValueError, 'permutation'):
            prepare_frontier(inst, group_order=(0,), **kwargs)
        with self.assertRaisesRegex(ValueError, 'continuous'):
            prepare_frontier(inst, bags=(('i', 'a'), ('b', 'r', 'z'), ('i',)), **kwargs)
        with self.assertRaisesRegex(ValueError, 'covers'):
            prepare_frontier(inst, bags=(('i',), ('a',), ('r',), ('z',), ('b',)), **kwargs)
        plan = prepare_frontier(inst, **kwargs)
        with self.assertRaises(ResourceLimit) as error:
            compile_frontier(inst, prepared=plan, max_states=2)
        self.assertEqual(error.exception.stats['status'], 'UNKNOWN')
        self.assertEqual(error.exception.stats['resource_reason'], 'STATE_LIMIT')
        self.assertEqual(error.exception.stats['actual_K'], plan.stats['actual_K'])

    def test_external_certificate_must_include_closed_relations(self):
        inst = crossing()
        cert = recognize(inst)
        bad = dict(cert, H=set(inst.sb))
        with self.assertRaises(ValueError):
            prepare_frontier(inst, certificate=bad, co_mode='direct', summary_mode='ports')
        bad = dict(cert, mandatory=set())
        # This fixture has no forced source, so deliberately truncate D instead.
        bad['domains'] = dict(cert['domains'], r=set())
        with self.assertRaises(ValueError):
            prepare_frontier(inst, certificate=bad, co_mode='direct', summary_mode='ports')
        cert_outside = dict(cert, status='OUTSIDE')
        with self.assertRaises(ValueError):
            prepare_frontier(inst, certificate=cert_outside, co_mode='direct', summary_mode='ports')

    def test_dense_co_generators_preserve_full_relation(self):
        inst = crossing()
        cert = recognize(inst)
        sparse, dense = [prepare_frontier(inst, certificate=cert, co_mode='direct',
            summary_mode='ports', dense_co_generators=dense) for dense in (False, True)]
        self.assertGreater(len(dense.groups), len(sparse.groups))
        graphs = [GraphSolver(compile_frontier(inst, prepared=p)) for p in (sparse, dense)]
        for bits in itertools.product((False, True), repeat=sparse.registry.nvars):
            alpha = [v if bits[v-1] else -v for v in sparse.registry.by_id]
            self.assertEqual(graphs[0].propagate(alpha)[0], graphs[1].propagate(alpha)[0])
        with self.assertRaisesRegex(ValueError, 'direct CO'):
            prepare_frontier(inst, certificate=cert)


if __name__ == '__main__':
    unittest.main()
