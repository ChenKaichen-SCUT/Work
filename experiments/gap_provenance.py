"""Post-campaign inventory; raw per-run hashes remain authoritative."""
import hashlib,json,platform,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];root=ROOT/'results/gap'
import pysat
inventory={}
for group in ('serial','forced','ablation','wide'):
    paths=sorted((root/group).glob('[0-9]*.json'))
    records=[json.loads(p.read_text()) for p in paths]
    inventory[group]={'records':len(paths),'statuses':{s:sum(r['status']==s for r in records) for s in sorted({r['status'] for r in records})},
                      'raw_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
report={'recorded_after_campaign':True,'platform':platform.platform(),'python':sys.version,
        'python_sat':pysat.__version__,'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for folder in ('wmcheck','experiments','tests') for p in sorted((ROOT/folder).glob('*.py'))},
        'inventory':inventory,
        'source_note':'Serial runs precede CLI switching and addition of the search comparator. Core compiler/summary semantics are unchanged across this campaign; each raw record retains the exact then-present wmcheck file hashes. Profiling is separate from normal timings.',
        'measurement_note':'Serial, forced and ablation runs each used one worker, in sequence. The final wide sensitivity run used two workers once per configuration; profiling followed it.'}
(root/'provenance.json').write_text(json.dumps(report,indent=2))
