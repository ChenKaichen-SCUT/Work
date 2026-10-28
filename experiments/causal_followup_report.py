"""Derived tables and figures; timings are never filled in for censored runs."""
import json
import statistics
import sys
from collections import defaultdict,Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from experiments.causal_bench import save
from experiments.causal_followup_inputs import OUT
from experiments.causal_followup_bench import summarize


def main():
    summarize();raw=json.loads((OUT/'summary.json').read_text());groups=defaultdict(list)
    for r in raw['rows']:groups[r['family'],r['rounds'],r['U'],r['method']].append(r)
    tables=[]
    for (family,n,u,method),rs in sorted(groups.items()):
        ok=[r for r in rs if r['status']=='OK']
        row=dict(family=family,rounds=n,U=u,method=method,status_counts=dict(Counter(r['status'] for r in rs)))
        if ok:
            for field in ('cold_seconds','query_seconds','total_seconds','miss_compute_seconds','hit_seconds','output_seconds'):
                row[field]=statistics.median(r[field] for r in ok)
            row.update(total_min=min(r['total_seconds'] for r in ok),total_max=max(r['total_seconds'] for r in ok),
                cache_hits=ok[0]['cache_hits'],cache_misses=ok[0]['cache_misses'],distinct_answers=ok[0]['distinct_answers'],
                sat_miss_compute_seconds=statistics.median(sum(q['miss_compute_seconds'] for q in r['queries'] if q['sat']) for r in ok),
                unsat_miss_compute_seconds=statistics.median(sum(q['miss_compute_seconds'] for q in r['queries'] if not q['sat']) for r in ok),
                peak_mib=statistics.median(r['peak_wset_bytes']/1024**2 for r in ok))
            if method=='BD':row.update(local_hits=ok[0]['local_hits'],local_misses=ok[0]['local_misses'],
                                      component_sat_calls=ok[0]['component_sat_calls'],components=ok[0]['solver_stats']['original_components'])
            if method=='B2':row.update(K=ok[0]['plan_stats']['actual_K'],Smax=ok[0]['compile_stats']['max_layer_states'])
        else:row.update(completed_queries=max(len(r['queries']) for r in rs),phases=list({r['phase'] for r in rs}))
        tables.append(row)
    curves=[];crossovers=[]
    for (family,n,u,method),rs in sorted(groups.items()):
        ok=[r for r in rs if r['status']=='OK']
        if not ok:continue
        repetitions=[]
        for r in ok:
            totals=[r['cold_seconds']]
            for q in r['queries']:totals.append(totals[-1]+q['seconds'])
            repetitions.append(totals)
        medians=[statistics.median(values) for values in zip(*repetitions)]
        curves.append(dict(family=family,rounds=n,U=u,method=method,cumulative_seconds=medians))
    indexed={(r['family'],r['rounds'],r['U'],r['method']):r['cumulative_seconds'] for r in curves}
    for r in curves:
        if r['method']!='B2':continue
        for baseline in ('B0','B1','BD'):
            other=indexed.get((r['family'],r['rounds'],r['U'],baseline))
            if other is None:continue
            last_loss=max((q for q,(a,b) in enumerate(zip(r['cumulative_seconds'],other)) if a>=b),default=-1)
            crossovers.append(dict(family=r['family'],rounds=r['rounds'],U=r['U'],baseline=baseline,
                first_sustained_faster_prefix=None if last_loss==1000 else last_loss+1,
                scope='median cumulative measured sequence including cold; not a universal threshold'))
    save(OUT/'cumulative.json',dict(curves=curves,crossovers=crossovers))
    save(OUT/'tables.json',dict(rows=tables,status_counts=dict(Counter(r['status'] for r in raw['rows'])),answer_discrepancies=raw['answer_discrepancies'],crossovers=crossovers))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'figure.dpi':150})
    colors={'B0':'#9a6223','B1':'#315ca8','BD':'#8b5194','B2':'#10816b'}
    names={'B0':'Raw SAT','B1':'Preprocessed SAT','BD':'Component SAT','B2':'Compiled'}
    figures=OUT/'figures';figures.mkdir(exist_ok=True)
    fig,axes=plt.subplots(1,3,figsize=(12,4))
    for ax,(family,n) in zip(axes,(('barrier',8),('barrier',16),('buffer',8))):
        for method in colors:
            rr=[r for r in tables if r['family']==family and r['rounds']==n and r['method']==method and 'total_seconds' in r]
            ax.plot([r['U'] for r in rr],[r['total_seconds'] for r in rr],'-o',color=colors[method],label=names[method])
            ax.fill_between([r['U'] for r in rr],[r['total_min'] for r in rr],[r['total_max'] for r in rr],color=colors[method],alpha=.12)
        ax.set(xlabel='Distinct original assumptions U',title=f'{family.title()}, {n} rounds')
        ax.set_xscale('log');ax.set_yscale('log');ax.grid(alpha=.2)
    axes[0].set_ylabel('Cold + 1,000 complete-support requests (s)');axes[0].legend(fontsize=7)
    fig.text(.5,.01,'Same complete-answer cache; median/range of 3 successful runs. Missing points are censored, not assigned a time.',ha='center',fontsize=8)
    fig.tight_layout(rect=(0,.05,1,1));fig.savefig(figures/'new_assumptions.png');fig.savefig(figures/'new_assumptions.pdf');plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(10,3.8))
    for n in (8,16):
        for method,style in (('BD','--'),('B2','-')):
            rr=[r for r in tables if r['family']=='barrier' and r['rounds']==n and r['method']==method and 'total_seconds' in r]
            axes[0].plot([r['U'] for r in rr],[r['miss_compute_seconds'] for r in rr],style+'o',label=f'{names[method]}, n={n}')
        rr=[r for r in tables if r['family']=='barrier' and r['rounds']==n and r['method']=='BD' and 'local_misses' in r]
        axes[1].plot([r['U'] for r in rr],[r['local_misses'] for r in rr],'-o',label=f'n={n}')
    axes[0].set(xlabel='U',ylabel='Cache-miss computation only (s)',title='Global novelty vs query cost')
    axes[1].set(xlabel='U',ylabel='Distinct local component cache misses',title='Local novelty saturates')
    for ax in axes:ax.set_xscale('log');ax.grid(alpha=.2);ax.legend(fontsize=8)
    fig.tight_layout();fig.savefig(figures/'component_reuse.png');fig.savefig(figures/'component_reuse.pdf');plt.close(fig)
    fig,axes=plt.subplots(1,3,figsize=(12,3.8))
    for ax,(family,n) in zip(axes,(('barrier',8),('barrier',16),('buffer',8))):
        for method in ('BD','B2'):
            values=indexed[(family,n,1000,method)]
            ax.plot(range(len(values)),values,color=colors[method],label=names[method])
        ax.set(xlabel='Requests completed (all new assumptions)',title=f'{family.title()}, {n} rounds, U=1000')
        ax.grid(alpha=.2)
    axes[0].set_ylabel('Cumulative cost including cold start (s)');axes[0].legend(fontsize=8)
    fig.tight_layout();fig.savefig(figures/'cumulative_new.png');fig.savefig(figures/'cumulative_new.pdf');plt.close(fig)
    print(json.dumps(tables,indent=2))


if __name__=='__main__':main()
