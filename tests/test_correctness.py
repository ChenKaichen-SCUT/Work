import random
import unittest
from itertools import product
from pysat.solvers import Minisat22
from wmcheck.generators import make_instance,make_trace
from wmcheck.recognize import recognize,Unsupported
from wmcheck.model import Event,Axiom,Instance
from wmcheck.compiler import compile_instance,ResourceLimit
from wmcheck.eager import encode
from wmcheck.oracle import enumerate_models,truth_under
from wmcheck.propagation import unit_propagate,supports,Session


class Correctness(unittest.TestCase):
    audit_records=[]
    def compare(self,inst,exhaustive=False,samples=120,dense=False):
        c=compile_instance(inst);e=encode(inst)
        models=list(enumerate_models(inst,c.registry,dense_tso=dense))
        mandatory=[];free=[]
        for v,(kind,a,b) in c.registry.by_id.items():
            if kind=='rf' and len(inst.candidates[b])==1: mandatory.append(v)
            else: free.append(v)
        assignments=[]
        if exhaustive:
            for values in product((-1,0,1),repeat=len(free)):
                assignments.append([v*s for v,s in zip(free,values) if s])
        else:
            rng=random.Random(20261015)
            assignments=[[],*[[v] for v in c.registry.by_id],*[[-v] for v in c.registry.by_id]]
            assignments.extend([v*rng.choice((-1,1)) for v in free if rng.random()<.35] for _ in range(samples))
        assignments.extend([[-v] for v in mandatory])
        with Minisat22(bootstrap_with=e.clauses) as solver:
            for alpha in assignments:
                consistent,forced=truth_under(models,alpha)
                actual=unit_propagate(c.clauses,alpha)
                self.assertEqual(actual.consistent,consistent,(inst.metadata,alpha))
                self.assertEqual(solver.solve(assumptions=alpha),consistent)
                self.assertEqual(supports(c,alpha),(consistent,forced))
                if consistent:
                    got={v if b else -v for v,b in actual.values.items() if v in c.registry.by_id}
                    self.assertEqual(got,forced)
                    # A generated reason is validated against independent full models.
                    for lit in sorted(forced-set(alpha),key=abs)[:2]:
                        reason=actual.explanation(lit)
                        self.assertTrue(set(reason)<=set(alpha))
                        self.assertIn(lit,truth_under(models,reason)[1])
                else:
                    reason=actual.explanation()
                    self.assertTrue(set(reason)<=set(alpha))
                    self.assertFalse(truth_under(models,reason)[0])
        self.audit_records.append({'test':self.id(),'events':len(inst.events),'models':len(models),
            'partial_assignments':len(assignments),'dense_tso_oracle':dense,'exhaustive_nonconstant_partials':exhaustive})
        return len(models),len(assignments)

    def test_tso_one_round_exhaustive_partial_assignments(self):
        self.compare(make_instance(rounds=1,first_read_value=1),exhaustive=True,dense=True)

    def test_tso_two_rounds(self):
        models,_=self.compare(make_instance(rounds=2),samples=200,dense=True)
        self.assertEqual(models,144)

    def test_random_generic_graphs_and_rf_filters(self):
        rng=random.Random(17)
        ev=(Event('s','W','x',0),Event('v','W','x',1),Event('b','W','y',2),Event('r','R','x',0))
        for mask in ('all','ext','none'):
            for _ in range(8):
                edges=tuple((a.id,b.id) for a in ev for b in ev if a!=b and rng.random()<.18)
                i=Instance(ev,(('s','v','b'),('r',)),{'r':('s','v')},(Axiom(mask,edges,mask),))
                self.compare(i,exhaustive=True)

    def test_source_port_and_internal_cycle_retirement(self):
        ev=(Event('s','W','x',0),Event('v','W','x',1),Event('b','W','y',2),Event('r','R','x',0))
        i=Instance(ev,(('s','v','b'),('r',)),{'r':('s',)},
                   (Axiom('cycle',(('v','b'),('b','r'))),),forced_co=(('s','v'),))
        self.compare(i,exhaustive=True)
        self.assertFalse(unit_propagate(compile_instance(i).clauses).consistent)

    def test_multiple_cuts_and_relation_modes(self):
        ev=(Event('s','W','x',0),Event('v','W','x',1),Event('b','W','y',2),
            Event('r','R','x',0),Event('w','W','x',1),Event('r2','R','x',2))
        for mode in ('none','all','ext'):
            for co,fr in product((False,True),repeat=2):
                if mode=='none' and not co and not fr: continue
                inst=Instance(ev,(('s','v','b'),('r',),('w',),('r2',)),
                    {'r':('s','v'),'r2':('s','v','w')},
                    (Axiom('generic',(('v','b'),('b','r'),('r','r2')),mode,co,fr),))
                self.compare(inst,exhaustive=True)

    def test_pop_restores_results(self):
        c=compile_instance(make_instance(rounds=2));s=Session(c)
        before=s.propagate();v=next(iter(c.registry.by_id))
        s.push(-v);s.push(v)
        self.assertFalse(s.propagate().consistent)
        s.pop();after=s.pop()
        self.assertEqual(before.consistent,after.consistent)
        self.assertEqual(before.values,after.values)
        with self.assertRaises(ValueError): s.push(c.nvars+1)

    def test_ablation_equivalence(self):
        i=make_instance(rounds=2);a=compile_instance(i);b=compile_instance(i,merge=False)
        weak=compile_instance(i,strong=False);models=list(enumerate_models(i,a.registry,dense_tso=True))
        rng=random.Random(91)
        with Minisat22(bootstrap_with=weak.clauses) as solver:
            for _ in range(50):
                alpha=[v*rng.choice((-1,1)) for v in a.registry.by_id if rng.random()<.1]
                self.assertEqual(unit_propagate(a.clauses,alpha).consistent,unit_propagate(b.clauses,alpha).consistent)
                self.assertEqual(solver.solve(assumptions=alpha),truth_under(models,alpha)[0])
        self.assertGreater(b.stats['states'],a.stats['states'])

    def test_recognizer_rejects_mutations(self):
        t=make_trace();t['sequences'][0].pop()
        with self.assertRaises(Unsupported): recognize(t)
        t=make_trace();t['data_locations'].append('unrefreshed')
        with self.assertRaises(Unsupported): recognize(t)
        t=make_trace();t['flags'][1]=t['flags'][0]
        with self.assertRaises(Unsupported): recognize(t)

    def test_limits_are_not_unsat(self):
        with self.assertRaises(ResourceLimit): compile_instance(make_instance(rounds=2),max_states=2)

    def test_empty_candidate_is_conflict(self):
        i=Instance((Event('r','R','x',0),),(('r',),),{'r':()},(Axiom('a'),))
        self.assertFalse(unit_propagate(compile_instance(i).clauses).consistent)
        self.assertFalse(Minisat22(bootstrap_with=encode(i).clauses).solve())


if __name__=='__main__': unittest.main()
