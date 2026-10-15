"""Retain cProfile attribution separately from uninstrumented timings."""
import argparse,cProfile,hashlib,json,pstats,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--out',required=True)
p.add_argument('--threads',type=int,default=5);p.add_argument('--rounds',type=int,default=3)
a=p.parse_args();root=Path(a.source);sys.path.insert(0,str(root))
from wmcheck.generators import make_instance
from wmcheck.compiler import compile_instance
prof=cProfile.Profile();prof.enable()
c=compile_instance(make_instance(rounds=a.rounds,threads=a.threads),max_seconds=180)
prof.disable();stats=pstats.Stats(prof)
rows=[]
for (path,line,fn),(primitive,total,own,cumulative,_) in stats.stats.items():
    rows.append({'file':Path(path).name,'line':line,'function':fn,'calls':total,
                 'own_seconds':own,'cumulative_seconds':cumulative})
rows.sort(key=lambda r:r['cumulative_seconds'],reverse=True)
report={'instrumented':True,'parameters':{'rounds':a.rounds,'threads':a.threads},
        'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'wmcheck').glob('*.py')},
        'compile_stats':c.stats,'profile_total_seconds':stats.total_tt,'functions':rows[:30]}
Path(a.out).parent.mkdir(parents=True,exist_ok=True);Path(a.out).write_text(json.dumps(report,indent=2))
