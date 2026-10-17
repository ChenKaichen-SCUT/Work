import random
import unittest
from itertools import product
from pysat.solvers import Minisat22
from wmcheck.model import Event
from wmcheck.ra import RAInstance, RARegistry
from wmcheck.ra_frontier import compile_frontier
from wmcheck.ra_publication import publication_exchange, publication_layout
from wmcheck.ra_oracle import enumerate_assignments
from wmcheck.ra_sat import encode_ra
from wmcheck.oracle import truth_under
from wmcheck.propagation import unit_propagate
from wmcheck.owned_dag import OwnedGraphSolver
from wmcheck.complete_query import forced_by_search
from wmcheck.trace_diagnosis import diagnose, publication_logs
from wmcheck.dag_reduce import reduce_dag


class AtomicDiagnosis(unittest.TestCase):
    def test_atomic_all_partial_assignments_and_cnf(self):
        inst=RAInstance((Event('i','W','x',-1,0),Event('a','W','x',0,1),
                         Event('b','W','x',0,1),Event('r','R','x',1,1)),(('a','b'),('r',)),('i',))
        c=compile_frontier(inst,co_mode='direct',summary_mode='ports',rf_mode='atomic',cnf=True)
        models=list(enumerate_assignments(inst,c.registry));engine=OwnedGraphSolver(c)
        for values in product((-1,0,1),repeat=c.registry.nvars):
            alpha=tuple(v*s for v,s in zip(c.registry.by_id,values) if s)
            expected=truth_under(models,alpha)
            self.assertEqual(engine.propagate(alpha),expected)
            up=unit_propagate(c.clauses,alpha)
            self.assertEqual(up.consistent,expected[0])
            if up.consistent:
                self.assertEqual({v if b else -v for v,b in up.values.items() if v in c.registry.by_id},expected[1])

    def test_atomic_random_against_independent_dense_models(self):
        rng=random.Random(20161017)
        for trial in range(40):
            events=[Event('i','W','x',-1,0)];threads=[]
            for t in range(2):
                seq=[]
                for j in range(2):
                    v=f't{t}_{j}';seq.append(v)
                    events.append(Event(v,rng.choice(('W','R')),'x',t,rng.randrange(2)))
                threads.append(tuple(seq))
            inst=RAInstance(tuple(events),tuple(threads),('i',));reg=RARegistry(inst)
            models=list(enumerate_assignments(inst,reg))
            for co_mode,summary in (('direct','ports'),('successor','full')):
                c=compile_frontier(inst,co_mode=co_mode,summary_mode=summary,source_covers=True,rf_mode='atomic')
                engine=OwnedGraphSolver(c)
                for _ in range(12):
                    alpha=[v*rng.choice((-1,1)) for v in rng.sample(list(reg.by_id),min(reg.nvars,3))]
                    self.assertEqual(engine.propagate(alpha),truth_under(models,alpha),(trial,alpha))

    def test_diagnosis_outputs_and_every_repair(self):
        inst=publication_exchange(2);reg=RARegistry(inst)
        c=compile_frontier(inst,order=publication_layout(inst,2),co_mode='direct',summary_mode='ports',
                           rf_mode='atomic',source_covers=True,early_degrees=True)
        reduced=reduce_dag(c,cnf=True)
        engine=OwnedGraphSolver(reduced);enc=encode_ra(inst)
        with Minisat22(bootstrap_with=enc.clauses) as sat:
            query=lambda a: forced_by_search(sat,reg.by_id,a)[:2]
            for log in publication_logs(inst,2):
                obs=log['observations'];answer=diagnose(reg,engine.propagate,obs)
                self.assertEqual(answer,diagnose(reg,query,obs))
                self.assertEqual(engine.propagate(obs),OwnedGraphSolver(c).propagate(obs))
                if answer['snapshot']['consistent']:continue
                core=answer['conflict'];self.assertFalse(sat.solve(assumptions=core))
                for lit in core:
                    self.assertTrue(sat.solve(assumptions=[l for l in core if l!=lit]))
                for repair in answer['repairs']:
                    remaining=[l for l in obs if l!=repair['remove']]
                    for replacement in repair['replacements']:
                        self.assertTrue(sat.solve(assumptions=remaining+[replacement]))
                self.assertTrue(answer['repairs'])


if __name__=='__main__':unittest.main()
