import unittest
from wmcheck.generators import make_trace
from wmcheck.litmus import export_trace,parse_x86
from wmcheck.compiler import compile_instance
from wmcheck.propagation import unit_propagate
from wmcheck.recognize import Unsupported

class LitmusTests(unittest.TestCase):
    def test_generated_roundtrip(self):
        text=export_trace(make_trace(rounds=1,threads=2),name='OwnProtocol')
        inst=parse_x86(text)
        self.assertTrue(unit_propagate(compile_instance(inst).clauses).consistent)
    def test_rejects_unknown_instruction(self):
        with self.assertRaises(Unsupported): parse_x86('X86 T\n{x=0;}\nP0;\nLOCK INC [x];\nexists (0:EAX=0)')

if __name__=='__main__': unittest.main()
