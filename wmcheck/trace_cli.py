"""Runnable provenance-log diagnosis client (see trace_diagnosis)."""
import argparse,json
from pathlib import Path
from .ra import RAInstance
from .model import Event
from .ra_publication import publication_exchange,publication_layout
from .ra_frontier import compile_frontier
from .dag_reduce import reduce_dag
from .owned_dag import OwnedGraphSolver
from .trace_diagnosis import diagnose,publication_logs


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',help='Fixed-event RA JSON')
    p.add_argument('--publication',type=int,default=2)
    p.add_argument('--payload',choices=('constant','epoch'),default='epoch')
    p.add_argument('--log',help='JSON list of signed original RF/CO literal IDs')
    p.add_argument('--episode',default='s2_t1_late_inverted')
    p.add_argument('--output');p.add_argument('--seconds',type=float,default=90)
    args=p.parse_args()
    if args.input:
        data=json.loads(Path(args.input).read_text())
        inst=RAInstance(tuple(Event(**e) for e in data['events']),tuple(map(tuple,data['threads'])),tuple(data['initial']))
        order=None
    else:
        inst=publication_exchange(args.publication,payload=args.payload);order=publication_layout(inst,args.publication)
    c=compile_frontier(inst,order=order,co_mode='direct',summary_mode='ports',source_covers=True,
        rf_mode='atomic',early_degrees=True,max_states=3000000,max_edges=6000000,max_seconds=args.seconds)
    c=reduce_dag(c);engine=OwnedGraphSolver(c)
    if args.log:observations=json.loads(Path(args.log).read_text())
    elif args.input:p.error('--input requires --log')
    else:observations=next(log['observations'] for log in publication_logs(inst,args.publication) if log['name']==args.episode)
    result=dict(observations=observations,registry=c.registry.by_id,diagnosis=diagnose(c.registry,engine.propagate,observations),stats=c.stats)
    text=json.dumps(result,indent=2)
    if args.output:Path(args.output).write_text(text+'\n',encoding='utf8')
    else:print(text)


if __name__=='__main__':main()
