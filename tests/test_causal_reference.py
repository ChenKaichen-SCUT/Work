"""Acceptance of complete assignments, correlations and retractable SAT queries."""
import unittest
from types import SimpleNamespace
from itertools import product
from pysat.solvers import Solver
from wmcheck.model import Event
from wmcheck.ra import RAInstance, RARegistry, recognize, producers
from wmcheck.ra_reference import (evaluate_assignment, enumerate_completions,
                                  all_boolean_assignments, supports_from_models,
                                  has_sc_linearization)
from wmcheck.ra_support_sat import SupportSAT
from wmcheck.ra_frontier import compile_frontier
from wmcheck.graph_solver import GraphSolver


def data_pair():
    events = (Event('ix', 'W', 'x', -1, 0), Event('iy', 'W', 'y', -1, 0),
              Event('ax', 'W', 'x', 0, 1), Event('ay', 'W', 'y', 0, 1),
              Event('ar', 'R', 'x', 0, 1), Event('by', 'W', 'y', 1, 1),
              Event('bx', 'W', 'x', 1, 1), Event('br', 'R', 'y', 1, 1))
    return RAInstance(events, (('ax', 'ay', 'ar'), ('by', 'bx', 'br')), ('ix', 'iy'))


class CausalReferenceTests(unittest.TestCase):
    def test_full_boolean_cube_raw_sat_and_compiler(self):
        inst = producers((1, 1), ((1,),))
        registry = RARegistry(inst)
        compiled = compile_frontier(inst, co_mode='direct', summary_mode='ports', cnf=True)
        graph = GraphSolver(compiled)
        with SupportSAT(inst) as sat, Solver(name='cadical195', bootstrap_with=compiled.clauses) as encoded:
            for x in all_boolean_assignments(registry):
                expected = evaluate_assignment(inst, x)
                self.assertEqual(expected, sat.solve(x), x)
                self.assertEqual(expected, graph.propagate(x)[0], x)
                self.assertEqual(expected, encoded.solve(assumptions=list(x)), x)

    def test_data_correlation_non_sc_projection_and_retraction(self):
        inst = data_pair()
        registry = RARegistry(inst)
        graph = GraphSolver(compile_frontier(inst, co_mode='direct', summary_mode='ports'))
        models = set(enumerate_completions(inst))
        self.assertTrue(any(not has_sc_linearization(inst, x) for x in models))
        cross = registry.literal(('rf', 'bx', 'ar'))
        opposite = registry.literal(('co', 'bx', 'ax'))
        own = registry.literal(('rf', 'ax', 'ar'))
        queries = [(), (cross,), (cross, opposite), (cross,), (), (own, opposite), ()]
        with SupportSAT(inst) as raw, SupportSAT(inst, recognize(inst)) as filtered:
            for x in all_boolean_assignments(registry):
                expected = x in models
                self.assertEqual(expected, evaluate_assignment(inst, x))
                self.assertEqual(expected, raw.solve(x))
                self.assertEqual(expected, filtered.solve(x))
                self.assertEqual(expected, graph.propagate(x)[0])
            for alpha in queries:
                expected = supports_from_models(models, alpha)
                self.assertEqual(expected, raw.supports(alpha))
                self.assertEqual(expected, filtered.supports(alpha))
                ok, forced = graph.propagate(alpha)
                observed = {lit for v in registry.by_id for lit in (v, -v)
                            if ok and -lit not in forced}
                self.assertEqual(expected, (ok, observed))
            self.assertFalse(raw.solve((cross, opposite)))
            self.assertTrue(raw.solve((own, opposite)))
            self.assertTrue(evaluate_assignment(inst, raw.model_original()))

    def test_original_guard_is_not_unconstrained_none(self):
        events = (Event('iwp', 'W', 'wp', -1, 0), Event('irp', 'W', 'rp', -1, 0),
                  Event('own', 'R', 'wp', 0, None), Event('peer', 'R', 'rp', 0, None),
                  Event('ack', 'W', 'rp', 1, 1))
        inst = RAInstance(events, (('own', 'peer'), ('ack',)), ('iwp', 'irp'))
        value = SimpleNamespace(inst=inst, allowed_values=None,
                                guards=({'op': 'buffer_full', 'own': 'own', 'peer': 'peer',
                                         'modulus': 2, 'outcome': False},))
        registry = RARegistry(inst)
        forbidden = registry.literal(('rf', 'ack', 'peer'))
        models = set(enumerate_completions(value))
        self.assertTrue(models)
        with SupportSAT(value) as sat, SupportSAT(inst) as unguarded:
            self.assertFalse(sat.solve((forbidden,)))
            self.assertTrue(unguarded.solve((forbidden,)))
            for x in all_boolean_assignments(registry):
                self.assertEqual(x in models, sat.solve(x))
                self.assertEqual(x in models, evaluate_assignment(value, x))
            self.assertEqual(supports_from_models(models), sat.supports())

    def test_allowed_values_and_fixed_constants_stay_queryable(self):
        inst = producers((1,), ((None,),))
        value = SimpleNamespace(inst=inst, guards=(), allowed_values={inst.reads[0]: (1,)})
        registry = RARegistry(inst)
        initial = registry.literal(('rf', 'init', inst.reads[0]))
        co = registry.literal(('co', 'init', inst.writes[-1]))
        models = set(enumerate_completions(value))
        with SupportSAT(value) as sat:
            self.assertEqual(supports_from_models(models), sat.supports())
            self.assertFalse(sat.single_support(initial))
            self.assertTrue(sat.single_support(-initial))
            self.assertFalse(sat.single_support(-co))
            self.assertTrue(sat.single_support(co))
            self.assertEqual(supports_from_models(models), sat.supports())

    def test_malformed_full_assignments_rejected(self):
        inst = producers((1,), ((1,),))
        registry = RARegistry(inst)
        model = next(enumerate_completions(inst))
        self.assertFalse(evaluate_assignment(inst, ()))
        self.assertFalse(evaluate_assignment(inst, set(model) | {-next(iter(model))}))
        self.assertFalse(evaluate_assignment(inst, {v: 1 for v in registry.by_id}))
        with SupportSAT(inst) as sat:
            with self.assertRaises(ValueError):
                sat.supports((registry.nvars + 1,))

    def test_every_small_protocol_prefix_full_projection(self):
        from wmcheck.ra_protocols import barrier_instance, buffer_instance, prefix_input, build_protocol
        families = [barrier_instance(1, workers=1, data=False),
                    buffer_instance(1, capacity=2, mode='value', data=False),
                    buffer_instance(1, capacity=2, mode='branch', data=False)]
        for family in families:
            ranges = [range(len(thread) + 1) for thread in family.inst.threads]
            for lengths in product(*ranges):
                inp = prefix_input(family, dict(enumerate(lengths)))
                result = build_protocol(inp)
                self.assertNotEqual('OUTSIDE', result['status'], lengths)
                registry = RARegistry(inp.inst)
                graph = GraphSolver(compile_frontier(inp.inst, certificate=result['certificate'],
                                    order=result['order'], co_mode='direct', summary_mode='ports'))
                with SupportSAT(inp) as raw, SupportSAT(inp, result['certificate']) as filtered:
                    for x in all_boolean_assignments(registry, max_variables=10):
                        expected = evaluate_assignment(inp, x)
                        self.assertEqual(expected, raw.solve(x), (lengths, x))
                        self.assertEqual(expected, filtered.solve(x), (lengths, x))
                        self.assertEqual(expected, graph.propagate(x)[0], (lengths, x))

    def test_premature_full_is_semantically_unsat(self):
        from wmcheck.ra_protocols import buffer_instance, build_protocol
        inp = buffer_instance(0, capacity=2, mode='branch', producer_tail_failures=1, data=False)
        result = build_protocol(inp)
        self.assertEqual('PROVED_UNSAT', result['status'])
        self.assertEqual([], list(enumerate_completions(inp)))
        with SupportSAT(inp) as raw, SupportSAT(inp, result) as filtered:
            self.assertEqual((False, set()), raw.supports())
            self.assertEqual((False, set()), filtered.supports())
        with self.assertRaises(ValueError):
            SupportSAT(inp, {'status': 'OUTSIDE', 'certificate': None})


if __name__ == '__main__':
    unittest.main()
