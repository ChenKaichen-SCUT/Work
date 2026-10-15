"""Server validation report and public CLI contract smoke checks."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    start = time.perf_counter()
    suite = unittest.defaultTestLoader.discover(str(ROOT/'tests'))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    smoke = []
    def cli(arguments, expected):
        r = subprocess.run([sys.executable, '-m', 'wmcheck.ra_cli', *arguments], cwd=ROOT,
                           capture_output=True, text=True, check=True, timeout=30)
        data = json.loads(r.stdout)
        if data['status'] != expected:
            raise AssertionError((arguments, data))
        smoke.append(dict(arguments=arguments, status=data['status']))
        return data
    if result.wasSuccessful():
        with tempfile.TemporaryDirectory() as directory:
            dimacs = str(Path(directory)/'ra.cnf'); registry = str(Path(directory)/'variables.json')
            cli(['--size', '3', '--dimacs', dimacs, '--registry', registry], 'SAT')
            from pysat.formula import CNF
            from pysat.solvers import Minisat22
            with Minisat22(bootstrap_with=CNF(from_file=dimacs).clauses) as solver:
                assert solver.solve()
            variables = json.loads(Path(registry).read_text())
            constant = next(int(v) for v, key in variables.items() if key[0] == 'co' and key[1] == 'init')
            cli(['--size', '3', '--assume', str(-constant)], 'UNSAT')
        # Strip temporary paths from the public report.
        smoke[0]['arguments'] = ['--size', '3', '--dimacs', '<temporary-file>', '--registry', '<temporary-file>']
        cli(['--family', 'pipeline', '--size', '1'], 'SAT')
        cli(['--family', 'pipeline', '--size', '1', '--algorithm', 'dynamic'], 'OUTSIDE_CERTIFICATE')
        cli(['--size', '2', '--states', '1'], 'UNKNOWN')
    import pysat
    report = dict(tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                  successful=result.wasSuccessful(), seconds=time.perf_counter()-start,
                  utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                  platform=platform.platform(), python=sys.version, python_sat=pysat.__version__,
                  source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'wmcheck').glob('*.py'))},
                  test_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'tests').glob('test_*.py'))},
                  ra_exhaustive_partial_assignments=2187, ra_random_mixed_inputs=40,
                  independent_oracle='Dense hb/eco relation definition, no compiler/recognizer reuse', cli_smoke=smoke)
    if Path('/proc/cpuinfo').exists():
        report['cpu_model'] = next(x.split(':', 1)[1].strip() for x in Path('/proc/cpuinfo').read_text().splitlines() if x.startswith('model name'))
        report['cpu_affinity'] = sorted(os.sched_getaffinity(0))
        report['memory'] = {line.split(':')[0]: line.split(':')[1].strip()
                            for line in Path('/proc/meminfo').read_text().splitlines()
                            if line.startswith(('MemTotal:', 'MemAvailable:', 'SwapTotal:'))}
    out = ROOT/'results/construction/validation.json'; out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == '__main__':
    main()
