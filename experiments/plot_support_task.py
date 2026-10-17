"""Standalone research figure; unknown runs are omitted, never given timings."""
import argparse,json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();out=Path(a.out)
    rows=json.loads((out/'summary.json').read_text())['rows']
    demand=json.loads((out/'demand_summary.json').read_text())
    fig,axes=plt.subplots(1,2,figsize=(12,4.4),layout='constrained')
    colors={'ports-atomic':'#1764ab','ports-binary':'#8393a1','ports-no-cover':'#aa3870',
            'sat-phase':'#d06b22','sat-demand':'#9a4017','bdd-coherence':'#29855b'}
    labels={'ports-atomic':'Ports + atomic RF','ports-binary':'Ports + binary RF','ports-no-cover':'Atomic RF, no source cover',
            'sat-phase':'SAT, full support','sat-demand':'SAT, task-specific queries','bdd-coherence':'Relational BDD'}
    for method in ('ports-atomic','ports-binary','ports-no-cover'):
        rs=sorted((r for r in rows if r['payload']=='epoch' and r['method']==method and r['n']<=32 and 'stats' in r),key=lambda r:r['n'])
        axes[0].plot([r['n'] for r in rs],[r['stats']['raw_states'] for r in rs],'o-',label=labels[method],color=colors[method])
    rs=sorted((r for r in rows if r['payload']=='epoch' and r['method']=='ports-atomic' and r['n']<=32 and 'stats' in r),key=lambda r:r['n'])
    axes[0].plot([r['n'] for r in rs],[r['stats']['states'] for r in rs],'s--',color='#142e4d',label='Atomic RF, after DAG reduction')
    for method in ('ports-atomic','ports-binary','sat-phase','bdd-coherence'):
        rs=sorted((r for r in rows if r['payload']=='epoch' and r['method']==method and r['n']<=32 and 'task_median' in r),key=lambda r:r['n'])
        axes[1].plot([r['n'] for r in rs],[r['task_median'] for r in rs],'o-',color=colors[method],label=labels[method])
    rs=sorted((r for r in demand if r['payload']=='epoch' and 'total_median' in r),key=lambda r:r['n'])
    axes[1].plot([r['n'] for r in rs],[r['total_median'] for r in rs],'s--',color=colors['sat-demand'],label=labels['sat-demand'])
    axes[0].set_title('Construction and stored graph size');axes[0].set_ylabel('States (log scale)')
    axes[1].set_title('Complete provenance-log diagnosis');axes[1].set_ylabel('Seconds, median of 3 runs (log scale)')
    for ax in axes:
        ax.set_xscale('log',base=2);ax.set_yscale('log');ax.set_xticks([2,4,8,16,32],['2','4','8','16','32'])
        ax.set_xlabel('Publication rounds');ax.grid(True,which='major',alpha=.22);ax.legend(fontsize=8,loc='upper left')
        ax.spines[['top','right']].set_visible(False)
    fig.suptitle('Version-tagged payloads; ambiguous publication sources and unresolved CO',fontsize=12)
    for suffix in ('png','svg','pdf'):fig.savefig(out/f'support_task_scaling.{suffix}',dpi=180)


if __name__=='__main__':main()
