import random
import re
import unittest
from itertools import product

from wmcheck.model import Event
from wmcheck.ra import RAInstance, RARegistry, recognize, producers, pipeline
from wmcheck.ra_oracle import enumerate_assignments, valid
from wmcheck.ra_schedule import compile_schedule, compile_co_first, OutsideCertificate
from wmcheck.ra_frontier import compile_frontier
from wmcheck.regular_monitor import ra_monitors, rotation_automaton, seq, update
from wmcheck.owned_dag import OwnedGraphSolver, check_ownership
from wmcheck.propagation import unit_propagate
from wmcheck.oracle import truth_under
from wmcheck.compiler import Compiled, Transition
from wmcheck.ra_order_sat import encode_order
from wmcheck.complete_query import forced_by_search
from pysat.solvers import Minisat22
from wmcheck.ra_grid import compile_grid, GridSolver, grid_cnf


class RAConstruction(unittest.TestCase):
    def compare(self, inst, graphs, count=100, exhaustive=False):
        models = list(enumerate_assignments(inst, graphs[0].registry))
        variables = list(graphs[0].registry.by_id)
        if exhaustive:
            queries = [tuple(v*s for v, s in zip(variables, values) if s)
                       for values in product((-1, 0, 1), repeat=len(variables))]
        else:
            rng = random.Random(1014)
            queries = [()] + [(v,) for v in variables] + [(-v,) for v in variables]
            queries += [tuple(v*rng.choice((-1, 1)) for v in variables if rng.random() < rng.choice((.1, .4, .8)))
                        for _ in range(count)]
        engines = [OwnedGraphSolver(c) for c in graphs]
        for alpha in queries:
            expected = truth_under(models, alpha)
            for c, engine in zip(graphs, engines):
                self.assertEqual(engine.propagate(alpha), expected, (c.stats, alpha))
                if c.clauses:
                    result = unit_propagate(c.clauses, alpha)
                    actual = {v if b else -v for v, b in result.values.items() if v in c.registry.by_id}
                    self.assertEqual(result.consistent, expected[0], alpha)
                    if result.consistent:
                        self.assertEqual(actual, expected[1], alpha)
                witness = engine.witness(alpha)
                self.assertEqual(witness is not None, expected[0])
                if witness is not None:
                    self.assertTrue(truth_under(models, witness)[0])
                    self.assertEqual(len(witness), c.registry.nvars)
        return len(queries)

    def test_rotated_ra_word_languages(self):
        monitors = ra_monitors()
        regexes = (r'[sr]+(?:r|c|Rc+)*', r'c+', r'qc+')
        for monitor, expression in zip(monitors, regexes):
            table = dict(monitor.transitions)
            alphabet = tuple(table)
            for n in range(6):
                for word in product(alphabet, repeat=n):
                    text = ''.join(word); q = 0
                    for s in word:
                        q = table[s][q]
                    expected = any(re.fullmatch(expression, text[i:]+text[:i]) is not None
                                   for i in range(max(1, len(text))))
                    self.assertEqual(q in monitor.final, expected, text)

    def test_forgotten_start_and_intermediate_states(self):
        m = rotation_automaton(seq('a', 'b', 'c'))
        # abc starts at u; u is forgotten before b arrives. Must detect bca.
        for incremental in (False, True):
            rows = update(m, (), (), ('u', 'v', 'w'), ('v', 'w'),
                          (('a', 'u', 'w'), ('c', 'v', 'u')), incremental)
            self.assertIsNotNone(rows)
            self.assertIsNone(update(m, rows, ('v', 'w'), ('v', 'w'), ('v', 'w'),
                                     (('b', 'w', 'v'),), incremental))

    def test_shared_rotation_cut_all_short_words(self):
        paired = ra_monitors(compact=True)[0]
        dfa = ra_monitors()[0]; table = dict(dfa.transitions)
        for n in range(7):
            for word in product('srRc', repeat=n):
                current = list(paired.initial_rows); q = 0
                for s in word:
                    q = table[s][q]
                    nxt = []
                    for row in current:
                        value = 0
                        for a, b in paired.edge_map[s]:
                            if row & (1 << a):
                                value |= paired.initial_rows[b]
                        nxt.append(value)
                    current = nxt
                self.assertEqual(any(current[a] & (1 << b) for a, b in paired.accept_pairs), q in dfa.final, word)
        inst = pipeline(1)
        self.compare(inst, [compile_frontier(inst, compact=False), compile_frontier(inst, compact=True)], count=150)

    def test_exhaustive_partial_assignments(self):
        i = producers((1, 1))
        dynamic = compile_schedule(i, cnf=True)
        self.assertTrue(check_ownership(dynamic, dynamic.owned))
        graphs = [dynamic, compile_co_first(i, cnf=True), compile_frontier(i, cnf=True)]
        self.assertEqual(self.compare(i, graphs, exhaustive=True), 2187)

    def test_incremental_closure_matches_full_joint_graph(self):
        for i in (producers((1, 1)), producers((2, 1)), pipeline(1)):
            a, b = [compile_frontier(i, incremental=x, max_seconds=60) for x in (False, True)]
            self.assertEqual(a.layers, b.layers)
            self.assertEqual(a.edges, b.edges)
            self.compare(i, [a, b], count=80)

    def test_generalized_scheduling_values_and_readers(self):
        cases = [producers((2, 2)), producers((2, 1, 1)),
                 producers((2, 1), ((0, 1), (1,)), ((1, 0), (1,))),
                 producers((1, 1), ((2,),)), producers((), ((0, 0),))]
        for i in cases:
            c = compile_schedule(i, cnf=True)
            self.assertTrue(check_ownership(c, c.owned))
            self.compare(i, [c], count=160)
        with self.assertRaises(OutsideCertificate):
            compile_schedule(pipeline(1))

    def test_random_small_ra_including_mixed_threads(self):
        rng = random.Random(3881)
        for case in range(40):
            events = [Event('ix', 'W', 'x', -1, 0), Event('iy', 'W', 'y', -1, 0)]
            threads = []
            for t in range(2):
                seq_ = []
                for j in range(2):
                    v = f'e{t}{j}'; seq_.append(v)
                    events.append(Event(v, rng.choice(('W', 'R')), rng.choice(('x', 'y')), t, rng.randrange(2)))
                threads.append(tuple(seq_))
            inst = RAInstance(tuple(events), tuple(threads), ('ix', 'iy'))
            c = compile_frontier(inst, cnf=True)
            self.compare(inst, [c], count=40)

    def test_real_ra_non_sc_execution_and_original_constants(self):
        i = pipeline(1); c = compile_frontier(i, cnf=True)
        # Ax ->sb Ay ->co By ->sb Bx ->co Ax is allowed by RA.
        rf = {'t0_1_read': 't0_1_x', 't1_1_read': 't1_1_x',
              't0_1_wait': 'ifb', 't1_1_wait': 'ifa'}
        orders = {'x': ('ix', 't1_1_x', 't0_1_x'), 'y': ('iy', 't0_1_y', 't1_1_y'),
                  'fa': ('ifa', 't0_1_flag'), 'fb': ('ifb', 't1_1_flag')}
        self.assertTrue(valid(i, rf, orders))
        alpha = [c.registry.literal(('rf', w, r)) for r, w in rf.items()]
        alpha += [c.registry.literal(('co', ws[j], ws[j+1])) for ws in orders.values() for j in range(len(ws)-1)]
        self.assertTrue(OwnedGraphSolver(c).propagate(alpha)[0])
        self.compare(i, [c], count=150)
        for n in range(1, 8):
            cert = recognize(pipeline(n))
            self.assertEqual(cert['status'], 'RECOGNIZED')
            for t in range(2):
                for stage in range(1, n+1):
                    source = ('ifb' if t == 0 else 'ifa') if stage == 1 else f't{1-t}_{stage-1}_flag'
                    self.assertEqual(cert['domains'][f't{t}_{stage}_wait'], {source})

    def test_bad_ownership_and_contradictory_queries(self):
        c = compile_schedule(producers((1, 1)))
        bad = Compiled(c.registry, c.layers, list(c.edges), [], c.nvars, {})
        e = bad.edges[1]
        bad.edges[1] = Transition(e.layer, e.source, e.target, e.label+(1,))
        with self.assertRaises(ValueError):
            check_ownership(bad, c.owned)
        g = OwnedGraphSolver(c)
        self.assertEqual(g.propagate((1, -1)), (False, set()))
        with self.assertRaises(ValueError):
            g.propagate((c.registry.nvars+1,))

    def test_structure_aware_sat_comparator(self):
        for inst in (producers((2, 2)), producers((1, 1, 1)),
                     producers((2, 1), ((0, 1), (1,)), ((1, 0), (1,)))):
            enc = encode_order(inst)
            models = list(enumerate_assignments(inst, enc.registry))
            rng = random.Random(456)
            with Minisat22(bootstrap_with=enc.clauses) as s:
                for j in range(120):
                    alpha = [v*rng.choice((-1, 1)) for v in enc.registry.by_id if rng.random() < (j % 5)/5]
                    ok, forced, _ = forced_by_search(s, enc.registry.by_id, alpha)
                    self.assertEqual((ok, forced), truth_under(models, alpha))

    def test_range_labels_exact_graph_and_complete_cnf(self):
        reversed_producers = producers((2, 1))
        reversed_producers = RAInstance(reversed_producers.events,
                                       (reversed_producers.threads[1], reversed_producers.threads[0],
                                        reversed_producers.threads[2]), reversed_producers.initial)
        cases = [producers((1, 1)), producers((2, 2)),
                 producers((2, 1), ((0, 1, 0),), ((1, 0), (1,))),
                 producers((1, 1), ((2,),)), reversed_producers]
        for inst in cases:
            compact = compile_grid(inst); expanded = compact.expand(); dynamic = compile_schedule(inst)
            self.assertEqual(expanded.layers, dynamic.layers)
            self.assertEqual(expanded.edges, dynamic.edges)
            graph = GridSolver(compact); enc = grid_cnf(compact)
            models = list(enumerate_assignments(inst, compact.registry))
            variables = list(compact.registry.by_id)
            if len(variables) <= 7:
                queries = [tuple(v*s for v, s in zip(variables, values) if s)
                           for values in product((-1, 0, 1), repeat=len(variables))]
            else:
                rng = random.Random(1141)
                queries = [[v*rng.choice((-1, 1)) for v in variables if rng.random() < .3] for _ in range(300)]
                queries += [[v if value else -v for v, value in model.items() if rng.random() < .3]
                            for model in models[:100]]
            for alpha in queries:
                expected = truth_under(models, alpha)
                self.assertEqual(graph.propagate(alpha), expected)
                result = unit_propagate(enc.clauses, alpha)
                self.assertEqual(result.consistent, expected[0])
                if expected[0]:
                    actual = {v if truth else -v for v, truth in result.values.items() if v in compact.registry.by_id}
                    self.assertEqual(actual, expected[1])
            self.assertEqual(graph.propagate([1, -1]), (False, set()))
            with self.assertRaises(ValueError):
                graph.propagate([compact.registry.nvars+1])


if __name__ == '__main__':
    unittest.main()
