import random
import unittest
from itertools import product
from wmcheck.model import Event
from wmcheck.ra import RAInstance, RARegistry
from wmcheck.ra_frontier import compile_frontier
from wmcheck.ra_object_layout import object_layout
from wmcheck.ra_objects import compile_objects
from wmcheck.ra_oracle import enumerate_assignments
from wmcheck.ra_splitter import Visit, extract_grid, grid_family, root_probe
from wmcheck.oracle import truth_under
from wmcheck.owned_dag import OwnedGraphSolver
from wmcheck.propagation import unit_propagate


OPTIONS = dict(co_mode='direct', summary_mode='ports', rf_mode='atomic', source_covers=True)


class ObjectProtocol(unittest.TestCase):
    def test_elided_initial_hb_matches_dense_two_address_models(self):
        rng = random.Random(20261019)
        for trial in range(28):
            events = [Event('ix', 'W', 'x', -1, 0), Event('iy', 'W', 'y', -1, 0)]
            threads = []
            for t in range(2):
                seq = []
                for j in range(2):
                    v = f't{t}_{j}'
                    events.append(Event(v, rng.choice(('R', 'W')), rng.choice(('x', 'y')), t, rng.randrange(2)))
                    seq.append(v)
                threads.append(tuple(seq))
            inst = RAInstance(tuple(events), tuple(threads), ('ix', 'iy'))
            reg = RARegistry(inst)
            models = list(enumerate_assignments(inst, reg))
            for mode in ('direct', 'successor'):
                opts = dict(OPTIONS, co_mode=mode, summary_mode='ports' if mode == 'direct' else 'full')
                engines = [OwnedGraphSolver(compile_frontier(inst, elide_init_hb=elide, **opts))
                           for elide in (False, True)]
                for _ in range(12):
                    alpha = [v*rng.choice((-1, 1)) for v in rng.sample(list(reg.by_id), min(3, reg.nvars))]
                    expected = truth_under(models, alpha)
                    for engine in engines:
                        self.assertEqual(engine.propagate(alpha), expected, (trial, mode, alpha))

    def test_object_factorization_all_small_partial_assignments(self):
        # X -> Y for both threads. RF can connect either writer to either read,
        # but cannot create an inter-object cycle. Compare every partial query.
        inst = RAInstance((Event('ix', 'W', 'x', -1, 0), Event('iy', 'W', 'y', -1, 0),
            Event('a', 'W', 'x', 0, 1), Event('b', 'R', 'y', 0, 1),
            Event('c', 'R', 'x', 1, 1), Event('d', 'W', 'y', 1, 1)),
            (('a', 'b'), ('c', 'd')), ('ix', 'iy'))
        c = compile_objects(inst, {'x': 'X', 'y': 'Y'}, cnf=True, **OPTIONS)
        models = list(enumerate_assignments(inst, c.registry))
        engine = OwnedGraphSolver(c)
        for values in product((-1, 0, 1), repeat=c.registry.nvars):
            alpha = [v*s for v, s in zip(c.registry.by_id, values) if s]
            expected = truth_under(models, alpha)
            self.assertEqual(engine.propagate(alpha), expected)
            up = unit_propagate(c.clauses, alpha)
            self.assertEqual(up.consistent, expected[0])
            if up.consistent:
                self.assertEqual({v if b else -v for v, b in up.values.items() if v in c.registry.by_id}, expected[1])

    def test_cyclic_object_split_is_rejected_and_would_be_unsound(self):
        # Load buffering: individually feasible objects, but an RF/SB HB cycle.
        inst = RAInstance((Event('ix', 'W', 'x', -1, 0), Event('iy', 'W', 'y', -1, 0),
            Event('rx', 'R', 'x', 0, 1), Event('wy', 'W', 'y', 0, 1),
            Event('ry', 'R', 'y', 1, 1), Event('wx', 'W', 'x', 1, 1)),
            (('rx', 'wy'), ('ry', 'wx')), ('ix', 'iy'))
        self.assertEqual(list(enumerate_assignments(inst, RARegistry(inst))), [])
        for loc in ('x', 'y'):
            es = tuple(e for e in inst.events if e.loc == loc)
            seq = tuple(tuple(v for v in s if inst.event[v].loc == loc) for s in inst.threads)
            local = RAInstance(es, seq, ('i'+loc,))
            self.assertTrue(list(enumerate_assignments(local, RARegistry(local))))
        with self.assertRaisesRegex(ValueError, 'cycle'):
            compile_objects(inst, {'x': 'X', 'y': 'Y'}, **OPTIONS)

    def test_random_dag_factorization_against_independent_models(self):
        rng = random.Random(78231)
        for trial in range(18):
            es = [Event('ix', 'W', 'x', -1, 0), Event('iy', 'W', 'y', -1, 0)]
            threads = []
            for t in range(2):
                seq = []
                for j, loc in enumerate(rng.choice((('x', 'x', 'y'), ('x', 'y', 'y')))):
                    eid = f't{t}_{j}'
                    es.append(Event(eid, rng.choice(('R', 'W')), loc, t, rng.randrange(2)))
                    seq.append(eid)
                threads.append(tuple(seq))
            inst = RAInstance(tuple(es), tuple(threads), ('ix', 'iy'))
            c = compile_objects(inst, {'x': 'X', 'y': 'Y'}, **OPTIONS)
            models = list(enumerate_assignments(inst, c.registry))
            engine = OwnedGraphSolver(c)
            for _ in range(24):
                alpha = [v*rng.choice((-1, 1)) for v in rng.sample(list(c.registry.by_id), min(4, c.registry.nvars))]
                self.assertEqual(engine.propagate(alpha), truth_under(models, alpha), (trial, alpha))

    def test_splitter_raw_sources_and_object_compilation(self):
        inst, layout, _ = root_probe()
        owners = {e.loc: layout['event_owner'][e.id] for e in inst.events}
        c = compile_objects(inst, owners, cnf=True, **OPTIONS)
        reg = c.registry
        models = list(enumerate_assignments(inst, reg))
        self.assertEqual(len(models), 88)
        engine = OwnedGraphSolver(c)
        rng = random.Random(19102026)
        for _ in range(100):
            alpha = [v*rng.choice((-1, 1)) for v in rng.sample(list(reg.by_id), 4)]
            self.assertEqual(engine.propagate(alpha), truth_under(models, alpha))
        self.assertLessEqual(c.stats['max_interface'], c.stats['theorem_interface_bound'])

    def test_extractor_rejects_branch_and_boundary_mismatches(self):
        with self.assertRaisesRegex(ValueError, 'unlogged branch'):
            extract_grid(((Visit(0, 0, 0, 'probe'), Visit(0, 1, 0, 'stop')), (), ()))
        with self.assertRaisesRegex(ValueError, 'Route'):
            extract_grid(((Visit(0, 0, 0, 'right'), Visit(0, 1, 0, 'stop')), (), ()))
        with self.assertRaisesRegex(ValueError, 'boundary'):
            extract_grid(((Visit(0, 0, 0, 'right'), Visit(0, 0, 1, 'right'), Visit(0, 0, 2, 'stop')), (), ()))

    def test_batches_keep_all_original_identities_and_supports(self):
        inst, layout, _ = grid_family(3, 3, duplicate_stop=True)
        owners = {e.loc: layout['event_owner'][e.id] for e in inst.events}
        normal = compile_frontier(inst, order=layout['order'], elide_init_hb=True, **OPTIONS)
        factor = compile_objects(inst, owners, **OPTIONS)
        self.assertEqual(normal.registry.by_id, factor.registry.by_id)
        a, b = OwnedGraphSolver(normal), OwnedGraphSolver(factor)
        rng = random.Random(321)
        for _ in range(60):
            alpha = [v*rng.choice((-1, 1)) for v in rng.sample(list(factor.registry.by_id), 4)]
            self.assertEqual(a.propagate(alpha), b.propagate(alpha))


if __name__ == '__main__':
    unittest.main()
