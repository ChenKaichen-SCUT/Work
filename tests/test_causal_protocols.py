import unittest
from copy import deepcopy
from dataclasses import replace
from wmcheck.ra import RAInstance, RARegistry
from wmcheck.ra_oracle import enumerate_assignments
from wmcheck.ra_protocols import (ProtocolInput, barrier_instance, buffer_instance,
    prefix_input, build_protocol, replay_certificate, buffer_chain_bags)


class ProtocolConstruction(unittest.TestCase):
    def test_barrier_certificate_keeps_every_small_model(self):
        inp=barrier_instance(1);result=build_protocol(inp);cert=result['certificate']
        self.assertEqual(result['status'],'CERTIFIED');reg=RARegistry(inp.inst)
        models=list(enumerate_assignments(inp.inst,reg))
        self.assertGreater(len(models),4)
        for model in models:
            for v,(kind,a,b) in reg.by_id.items():
                if kind=='rf' and model[v]:self.assertIn(a,cert['domains'][b])
                if kind=='co' and (a,b) in cert['L']:self.assertTrue(model[v])
                if kind=='co' and (b,a) in cert['L']:self.assertFalse(model[v])
        self.assertTrue(replay_certificate(inp,result))
        corrupted=deepcopy(result);corrupted['certificate']['domains']['w1_1_ar'].clear()
        self.assertFalse(replay_certificate(inp,corrupted))

    def test_barrier_non_sc_and_conditional_identity_survive(self):
        inp=barrier_instance(1);cert=build_protocol(inp)['certificate']
        self.assertEqual(cert['domains']['w1_1_ar'],{'w1_1_ax','w2_1_bx'})
        self.assertNotIn(('w1_1_ax','w2_1_bx'),cert['L'])
        self.assertNotIn(('w2_1_bx','w1_1_ax'),cert['L'])

    def test_barrier_partial_reset_and_impossible_success(self):
        inp=barrier_instance(1,failures=2)
        # Coordinator ends after first reset, workers before successful wake.
        lens={0:7,1:6,2:6}
        truncated=prefix_input(inp,lens)
        self.assertEqual(build_protocol(truncated)['status'],'CERTIFIED')
        missing=prefix_input(inp,{0:0})
        self.assertEqual(build_protocol(missing)['status'],'PROVED_UNSAT')

    def test_outside_is_not_unsat(self):
        inp=barrier_instance(1);bad=deepcopy(inp)
        bad.contract['positions']['w1_1_ax']['role']='arrival'
        self.assertEqual(build_protocol(bad)['status'],'OUTSIDE')
        bad=deepcopy(inp);bad.contract['family']='unknown'
        self.assertEqual(build_protocol(bad)['status'],'OUTSIDE')

    def test_buffer_full_before_capacity_is_unsat(self):
        inp=buffer_instance(0,capacity=2,mode='branch',producer_tail_failures=1)
        result=build_protocol(inp)
        self.assertEqual(result['status'],'PROVED_UNSAT')
        self.assertFalse(result['certificate']['domains']['P0_peer'])

    def test_buffer_value_and_branch_have_distinct_domains(self):
        branch=build_protocol(buffer_instance(3,capacity=3,mode='branch'))
        value=build_protocol(buffer_instance(3,capacity=3,mode='value'))
        self.assertEqual(branch['status'],'CERTIFIED');self.assertEqual(value['status'],'CERTIFIED')
        self.assertEqual(branch['certificate']['domains']['Q0_peer'],{'W1','W2','W3'})
        self.assertEqual(value['certificate']['domains']['Q0_peer'],{'W1'})

    def test_buffer_guards_are_exact_not_ignored(self):
        inp=buffer_instance(1,mode='branch');bad=deepcopy(inp)
        bad.guards=bad.guards[:-1]
        self.assertEqual(build_protocol(bad)['status'],'OUTSIDE')
        allowed=deepcopy(inp);allowed.allowed_values={'Q0_peer':{0}}
        self.assertEqual(build_protocol(allowed)['status'],'PROVED_UNSAT')

    def test_buffer_partial_read_and_tail_chain(self):
        inp=buffer_instance(2,capacity=2,mode='branch',failures=3,tail_failures=4)
        short=prefix_input(inp,{0:1,1:1})
        self.assertEqual(build_protocol(short)['status'],'CERTIFIED')
        result=build_protocol(inp);bags=buffer_chain_bags(inp,result)
        self.assertEqual(set().union(*map(set,bags)),set(inp.inst.event))
        appearances={e:[i for i,b in enumerate(bags) if e in b] for e in inp.inst.event}
        for points in appearances.values():self.assertEqual(points,list(range(min(points),max(points)+1)))
        self.assertLessEqual(max(map(len,bags)),result['metrics']['K_chain_bound'])
        # A failed-chain right SB anchor appears before its first internal read.
        self.assertLess(appearances['Q3_peer'][0],appearances['Q0_peer'][0])


if __name__=='__main__':unittest.main()
