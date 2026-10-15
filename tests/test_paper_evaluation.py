"""Independent semantic checks for the new comparison and program adapters."""
import random
import unittest
from itertools import product
from wmcheck.ra import RAInstance, RARegistry, producers, pipeline
from wmcheck.model import Event
from wmcheck.ra_sat import encode_ra
from wmcheck.ra_order_sat import encode_order
from wmcheck.ra_oracle import enumerate_assignments
from wmcheck.ra_frontier import compile_frontier
from wmcheck.owned_dag import OwnedGraphSolver
from wmcheck.ra_program import export_litmus, parse_c_litmus
from wmcheck.complete_query import forced_by_search
from pysat.solvers import Minisat22


class PaperTests(unittest.TestCase):
    def test_sat_projection_against_dense_definition(self):
        rng=random.Random(912)
        for case in range(30):
            es=[Event('ix','W','x',-1,0),Event('iy','W','y',-1,0)];ts=[]
            for t in range(2):
                seq=[]
                for j in range(2):
                    v=f't{t}_{j}';kind=rng.choice(('R','W'));loc=rng.choice(('x','y'))
                    val=rng.choice((0,1,None)) if kind=='R' else rng.choice((0,1))
                    es.append(Event(v,kind,loc,t,val));seq.append(v)
                ts.append(tuple(seq))
            inst=RAInstance(tuple(es),tuple(ts),('ix','iy'));e=encode_ra(inst)
            oracle={tuple(v if m[v] else -v for v in e.registry.by_id)
                    for m in enumerate_assignments(inst,e.registry)}
            got=set()
            with Minisat22(bootstrap_with=e.clauses) as s:
                while s.solve():
                    model={abs(l):l for l in s.get_model()}
                    row=tuple(model[v] for v in e.registry.by_id);got.add(row)
                    s.add_clause([-l for l in row])
            self.assertEqual(oracle,got,case)

    def test_initialization_sparsification(self):
        for inst in (pipeline(1),producers((1,1),((None,None),))):
            a=OwnedGraphSolver(compile_frontier(inst,sparse_init=False))
            b=OwnedGraphSolver(compile_frontier(inst,sparse_init=True))
            reg=a.compiled.registry;rng=random.Random(4)
            for _ in range(64):
                alpha=[v*rng.choice((-1,1)) for v in reg.by_id if rng.random()<.2]
                self.assertEqual(a.propagate(alpha),b.propagate(alpha))

    def test_degree_deadline_pruning(self):
        from wmcheck.query_sat_up import forced_with_up
        # Checks the original support interface, including contradictory and
        # satisfiable partial assignments, against an independent SAT encoding.
        for inst in (pipeline(1),producers((1,1),((None,None),))):
            e=encode_ra(inst)
            g=OwnedGraphSolver(compile_frontier(inst,early_degrees=True))
            rng=random.Random(814)
            with Minisat22(bootstrap_with=e.clauses) as s:
                for _ in range(150):
                    alpha=[v*rng.choice((-1,1)) for v in e.registry.by_id if rng.random()<.3]
                    ok,forced,_=forced_by_search(s,e.registry.by_id,alpha)
                    self.assertEqual((ok,forced),g.propagate(alpha))
                    self.assertEqual((ok,forced),forced_with_up(s,e.registry.by_id,alpha)[:2])
                    self.assertEqual((ok,forced),forced_with_up(s,e.registry.by_id,alpha,flip_phases=True)[:2])

    def test_direct_co_generators(self):
        rng=random.Random(316)
        fixtures=[pipeline(1),pipeline(2),producers((1,1),((None,None),))]
        for case in range(24):
            es=[Event('ix','W','x',-1,0),Event('iy','W','y',-1,0)];ts=[]
            for t in range(2):
                seq=[]
                for j in range(2):
                    v=f't{t}_{j}';kind=rng.choice(('R','W'));loc=rng.choice(('x','y'))
                    val=rng.choice((0,1,None)) if kind=='R' else rng.choice((0,1))
                    seq.append(v);es.append(Event(v,kind,loc,t,val))
                ts.append(tuple(seq))
            fixtures.append(RAInstance(tuple(es),tuple(ts),('ix','iy')))
        for inst in fixtures:
            e=encode_ra(inst)
            g=OwnedGraphSolver(compile_frontier(inst,early_degrees=True,co_mode='direct'))
            with Minisat22(bootstrap_with=e.clauses) as s:
                for _ in range(64):
                    alpha=[v*rng.choice((-1,1)) for v in e.registry.by_id if rng.random()<.3]
                    ok,forced,_=forced_by_search(s,e.registry.by_id,alpha)
                    self.assertEqual((ok,forced),g.propagate(alpha))

    def test_direct_co_cnf_and_non_sc(self):
        from wmcheck.propagation import unit_propagate
        inst=producers((1,1));e=encode_ra(inst)
        c=compile_frontier(inst,cnf=True,early_degrees=True,co_mode='direct')
        variables=list(c.registry.by_id)
        with Minisat22(bootstrap_with=e.clauses) as s:
            for signs in product((-1,0,1),repeat=len(variables)):
                alpha=[v*sign for v,sign in zip(variables,signs) if sign]
                ok,forced,_=forced_by_search(s,variables,alpha);up=unit_propagate(c.clauses,alpha)
                got={v if val else -v for v,val in up.values.items() if v in c.registry.by_id} if up.consistent else set()
                self.assertEqual((ok,forced),(up.consistent,got))
        # A genuine RA execution with an HB/CO alternating cycle, forbidden by SC.
        c=compile_frontier(pipeline(1),co_mode='direct',early_degrees=True)
        rf={'t0_1_read':'t0_1_x','t1_1_read':'t1_1_x','t0_1_wait':'ifb','t1_1_wait':'ifa'}
        alpha=[c.registry.literal(('rf',w,r)) for r,w in rf.items()]
        alpha += [c.registry.literal(('co','t1_1_x','t0_1_x')),c.registry.literal(('co','t0_1_y','t1_1_y'))]
        self.assertTrue(OwnedGraphSolver(c).propagate(alpha)[0])

    def test_litmus_roundtrip_and_observation_encoding(self):
        inst=pipeline(1);p=parse_c_litmus(export_litmus(inst))
        constrained=encode_ra(p.conditioned());unconstrained=encode_ra(p.instance)
        with Minisat22(bootstrap_with=constrained.clauses) as a, Minisat22(
                bootstrap_with=unconstrained.clauses+p.clauses(unconstrained.registry)) as b:
            self.assertEqual(a.solve(),b.solve())
        with self.assertRaises(ValueError):
            parse_c_litmus(export_litmus(inst).replace('memory_order_release','memory_order_relaxed'))

    def test_bdd_complete_support(self):
        try:
            from dd.cudd import BDD
        except ImportError:
            self.skipTest('CUDD comparison dependency is installed on the experiment server')
        from wmcheck.ra_bdd import BDDCompiler
        from wmcheck.ra_bdd_relational import RelationalBDD
        for inst in (producers((1,1),((None,),)),pipeline(1)):
            e=encode_order(inst) if len(inst.initial)==1 else encode_ra(inst);b=BDDCompiler(e);direct=RelationalBDD(inst)
            ordered=RelationalBDD(inst,coherence_first=True,semantic_order=True)
            rng=random.Random(11)
            with Minisat22(bootstrap_with=e.clauses) as s:
                for _ in range(150):
                    alpha=[v*rng.choice((-1,1)) for v in e.registry.by_id if rng.random()<.3]
                    ok,forced,_=forced_by_search(s,e.registry.by_id,alpha)
                    self.assertEqual((ok,forced),b.propagate(alpha))
                    self.assertEqual((ok,forced),direct.propagate(alpha))
                    self.assertEqual((ok,forced),ordered.propagate(alpha))


if __name__=='__main__':unittest.main()
