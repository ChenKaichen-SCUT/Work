import json
from pathlib import Path
import sys
import time
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
start=time.perf_counter()
suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
result=unittest.TextTestRunner(verbosity=2).run(suite)
records=getattr(sys.modules.get('test_correctness'),'Correctness',object).__dict__.get('audit_records',[])
report={'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
        'seconds':time.perf_counter()-start,'checks':records,
        'partial_assignments':sum(r['partial_assignments'] for r in records),
        'scope':'Finite software validation, not a universal proof or proof-assistant certification.'}
(ROOT/'results').mkdir(exist_ok=True)
(ROOT/'results'/'validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
sys.exit(not result.wasSuccessful())
