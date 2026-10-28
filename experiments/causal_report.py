"""Tables and exportable figures from retained pilot rows; no invented timings."""
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.causal_bench import save, summarize


def med(rows,key):
    return statistics.median(r[key] for r in rows)


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    folder=ROOT/'results/causal_20261028'
    summary=summarize(folder)
    assert not summary['answer_discrepancies']
    rows=summary['rows'];figures=folder/'figures';figures.mkdir(exist_ok=True)
    groups=defaultdict(list)
    for row in rows:
        family=row['file'].split('_')[0]
        groups[(family,row['method'],row['rounds'])].append(row)
    table=[]
    for (family,method,n),values in sorted(groups.items()):
        if family!='history':continue
        ok=[r for r in values if r['status']=='OK']
        entry=dict(rounds=n,method=method,repetitions=len(values),statuses=dict(Counter(r['status'] for r in values)))
        if ok:
            entry.update(N=ok[0]['events'],X=ok[0]['original_variables'],
                cold_median=med(ok,'cold_seconds'),query100_median=med(ok,'query_seconds'),
                total100_median=statistics.median(r['cold_seconds']+r['query_seconds'] for r in ok),
                total100_min=min(r['cold_seconds']+r['query_seconds'] for r in ok),
                total100_max=max(r['cold_seconds']+r['query_seconds'] for r in ok),
                peak_mib_median=statistics.median(r.get('algorithm_peak_wset_before_accounting_bytes',r['peak_rss_sampled_bytes'])/1024**2 for r in ok))
            if method=='B2':
                entry.update(K=ok[0]['plan_stats']['actual_K'],Smax=ok[0]['compile_stats']['max_layer_states'],
                    states=ok[0]['compile_stats']['states'],transitions=ok[0]['compile_stats']['transitions'],
                    **ok[0]['ambiguity'])
        table.append(entry)
    save(folder/'tables.json',dict(history=table))
    colors={'B0':'#9a6223','B1':'#315ca8','B2':'#10816b'}
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'figure.dpi':140})
    fig,axes=plt.subplots(1,2,figsize=(10,3.8))
    for method in ('B0','B1','B2'):
        rr=[r for r in table if r['method']==method and 'total100_median' in r]
        x=[r['rounds'] for r in rr]
        axes[0].plot(x,[r['total100_median'] for r in rr],'-o',label=method,color=colors[method])
        axes[0].fill_between(x,[r['total100_min'] for r in rr],[r['total100_max'] for r in rr],alpha=.14,color=colors[method])
        axes[1].plot(x,[r['peak_mib_median'] for r in rr],'-o',label=method,color=colors[method])
    for ax in axes:
        ax.set_xscale('log',base=2);ax.set_xlabel('Barrier rounds');ax.grid(alpha=.2);ax.legend()
    axes[0].set_yscale('log');axes[0].set_ylabel('Cold start + 100 ALL queries (s)')
    axes[1].set_ylabel('Peak working set (MiB)')
    fig.suptitle('Same input, same original-literal queries; median and range of 3 runs')
    fig.text(.5,.01,'B0 at 16/32 rounds and B1 at 32 rounds: 30 s process limit. Memory measured before object accounting.',ha='center',fontsize=8)
    fig.tight_layout(rect=(0,.05,1,1));fig.savefig(figures/'history_cost.png');fig.savefig(figures/'history_cost.pdf');plt.close(fig)

    fig,ax=plt.subplots(figsize=(7,4))
    for method in ('B0','B1','B2'):
        values=groups.get(('reuse1000',method,8),[])
        if not values:continue
        common=min(len(r['queries']) for r in values)
        xs=list(range(1,common+1))
        ys=[]
        for q in xs:
            ys.append(statistics.median(r['cold_seconds']+sum(e['seconds'] for e in r['queries'][:q]) for r in values))
        ax.plot(xs,ys,label=method,color=colors[method])
    ax.set_xscale('log');ax.set_yscale('log');ax.grid(alpha=.2);ax.legend()
    ax.set(xlabel='Number of ALL queries / rollback operations',ylabel='Cumulative cold + query time (s)',
           title='Eight rounds; curves stop at the last saved completed query')
    fig.tight_layout();fig.savefig(figures/'query_reuse.png');fig.savefig(figures/'query_reuse.pdf');plt.close(fig)

    cached_path=folder/'cache/summary.json'
    if cached_path.exists():
        cached=json.loads(cached_path.read_text(encoding='utf8'))['rows']
        fig,ax=plt.subplots(figsize=(7,4))
        for i,method in enumerate(('B0','B1','B2')):
            rr=[r for r in cached if r['method']==method]
            value=statistics.median(r['cold_seconds']+r['query_seconds'] for r in rr)
            ax.bar(i+.18,value,width=.34,color=colors[method],alpha=1)
            ax.text(i+.18,value*1.08,f'{value:.3f}',ha='center',fontsize=9)
            plain=[r for r in groups.get(('reuse1000',method,8),[]) if r['status']=='OK']
            if plain:
                value=statistics.median(r['cold_seconds']+r['query_seconds'] for r in plain)
                ax.bar(i-.18,value,width=.34,color=colors[method],alpha=.35)
                ax.text(i-.18,value*1.08,f'{value:.3f}',ha='center',fontsize=9)
            else:ax.text(i-.18,5,'30 s limit',rotation=90,ha='center',fontsize=9)
        ax.set_xticks(range(3),['B0','B1','B2']);ax.set_yscale('log');ax.set_ylim(.05,70);ax.set_xlim(-.65,2.65)
        ax.set(ylabel='Cold start + 1,000 ALL queries (s)',title='21 distinct assumptions; complete-answer caching on all methods')
        fig.text(.5,.01,'Light: no answer cache     Solid: equal memoization',ha='center',fontsize=9)
        ax.grid(axis='y',alpha=.2);fig.tight_layout(rect=(0,.05,1,1))
        fig.savefig(figures/'cache_sensitivity.png');fig.savefig(figures/'cache_sensitivity.pdf');plt.close(fig)

    structural_path=folder/'structure/summary.json'
    if structural_path.exists():
        structures=json.loads(structural_path.read_text(encoding='utf8'))['rows']
        fig,axes=plt.subplots(1,3,figsize=(12,3.7))
        gap=[r for r in structures if r['config']['family']=='barrier' and r['config'].get('long_gap')
             and r['config']['failures']==0 and r['status']=='CERTIFIED']
        axes[0].plot([r['config']['rounds'] for r in gap],[r['special']['actual_K'] for r in gap],'-o',label='K (special)')
        axes[0].plot([r['config']['rounds'] for r in gap],[r['ordinary']['actual_K'] for r in gap],'-s',label='K (thread-major)')
        axes[0].plot([r['config']['rounds'] for r in gap],[r['old_write_gap_G_lower_bound'] for r in gap],'--^',label='G lower bound')
        axes[0].set(xlabel='Rounds, fixed protocol parameters',ylabel='Width / gap',title='Sparse-write history')
        for mode in ('value','branch'):
            bb=[r for r in structures if r['config']['family']=='buffer' and r['config']['mode']==mode and r['status']=='CERTIFIED']
            axes[1].plot([r['config']['failures'] for r in bb],[r['special']['actual_K'] for r in bb],'-o',label=mode+' K')
            axes[1].plot([r['config']['failures'] for r in bb],[r['metrics']['c_actual'] for r in bb],'--',label=mode+' original c')
        axes[1].set(xlabel='Failures per stage and tail',ylabel='Width / frontier',title='Real polling events retained')
        nf=[r for r in structures if r['config']['family']=='no_feedback' and r['status']=='CERTIFIED']
        axes[2].plot([r['config']['n'] for r in nf],[r['special']['actual_K'] for r in nf],'-o')
        axes[2].set(xlabel='Writes / reads',ylabel='Candidate plan K',title='No-feedback structural control')
        for ax in axes:ax.grid(alpha=.2)
        axes[0].legend(fontsize=7);axes[1].legend(fontsize=7)
        fig.tight_layout();fig.savefig(figures/'structure.png');fig.savefig(figures/'structure.pdf');plt.close(fig)
    print(json.dumps(table,indent=2))


if __name__=='__main__':main()
