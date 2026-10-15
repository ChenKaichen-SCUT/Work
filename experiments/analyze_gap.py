"""Aggregate all successes/failures, keeping separate experiment contracts."""
import argparse,collections,json,statistics
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root',default='results/gap');p.add_argument('--plots',action='store_true');a=p.parse_args()
root=Path(a.root);report={}
metrics=['cold_total_seconds','compile_seconds','graph_seconds','minimize_seconds','cnf_seconds',
         'query_answer_seconds','query_propagation_seconds','total_with_queries_seconds',
         'ready_seconds','query_seconds','total_seconds','peak_rss_kib','states','raw_states','transitions',
         'raw_transitions','max_layer_states','raw_max_layer_states','clauses','sat_calls']
for name in ('serial','forced','ablation','wide'):
    groups=collections.defaultdict(list)
    for path in sorted((root/name).glob('[0-9]*.json')):
        r=json.loads(path.read_text());s=r['spec']
        params=s.get('parameters',{'rounds':s.get('rounds')})
        key=(json.dumps(params,sort_keys=True),s.get('scenario','sat'),s['method'])
        groups[key].append(r)
    rows=[]
    for (params,scenario,method),records in sorted(groups.items()):
        ok=[r for r in records if r['status']=='ok']
        row={'parameters':json.loads(params),'scenario':scenario,'method':method,'runs':len(records),
             'statuses':dict(collections.Counter(r['status'] for r in records))}
        for metric in metrics:
            values=[r[metric] for r in ok if metric in r]
            if values: row[metric]={'median':statistics.median(values),'min':min(values),'max':max(values)}
        if ok and 'prefix_totals' in ok[0]:
            row['prefix_totals']={k:statistics.median(r['prefix_totals'][k] for r in ok) for k in ok[0]['prefix_totals']}
        rows.append(row)
    report[name]=rows
(root/'aggregates.json').write_text(json.dumps(report,indent=2))
for name,rows in report.items():
    print(name)
    for r in rows:
        print(r['parameters'],r['scenario'],r['method'],r['statuses'],
              {k:round(r[k]['median'],6) for k in ('cold_total_seconds','query_answer_seconds','total_seconds','query_seconds') if k in r})
if a.plots:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(12,4.5),layout='constrained')
    methods=('v1','cnf','graph','eager');names=('Original','Optimized CNF','Direct graph','Rank baseline')
    colors=('#90959e','#2474b5','#139574','#c65c42')
    cases=({'rounds':2},{'rounds':8},{'rounds':16},{'rounds':3,'threads':5})
    for j,(method,label,color) in enumerate(zip(methods,names,colors)):
        rs=[next(r for r in report['serial'] if r['parameters']==case and r['scenario']=='sat' and r['method']==method) for case in cases]
        med=[r['cold_total_seconds']['median'] for r in rs]
        axes[0].bar([i+(j-1.5)*.19 for i in range(4)],med,.18,label=label,color=color,
                    yerr=[[m-r['cold_total_seconds']['min'] for m,r in zip(med,rs)],
                          [r['cold_total_seconds']['max']-m for m,r in zip(med,rs)]],capsize=2)
    axes[0].set_xticks(range(4),['2 rounds\n4 threads','8 rounds\n4 threads','16 rounds\n4 threads','3 rounds\n5 threads'])
    axes[0].set_title('First SAT answer, including compilation')
    for j,(method,label,color) in enumerate(zip(('cnf','graph','weak','eager'),('Optimized CNF','Direct graph','Weak + search','Rank + search'),('#2474b5','#139574','#b99c38','#c65c42'))):
        rs=[next(r for r in report['forced'] if r['parameters']=={'rounds':n} and r['method']==method) for n in (2,8)]
        med=[r['total_seconds']['median'] for r in rs]
        axes[1].bar([i+(j-1.5)*.19 for i in range(2)],med,.18,label=label,color=color,
                    yerr=[[m-r['total_seconds']['min'] for m,r in zip(med,rs)],
                          [r['total_seconds']['max']-m for m,r in zip(med,rs)]],capsize=2)
    axes[1].set_xticks(range(2),['2 rounds / 4 threads','8 rounds / 4 threads'])
    axes[1].set_title('All forced literals: setup + 32 queries')
    for ax in axes:
        ax.set_yscale('log');ax.set_ylabel('Seconds (log scale)');ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True);ax.legend(fontsize=8)
    fig.suptitle('Isolated server runs: medians and ranges of 3 repetitions',fontsize=12)
    fig.savefig(root/'comparison.png',dpi=180);fig.savefig(root/'comparison.pdf')
