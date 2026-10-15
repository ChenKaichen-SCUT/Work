"""Audit a GenMC output-parser correction and fill the missing repetitions.

Original outputs and original JSON classifications are retained. No timed
measurement is changed; only assertion results that were misclassified as
unrecognized are corrected using their exact source location.
"""
import json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.paper_external import genmc_reachable
from experiments.paper_suite import save


def main():
    root=Path('results/paper/external');archive=root.parent/'provenance/result_parser_original';archive.mkdir(parents=True,exist_ok=True)
    names=[];audit=[]
    for path in sorted(root.glob('[0-9]*.json')):
        r=json.loads(path.read_text());s=r['spec']
        if s['method']!='genmc' or r['status']!='ERROR' or r.get('reason')!='unrecognized_GenMC_result':continue
        output=(root/r['process']['stdout']).read_text();result=genmc_reachable(output,s['c'])
        if result is None:raise RuntimeError('Unresolved native tool error: '+str(path))
        (archive/path.name).write_bytes(path.read_bytes())
        r.update(status='ok',reachable=result,result_parser_correction='GenMC Safety violation at the generated assertion location; original ERROR classification archived')
        r.pop('reason',None);save(path,r);names.append(s['name']);audit.append(dict(path=str(path),name=s['name'],reachable=result))
    save(root.parent/'provenance/result_parser_correction.json',audit)
    if names:
        subprocess.run([sys.executable,str(Path(__file__).with_name('paper_external.py')),
            '--out','results/paper/external_repair','--repeats','4','--methods','genmc','--select',*names],check=True)


if __name__=='__main__':main()
