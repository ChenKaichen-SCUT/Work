import random,unittest
from itertools import product
from wmcheck.model import Event
from wmcheck.ra import RAInstance,RARegistry,recognize
from wmcheck.ra_oracle import enumerate_assignments,valid
from wmcheck.ra_incidence_sat import IncidenceSAT
from wmcheck.ra_ring import publication_ring,ring_witness


class FMEvidence(unittest.TestCase):
    def test_independent_incidence_encoding_all_small_partial_assignments(self):
        rng=random.Random(20261018)
        for trial in range(20):
            events=[Event('i','W','x',-1,0)];threads=[]
            for t in range(2):
                seq=[]
                for j in range(2):
                    v=f't{t}_{j}';seq.append(v);events.append(Event(v,rng.choice(('R','W')),'x',t,rng.randrange(2)))
                threads.append(tuple(seq))
            inst=RAInstance(tuple(events),tuple(threads),('i',));reg=RARegistry(inst)
            models=list(enumerate_assignments(inst,reg))
            with IncidenceSAT(inst) as sat:
                for values in product((-1,0,1),repeat=reg.nvars):
                    alpha=[v*s for v,s in zip(reg.by_id,values) if s]
                    expected=any(all(m[abs(x)]==(x>0) for x in alpha) for m in models)
                    self.assertEqual(sat.solve(alpha),expected,(trial,alpha))

    def test_ring_witness_and_locked_source_blocks(self):
        for p,n,irregular in ((3,2,False),(3,4,True),(4,3,False)):
            inst=publication_ring(n,p,irregular=irregular);cert=recognize(inst,source_covers=True)
            for late in (False,True):self.assertTrue(valid(inst,*ring_witness(inst,n,p,late)))
            for t in range(p):
                prev=(t-1)%p
                for i in range(2,n+1):
                    expected={v for v in inst.threads[prev] if v.startswith(f't{prev}_{i-1}_pub')}
                    self.assertEqual(cert['domains'][f't{t}_{i}_wait'],expected)


if __name__=='__main__':unittest.main()
