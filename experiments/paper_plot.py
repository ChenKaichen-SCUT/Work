"""Scientific summary plots from audited aggregates, with censored points omitted."""
import argparse,json
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',default='results/paper');a=p.parse_args();root=Path(a.root)
    obj=json.loads((root/'analysis.json').read_text())
    if any(obj[k] for k in ('exact_query_mismatches','external_verdict_mismatches','profile_mismatches','boolean_interface_mismatches')):
        raise RuntimeError('Comparison audit failed')
    if obj['statuses'].get('running') or obj['statuses'].get('ERROR'):
        raise RuntimeError('Resolve incomplete runs or execution errors before publication plots')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})
    rows={(r['campaign'],r['id'],r['method']):r for r in obj['aggregates']}
    fig,axes=plt.subplots(1,2,figsize=(10.8,4.2),layout='constrained')
    styles=[('dynamic','D: explicit labels','#2563eb','o'),('grid','G: interval labels','#e07b21','s'),('sat-best','SAT: best of 2 fixed heuristics','#242424','^'),('bdd-best','CUDD: best measured construction','#777777','d')]
    for ax,count in zip(axes,(64,512)):
        for method,label,color,marker in styles:
            xs=[];ys=[];lo=[];hi=[]
            for j,n in enumerate((2,4,8,16,32,64,128)):
                if method=='sat-best':
                    ds=[rows.get(('sat_strong',f'c{j:03d}',m),{}).get('checkpoints',{}).get(str(count),{}).get('total') for m in ('sat-up-assisted','sat-phase-assisted')]
                    d=min((v for v in ds if v and v['n']>=5),key=lambda v:v['median'],default=None)
                elif method=='bdd-best':
                    ds=[rows.get((camp,f'c{j:03d}',m),{}).get('checkpoints',{}).get(str(count),{}).get('total') for camp,m in (('primary','bdd-sift'),('bdd_coherence','bdd-coherence-first'))]
                    d=min((v for v in ds if v and v['n']>=5),key=lambda v:v['median'],default=None)
                else:
                    r=rows.get(('primary',f'c{j:03d}',method),{});d=r.get('checkpoints',{}).get(str(count),{}).get('total')
                if not d or d['n']<5:continue
                xs.append(n);ys.append(d['median']);lo.append(d['median']-d['q1']);hi.append(d['q3']-d['median'])
            ax.errorbar(xs,ys,yerr=[lo,hi],label=label,color=color,marker=marker,capsize=3,linewidth=1.4)
        ax.set_xscale('log',base=2);ax.set_yscale('log');ax.set_xticks([2,4,8,16,32,64,128],labels=[2,4,8,16,32,64,128])
        ax.set_xlabel('Writes per producer (2 producers, 2 reads)');ax.set_ylabel('Construction + complete queries (s)')
        ax.set_title(f'{count} queries; median and interquartile range');ax.grid(alpha=.18)
    axes[0].legend(fontsize=8);fig.suptitle('Certified single-address D/G; only checkpoints with five repetitions\nMissing points: resource limit or fewer than five repetitions',fontsize=11)
    out=root/'figures';out.mkdir(exist_ok=True)
    fig.savefig(out/'producer_amortization.png',dpi=180);fig.savefig(out/'producer_amortization.pdf',metadata={'CreationDate':None,'ModDate':None});plt.close(fig)
    # General frontiers are displayed separately. No censored runtime is turned
    # into a plotted numerical measurement.
    pairs=[('c011','pipeline 1'),('c012','pipeline 2'),('c013','pipeline 3'),('a002','ambiguous IRIW 2'),('a004','ambiguous IRIW 4'),('a008','ambiguous IRIW 8'),('a016','ambiguous IRIW 16')]
    fig,ax=plt.subplots(figsize=(11.5,4.5),layout='constrained')
    for m,label,color,dx in [('frontier','F: successor witnesses','#2563eb',-.36),('frontier-direct-co','F: direct CO generators','#8b3fbf',-.12),('bdd-best','CUDD: best relational construction','#e07b21',.12),('sat-best','SAT: best of 2 fixed heuristics','#242424',.36)]:
        first=True
        for i,(cid,_) in enumerate(pairs):
            camp='pruning' if m=='frontier-direct-co' else 'stress' if cid.startswith('a') else 'bdd_relational' if m=='bdd-relational' else 'primary'
            r=rows.get((camp,cid,m));d=r.get('checkpoints',{}).get('64',{}).get('total') if r else None
            if m=='sat-best':
                rs=[rows.get(('sat_strong',cid,v)) for v in ('sat-up-assisted','sat-phase-assisted')]
                r=next((v for v in rs if v),None)
                ds=[v.get('checkpoints',{}).get('64',{}).get('total') for v in rs if v]
                d=min((v for v in ds if v and v['n']>=5),key=lambda v:v['median'],default=None)
            if m=='bdd-best':
                original='stress' if cid.startswith('a') else 'bdd_relational'
                rs=[rows.get((camp,cid,v)) for camp,v in ((original,'bdd-relational'),('bdd_coherence','bdd-coherence-first'))]
                r=next((v for v in rs if v),None)
                ds=[v.get('checkpoints',{}).get('64',{}).get('total') for v in rs if v]
                d=min((v for v in ds if v and v['n']>=5),key=lambda v:v['median'],default=None)
            if d:
                ax.scatter(i+dx,d['median'],label=label if first else None,color=color,marker='o');first=False
            elif r:
                ax.text(i+dx,1.01,'U',transform=ax.get_xaxis_transform(),ha='center',va='bottom',color=color,fontsize=9)
    ax.set_yscale('log');ax.set_xticks(range(len(pairs)),[name for _,name in pairs],rotation=25,ha='right')
    ax.set_ylabel('Construction + 64 complete queries (s)');ax.grid(axis='y',alpha=.18)
    ax.set_title('General fixed-event RA: U = resource limit (not a measured runtime)',pad=25);ax.legend(fontsize=8)
    fig.savefig(out/'general_frontier.png',dpi=180);fig.savefig(out/'general_frontier.pdf',metadata={'CreationDate':None,'ModDate':None});plt.close(fig)


if __name__=='__main__':main()
