"""Aggregate raw results, check cross-method agreement and export plots/CSV."""
import argparse
from collections import Counter,defaultdict
import csv
import json
from pathlib import Path
import statistics

def main():
    p=argparse.ArgumentParser();p.add_argument('--results',default='results/main');p.add_argument('--out',default='results/analysis');p.add_argument('--plots',action='store_true')
    a=p.parse_args();root=Path(a.results);out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    records=[json.loads(f.read_text()) for f in sorted(root.glob('[0-9][0-9][0-9][0-9].json'))]
    groups=defaultdict(list);answers=defaultdict(list)
    for r in records:
        s=r['spec'];key=(s['family'],json.dumps(s['parameters'],sort_keys=True),s['method']);groups[key].append(r)
        if r['status']=='ok':
            answers[(s['family'],key[1],r['query_sha256'])].append((s['method'],[q['sat'] for q in r['queries']]))
    mismatches=[]
    for key,values in answers.items():
        if any(v[1]!=values[0][1] for v in values): mismatches.append({'case':key,'methods':values})
    metrics=['recognize_seconds','compile_seconds','sat_setup_seconds','cold_solve_seconds','cold_total_seconds',
             'incremental_solve_seconds','raw_up_seconds','peak_rss_kib','states','transitions','max_layer_states','max_interface',
             'original_variables','cnf_variables','clauses','unsat_queries','up_conflicts']
    rows=[]
    for (family,parameters,method),rs in sorted(groups.items()):
        ok=[r for r in rs if r['status']=='ok'];row={'family':family,'parameters':parameters,'method':method,
            'runs':len(rs),'ok':len(ok),'statuses':json.dumps(dict(Counter(r['status'] for r in rs)))}
        for metric in metrics:
            values=[r[metric] for r in ok if metric in r]
            row[metric]=statistics.median(values) if values else None
        rows.append(row)
    report={'record_count':len(records),'statuses':dict(Counter(r['status'] for r in records)),
            'query_answer_mismatches':mismatches,'aggregates':rows}
    (out/'summary.json').write_text(json.dumps(report,indent=2))
    with (out/'aggregates.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]) if rows else []);w.writeheader();w.writerows(rows)
    if a.plots:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        plt.rcParams.update({'font.size':11,'figure.dpi':140,'savefig.bbox':'tight'})
        for metric,label,filename in [('cold_total_seconds','Cold end-to-end time (s)','cold_time'),
                                      ('peak_rss_kib','Peak worker RSS (MiB)','memory'),
                                      ('clauses','Generated clauses','clauses')]:
            fig,ax=plt.subplots(figsize=(6.3,4.1))
            for method in ('proposed','eager','weak'):
                data=sorted((json.loads(r['parameters'])['rounds'],r[metric]) for r in rows if r['family']=='length' and r['method']==method and r[metric] is not None)
                if data:
                    xs,ys=zip(*data);ys=[v/1024 for v in ys] if metric=='peak_rss_kib' else ys
                    ax.plot(xs,ys,'o-',label=method)
            if metric=='cold_total_seconds':
                censored=[]
                for f in (root.parent/'cold_long').glob('[0-9][0-9][0-9][0-9].json'):
                    r=json.loads(f.read_text())
                    if r.get('status')=='timeout' and r.get('stage')=='cold_solve' and r['spec']['method']=='eager':
                        censored.append((r['spec']['parameters']['rounds'],r['limit_seconds']))
                if censored:
                    ax.scatter(*zip(*censored),marker='^',facecolors='none',edgecolors='tab:orange',label='eager: cold timeout')
                    ax.set_title('Medians; triangles show separate timeout confirmations',fontsize=9)
            ax.set_xscale('log',base=2);ax.set_xticks([1,2,4,8,16,32,64],labels=['1','2','4','8','16','32','64'])
            ax.set_yscale('log');ax.set_xlabel('Protocol rounds');ax.set_ylabel(label);ax.grid(alpha=.25);ax.legend()
            fig.savefig(out/(filename+'.png'));fig.savefig(out/(filename+'.pdf'));plt.close(fig)
        fig,axes=plt.subplots(1,2,figsize=(10,3.8))
        for metric,ax in zip(('max_interface','max_layer_states'),axes):
            data=sorted((json.loads(r['parameters'])['rounds'],r[metric]) for r in rows if r['family']=='length' and r['method']=='proposed' and r[metric] is not None)
            ax.plot(*zip(*data),'o-');ax.set_xscale('log',base=2);ax.set_xlabel('Protocol rounds');ax.set_ylabel(metric.replace('_',' '));ax.grid(alpha=.25)
        fig.tight_layout();fig.savefig(out/'bounded_interface.png');fig.savefig(out/'bounded_interface.pdf');plt.close(fig)
    print(json.dumps({'records':len(records),'statuses':report['statuses'],'mismatches':len(mismatches)},indent=2))

if __name__=='__main__': main()
