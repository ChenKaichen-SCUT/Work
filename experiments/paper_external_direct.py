"""Evaluate the post-diagnosis general RA construction on the same native cases."""
import json,subprocess,sys
from pathlib import Path


if __name__=='__main__':
    cases=json.loads(Path('results/paper/external/inputs/manifest.json').read_text())
    names=[c['name'] for c in cases if not c['dynamic_certificate']]
    subprocess.run([sys.executable,str(Path(__file__).with_name('paper_external.py')),
        '--out','results/paper/external_direct','--repeats','5',
        '--methods','proposed-frontier-direct','support-frontier-direct','--select',*names],check=True)
