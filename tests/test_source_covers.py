"""Independent semantic tests for quantified synchronization and publication."""
import random
import unittest
from itertools import product

from pysat.solvers import Minisat22
from wmcheck.model import Event
from wmcheck.ra import RAInstance, RARegistry, recognize
from wmcheck.ra_oracle import enumerate_assignments, reach, valid
from wmcheck.ra_publication import publication_exchange, publication_layout, staged_witness
from wmcheck.ra_frontier import compile_frontier
from wmcheck.ra_sat import encode_ra
from wmcheck.complete_query import forced_by_search
from wmcheck.owned_dag import OwnedGraphSolver
from wmcheck.propagation import unit_propagate
from wmcheck.oracle import truth_under


class SourceCovers(unittest.TestCase):
    def test_common_predecessor_without_mandatory_source(self):
        inst = RAInstance((Event('i','W','x',-1,0), Event('a','W','x',0,1),
                           Event('b','W','x',0,1), Event('r','R','x',1,1)),
                          (('a','b'),('r',)), ('i',))
        old, new = [recognize(inst, source_covers=b) for b in (False, True)]
        self.assertNotIn(('a','r'), old['H'])
        self.assertIn(('a','r'), new['H'])
        self.assertNotIn(('b','r'), new['H'])
        self.assertEqual(new['domains']['r'], {'a','b'})
        self.assertFalse(new['mandatory'])
        c = compile_frontier(inst, co_mode='direct', summary_mode='ports', source_covers=True, cnf=True)
        models = list(enumerate_assignments(inst, c.registry))
        engine = OwnedGraphSolver(c)
        for values in product((-1,0,1), repeat=c.registry.nvars):
            alpha = tuple(v*s for v,s in zip(c.registry.by_id,values) if s)
            expected = truth_under(models, alpha)
            self.assertEqual(engine.propagate(alpha), expected)
            up = unit_propagate(c.clauses, alpha)
            self.assertEqual(up.consistent, expected[0])
            if up.consistent:
                self.assertEqual({v if b else -v for v,b in up.values.items() if v in c.registry.by_id},expected[1])

    def test_all_certified_hb_and_domains_against_dense_models(self):
        rng = random.Random(20261016)
        for trial in range(70):
            es=[Event('ix','W','x',-1,0),Event('iy','W','y',-1,0)]
            threads=[]
            for t in range(2):
                seq=[]
                for j in range(3):
                    v=f't{t}_{j}';seq.append(v)
                    es.append(Event(v,rng.choice(('R','W')),rng.choice(('x','y')),t,rng.randrange(2)))
                threads.append(tuple(seq))
            inst=RAInstance(tuple(es),tuple(threads),('ix','iy'))
            reg=RARegistry(inst); models=list(enumerate_assignments(inst,reg))
            cert=recognize(inst,source_covers=True)
            if cert['status']=='PROVED_UNSAT':
                self.assertFalse(models);continue
            for model in models:
                rf={(a,b) for v,(kind,a,b) in reg.by_id.items() if kind=='rf' and model[v]}
                hb=reach(inst.sb | rf | {(i,e) for i in inst.initial for e in inst.event if e not in inst.initial},inst.event)
                self.assertLessEqual(cert['H'],hb,(trial,cert))
                self.assertTrue(all(a in cert['domains'][b] for a,b in rf))
                self.assertTrue(all(model[abs(reg.literal(('co',a,b)))] == (reg.literal(('co',a,b))>0)
                                    for a,b in cert['L']))

    def test_publication_source_blocks_and_non_sc_witness(self):
        for n in (1,2,3,5,8):
            inst=publication_exchange(n)
            cert=recognize(inst,source_covers=True)
            for t in range(2):
                for i in range(2,n+1):
                    domain={f't{1-t}_{i-1}_pub0',f't{1-t}_{i-1}_pub1'}
                    self.assertEqual(cert['domains'][f't{t}_{i}_wait'],domain)
                    self.assertTrue(all((w,f't{t}_{i}_wait') not in cert['mandatory'] for w in domain))
            for last in (False,True):
                rf,orders=staged_witness(inst,n,last_publication=last)
                self.assertTrue(valid(inst,rf,orders))
                # This sb/co cycle has no SC linearization, independently of RA.
                co={(a,b) for ws in orders.values() for j,a in enumerate(ws) for b in ws[j+1:]}
                self.assertIn(('t0_1_x','t0_1_x'),reach(inst.sb|co,inst.event))

    def test_source_identity_changes_original_co_support(self):
        inst=publication_exchange(2); reg=RARegistry(inst)
        c=compile_frontier(inst,order=publication_layout(inst,2),co_mode='direct',
                           summary_mode='ports',source_covers=True,early_degrees=True,cnf=True)
        engine=OwnedGraphSolver(c); enc=encode_ra(inst)
        read=reg.literal(('rf','t1_2_y','t1_2_read'))
        early=reg.literal(('rf','t0_1_pub0','t1_2_wait'))
        late=reg.literal(('rf','t0_1_pub1','t1_2_wait'))
        order=reg.literal(('co','t0_1_y','t1_2_y'))
        with Minisat22(bootstrap_with=enc.clauses) as sat:
            for alpha in ((),(read,early),(read,late),(read,early,-order),(read,late,-order)):
                expected=forced_by_search(sat,reg.by_id,alpha)[:2]
                self.assertEqual(engine.propagate(alpha),expected)
                up=unit_propagate(c.clauses,alpha)
                self.assertEqual(up.consistent,expected[0])
                if expected[0]:
                    self.assertEqual({v if b else -v for v,b in up.values.items() if v in reg.by_id},expected[1])
            self.assertNotIn(order,engine.propagate((read,early))[1])
            self.assertIn(order,engine.propagate((read,late))[1])
            self.assertTrue(engine.propagate((read,early,-order))[0])
            self.assertFalse(engine.propagate((read,late,-order))[0])


if __name__=='__main__':
    unittest.main()
