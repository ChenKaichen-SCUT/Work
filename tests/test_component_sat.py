import itertools
import unittest
from wmcheck.ra_protocols import barrier_instance,buffer_instance,build_protocol
from wmcheck.ra_component_sat import ComponentSAT,residual_components
from wmcheck.ra_support_sat import SupportSAT


class Components(unittest.TestCase):
    def test_up_free_variables_auxiliary_and_conflict(self):
        p=residual_components([(1,),(-1,2),(3,4),(-3,-4),(5,-5)],{1,2,3,4,5})
        self.assertEqual(p['units'],{1,2})
        self.assertEqual(sorted(len(c['originals']) for c in p['components']),[1,2])
        self.assertTrue(residual_components([(1,),(-1,)],{1})['conflict'])

    def test_all_partial_assignments_one_round(self):
        inp=barrier_instance(1);pre=build_protocol(inp)
        with SupportSAT(inp) as raw,ComponentSAT(inp,pre['certificate']) as split:
            free=sorted(split.owner)
            self.assertEqual(len(free),6)
            for vals in itertools.product((0,1,-1),repeat=len(free)):
                alpha=tuple(v*s for v,s in zip(free,vals) if s)
                self.assertEqual(raw.all_support(alpha),split.all_support(alpha))
            split.all_support(())
            self.assertGreater(split.total_local_hits,0)

    def test_barrier_multiple_components_and_rollback(self):
        inp=barrier_instance(2);pre=build_protocol(inp)
        with SupportSAT(inp) as raw,ComponentSAT(inp,pre['certificate']) as split:
            self.assertEqual(split.stats['original_components'],2)
            reg=split.registry;r=reg.literal(('rf','w2_1_bx','w1_1_ar'))
            co=reg.literal(('co','w1_1_ax','w2_1_bx'))
            for alpha in ((),(r,),(r,-co),(r,),(),(-co,),(r,)):
                self.assertEqual(raw.all_support(alpha),split.all_support(alpha))

    def test_buffer_not_artificially_split_by_round(self):
        inp=buffer_instance(3,capacity=3,mode='branch');pre=build_protocol(inp)
        with SupportSAT(inp) as raw,ComponentSAT(inp,pre['certificate']) as split:
            self.assertEqual(split.stats['original_components'],1)
            for v in list(split.owner):
                for alpha in ((),(v,),(-v,),(v,-v)):
                    self.assertEqual(raw.all_support(alpha),split.all_support(alpha))


if __name__=='__main__':unittest.main()
