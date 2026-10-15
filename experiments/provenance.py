"""Non-secret runtime and source provenance; no environment-variable dump."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import pysat

project=Path(__file__).resolve().parents[1]
root=project.parent
report={'recorded_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
        'platform':platform.platform(),'architecture':platform.machine(),'python':sys.version,
        'python_sat':pysat.__version__,'backend':'Minisat22','logical_cpus':os.cpu_count(),
        'core_sha256':{},'baseline_revisions':{},
        'campaign_note':'Core semantics remained unchanged during performance runs. Runner checkpoint logging and extra confirmation modes were added during the campaign. This is a final source snapshot, not a claimed per-run pre-execution manifest.'}
for file in sorted((project/'wmcheck').glob('*.py')):
    report['core_sha256'][str(file.relative_to(project))]=hashlib.sha256(file.read_bytes()).hexdigest()
for name in ('Dat3M','herdtools7'):
    repo=root/'baselines'/name
    if (repo/'.git').exists():
        report['baseline_revisions'][name]=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
for name in ('cpuinfo','meminfo'):
    path=Path('/proc')/name
    if path.exists():
        if name=='cpuinfo': report['cpu_model']=next(x.split(':',1)[1].strip() for x in path.read_text().splitlines() if x.startswith('model name'))
        else: report['memory_total']=path.read_text().splitlines()[0]
(project/'results'/'provenance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='core_sha256'},indent=2))
