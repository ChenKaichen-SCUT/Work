import random
import unittest
from itertools import product

from wmcheck.compiler import compile_instance
from wmcheck.generators import make_instance
from wmcheck.graph_solver import GraphSolver
from wmcheck.model import Event,Axiom,Instance
from wmcheck.oracle import enumerate_models,truth_under
from wmcheck.propagation import unit_propagate
from wmcheck.summary import close,cyclic,close_dag
from wmcheck.complete_query import forced_by_search
from wmcheck.eager import encode
from pysat.solvers import Minisat22


class Optimizations(unittest.TestCase):
    def test_closure_exhaustive_three_vertices_and_random(self):
        cases=[tuple((mask>>(3*i))&7 for i in range(3)) for mask in range(512)]
        rng=random.Random(771)
        for _ in range(500):
            n=rng.randrange(1,25)
            cases.append(tuple(sum(1<<j for j in range(n) if rng.random()<.08) for _ in range(n)))
        for rows in cases:
            expected=close(rows)
            self.assertEqual(close_dag(rows),None if cyclic(expected) else expected)
        n=2000
        result=close_dag(tuple(1<<(i+1) if i+1<n else 0 for i in range(n)))
        self.assertEqual(result[0],(1<<n)-2)

    def test_directional_quotient_and_graph_against_full_oracle(self):
        rng=random.Random(342)
        events=(Event('a','W','x',0),Event('b','W','x',1),Event('r','R','x',0),
                Event('c','W','y',1),Event('s','R','y',0),Event('d','W','x',1))
        blocks=(('a','b'),('r','c'),('s','d'))
        for case in range(120):
            axes=[]
            for j in range(1+case%2):
                fixed=tuple((a.id,b.id) for a in events for b in events if a!=b and rng.random()<.08)
                axes.append(Axiom(str(j),fixed,('all','ext','none')[case%3],bool(case%2),bool((case//2)%2)))
            inst=Instance(events,blocks,{'r':('a','b'),'s':('c',)},tuple(axes))
            optimized=compile_instance(inst)
            reference=compile_instance(inst,directional=False,minimize=False)
            graph=GraphSolver(optimized)
            models=list(enumerate_models(inst,optimized.registry))
            variables=list(optimized.registry.by_id)
            for values in product((-1,0,1),repeat=len(variables)):
                alpha=[v*s for v,s in zip(variables,values) if s]
                expected=truth_under(models,alpha)
                self.assertEqual(graph.propagate(alpha),expected,(case,alpha))
                for compiled in (optimized,reference):
                    result=unit_propagate(compiled.clauses,alpha)
                    self.assertEqual(result.consistent,expected[0],(case,alpha))
                    if result.consistent:
                        got={v if b else -v for v,b in result.values.items() if v in compiled.registry.by_id}
                        self.assertEqual(got,expected[1],(case,alpha))
                witness=graph.witness(alpha)
                if expected[0]:
                    self.assertTrue(truth_under(models,witness)[0])
                    self.assertEqual(len(witness),len(variables))
                else: self.assertIsNone(witness)

    def test_protocol_direct_and_cnf_match_with_witness(self):
        inst=make_instance(rounds=2)
        compiled=compile_instance(inst)
        graph=GraphSolver(compiled)
        models=list(enumerate_models(inst,compiled.registry,dense_tso=True))
        rng=random.Random(982)
        for _ in range(300):
            alpha=[v*rng.choice((-1,1)) for v in compiled.registry.by_id if rng.random()<.1]
            self.assertEqual(graph.propagate(alpha),truth_under(models,alpha))
            witness=graph.witness(alpha)
            if witness is not None:
                self.assertTrue(truth_under(models,witness)[0])
                self.assertEqual(len(witness),compiled.registry.nvars)
        v=next(iter(compiled.registry.by_id))
        self.assertEqual(graph.propagate([v,-v]),(False,set()))
        with self.assertRaises(ValueError): graph.propagate([compiled.registry.nvars+1])
        plain=compile_instance(inst,cnf=False)
        self.assertEqual(GraphSolver(plain).propagate(),graph.propagate())

    def test_search_comparator_returns_every_forced_literal(self):
        inst=make_instance(rounds=2);enc=encode(inst)
        models=list(enumerate_models(inst,enc.registry,dense_tso=True))
        rng=random.Random(888)
        with Minisat22(bootstrap_with=enc.clauses) as solver:
            _,root,_=forced_by_search(solver,enc.registry.by_id)
            self.assertEqual(root,truth_under(models,[])[1])
            for _ in range(120):
                alpha=[v*rng.choice((-1,1)) for v in enc.registry.by_id if rng.random()<.1]
                ok,forced,_=forced_by_search(solver,enc.registry.by_id,alpha,known=root)
                self.assertEqual((ok,forced),truth_under(models,alpha))


if __name__=='__main__': unittest.main()
