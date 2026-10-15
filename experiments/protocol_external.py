"""Third-party validation of our generated, fully observed protocol traces."""
import json
import os
from pathlib import Path
import re
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from wmcheck.generators import make_trace
from wmcheck.recognize import recognize
from wmcheck.litmus import export_trace
from wmcheck.compiler import compile_instance
from wmcheck.propagation import unit_propagate
from public_suite import invoke

root=Path(os.environ.get('WM_RESEARCH_ROOT','/root/wm-research'))
project=Path(__file__).resolve().parents[1];out=project/'results'/'protocol_external';out.mkdir(parents=True,exist_ok=True)
inputs=project/'examples';inputs.mkdir(exist_ok=True)
dat=root/'baselines'/'Dat3M';herd=root/'baselines'/'herdtools7'
env=dict(os.environ,DAT3M_HOME=str(dat));env['LD_LIBRARY_PATH']=str(dat/'dartagnan'/'target'/'libs')
records=[]
for p,n,value in ((2,1,0),(2,2,0),(2,2,1),(4,1,0),(4,1,1),(2,1,2)):
    name=f'protocol_p{p}_n{n}_v{value}'
    trace=make_trace(rounds=n,threads=p,first_read_value=value)
    path=inputs/(name+'.litmus');path.write_text(export_trace(trace,name))
    compiled=compile_instance(recognize(trace));sat=unit_propagate(compiled.clauses).consistent
    row={'name':name,'parameters':{'threads':p,'rounds':n,'first_read_value':value},'proposed_sat':sat,'stats':compiled.stats}
    h=invoke([str(herd/'_build'/'default'/'herd'/'herd.exe'),'-I',str(herd/'herd'/'libdir'),'-model','x86tso.cat',
              '-speedcheck','true',str(path)],env,40,cpu=5)
    m=re.search(r'^Observation .* (Never|Sometimes|Always)\s',h.get('stdout',''),re.M)
    if m and h.get('exit_code')==0: h['sat']=m[1]!='Never'
    row['herd7']=h
    for method in ('lazy','eager'):
        d=invoke(['java','-Xmx2g','-Djava.library.path='+str(dat/'dartagnan'/'target'/'libs'),'-jar',
                  str(dat/'dartagnan'/'target'/'dartagnan.jar'),str(dat/'cat'/'tso.cat'),str(path),
                  '--method='+method,'--property=program_spec'],env,40,cpu=5)
        m=re.search(r'^Result: (PASS|FAIL)\s*$',d.get('stdout',''),re.M)
        if m and d.get('exit_code')==0: d['sat']=m[1]=='PASS'
        row['dartagnan_'+method]=d
    answers=[sat]+[v['sat'] for v in row.values() if isinstance(v,dict) and 'sat' in v]
    row['mismatch']=len(set(answers))>1
    records.append(row);print(name,'mismatch',row['mismatch'],flush=True)
    (out/'results.json').write_text(json.dumps(records,indent=2))
