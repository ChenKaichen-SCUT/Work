import itertools
import unittest
from wmcheck.ra_protocols import barrier_instance,buffer_instance,build_protocol
from wmcheck.ra_support_sat import SupportSAT
from wmcheck.ra_component_sat import ComponentSAT
from wmcheck.ra_task_diagnosis import QueryService,diagnose,session,validate_log


class OnDemand(unittest.TestCase):
    def test_target_and_consistency_agree_with_raw_support(self):
        for inp in (barrier_instance(1),buffer_instance(3,capacity=3,mode='branch')):
            pre=build_protocol(inp)
            with SupportSAT(inp) as raw,SupportSAT(inp,pre['certificate']) as b1,ComponentSAT(inp,pre['certificate']) as bd:
                candidates=list(bd.owner)[:5]
                for values in itertools.product((0,1,-1),repeat=min(3,len(candidates))):
                    alpha=[v*s for v,s in zip(candidates,values) if s]
                    ok,all_values=raw.all_support(alpha)
                    for target in ([],candidates[:1],candidates[1:4]):
                        expected=ok,{l for l in all_values if abs(l) in target}
                        self.assertEqual(b1.target_support(target,alpha),expected)
                        self.assertEqual(bd.target_support(target,alpha),expected)
                    self.assertEqual(bd.solve(alpha),ok)

    def test_client_reports_same_repairs_without_forcing_full_support(self):
        inp=barrier_instance(2);pre=build_protocol(inp)
        with SupportSAT(inp) as raw,ComponentSAT(inp,pre['certificate']) as bd:
            reg=raw.registry;r=reg.literal(('rf','w2_1_bx','w1_1_ar'));c=reg.literal(('co','w1_1_ax','w2_1_bx'))
            episodes=[dict(name='conflict',observations=[r,-c]),dict(name='consistent',observations=[r,c])]
            for profile in ('sparse','dense'):
                a,b=QueryService('B0',raw,reg),QueryService('BD',bd,reg)
                left,right=session(a,episodes,profile),session(b,episodes,profile)
                self.assertEqual(left,right)
                self.assertTrue(any(q['task']=='field' for q in a.calls))
                self.assertTrue(any(q['task']=='sat' for q in a.calls))
                core=left[0]['diagnosis']['conflict'];self.assertFalse(raw.solve(core))
                self.assertTrue(all(raw.solve([x for x in core if x!=v]) for v in core))
                for repair in left[0]['diagnosis']['repairs']:
                    for replacement in repair['replacements']:
                        self.assertTrue(raw.solve([x for x in (r,-c) if x!=repair['remove']]+[replacement]))
                with self.assertRaises(ValueError):validate_log(reg,[r,r])


if __name__=='__main__':unittest.main()
