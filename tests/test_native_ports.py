import os,random,unittest
from itertools import product
from wmcheck.port_monitor import PortMonitor,plan_ports


class NativePortTests(unittest.TestCase):
    def setUp(self):self.previous=os.environ.get('WMCHECK_NATIVE_PORTS')
    def tearDown(self):
        if self.previous is None:os.environ.pop('WMCHECK_NATIVE_PORTS',None)
        else:os.environ['WMCHECK_NATIVE_PORTS']=self.previous
    def test_native_matches_python_every_transition(self):
        from wmcheck import port_monitor
        if port_monitor._port_native is None:self.skipTest('Optional native accelerator not built')
        rng=random.Random(32044)
        for trial in range(120):
            q=1 if trial%3==0 else 4;acyclic=q==1
            mon=PortMonitor(q,(('x',tuple((a,b) for a in range(q) for b in range(q) if rng.random()<.3)),),
                            () if acyclic else ((2,0),(3,0)),acyclic)
            groups=[]
            for _ in range(7):
                a,b=rng.sample('abcdef',2);yes=((),(('x',a,b),),())
                groups.append(((a,b),[yes] if rng.random()<.3 else [((),(),()),yes]))
            os.environ['WMCHECK_NATIVE_PORTS']='0'
            plans=plan_ports((mon,),groups)[0]
            states={((),())}
            for plan in plans:
                native=port_monitor._port_native.prepare(plan);nextstates=set()
                for state in states:
                    for choice in range(len(plan.alternatives)):
                        expected=plan.update(state,choice)
                        self.assertEqual(expected,port_monitor._port_native.update(native,state,choice))
                        if expected is not None:nextstates.add(expected)
                states=nextstates

    def test_native_wide_bitsets(self):
        from wmcheck import port_monitor
        if port_monitor._port_native is None:self.skipTest('Optional native accelerator not built')
        os.environ['WMCHECK_NATIVE_PORTS']='0'
        mon=PortMonitor(1,(('x',((0,0),)),),acyclic=True)
        leaves=[f'v{i:03}' for i in range(90)]
        groups=[(('a',*leaves),[((),tuple(('x','a',v) for v in leaves),())])]
        groups += [(('b','a'),[((),(),()),((),(('x','b','a'),),())])]*2
        groups += [((v,'z'),[((),(('x',v,'z'),),())]) for v in leaves]
        for normalized in (False,):
            plans=plan_ports((mon,),groups)[0]
            self.assertGreater(max(len(p.after_outputs) for p in plans),64)
            states={((),())}
            for plan in plans:
                native=port_monitor._port_native.prepare(plan);self.assertIsNotNone(native)
                nextstates=set()
                for state in states:
                    for choice in range(len(plan.alternatives)):
                        expected=plan.update(state,choice)
                        self.assertEqual(expected,port_monitor._port_native.update(native,state,choice))
                        if expected is not None:nextstates.add(expected)
                states=nextstates


if __name__=='__main__':unittest.main()
