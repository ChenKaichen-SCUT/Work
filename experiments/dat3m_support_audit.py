"""Run unmodified Dat3M native may/must analysis with explicit input facts."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from wmcheck.ra import recognize,closure
from wmcheck.ra_publication import publication_exchange
from wmcheck.ra_program import export_litmus


def facts(inst,cert=None):
    domains=cert['domains'] if cert else inst.candidates
    result={('rf','may',w,r) for r,ws in domains.items() for w in ws}
    if cert:
        result.update(('hb','must',a,b) for a,b in cert['H'])
        result.update(('co','must',a,b) for a,b in cert['L'])
        result.update(('rf','must',a,b) for a,b in cert['mandatory'])
    return result


def run(args):
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    dat3m=Path(args.dat3m);cp=f'{out}:{dat3m}/dartagnan/target/classes:{dat3m}/dartagnan/target/libs/*'
    subprocess.run(['javac','-cp',cp,'-d',str(out),str(ROOT/'experiments/Dat3mSupportAudit.java')],check=True)
    env=dict(os.environ,DAT3M_HOME=str(dat3m));summary=[]
    for n in (1,2,3,4,8,16):
        inst=publication_exchange(n);folder=out/f'n{n}';folder.mkdir()
        litmus=folder/'program.litmus';litmus.write_text(export_litmus(inst,name=f'publication_{n}'))
        locs={l:f'&x{j}' for j,l in enumerate(sorted({e.loc for e in inst.events}))}
        mapping=[]
        for e in inst.events:
            native='init:'+locs[e.loc][1:] if e.id in inst.initial else f'{e.thread}:{inst.threads[e.thread].index(e.id)}'
            mapping.append('\t'.join((e.id,native,e.kind,locs[e.loc])))
        mapfile=folder/'mapping.tsv';mapfile.write_text('\n'.join(mapping)+'\n')
        old=recognize(inst);new=recognize(inst,source_covers=True)
        for mode in ('values','k0','k0-plus-cover','k0-plus-cover-closure'):
            current=facts(inst,None if mode=='values' else old);rounds=[]
            for iteration in range(30):
                prefix=folder/f'{mode}_{iteration}'
                inputfile=prefix.with_suffix('.input.tsv');outputfile=prefix.with_suffix('.output.tsv')
                inputfile.write_text(''.join('\t'.join(r)+'\n' for r in sorted(current)))
                start=time.perf_counter()
                proc=subprocess.run(['java','-Xmx2g','-cp',cp,'Dat3mSupportAudit',str(litmus),
                    str(ROOT/'experiments/fixed_ra.cat'),str(mapfile),str(inputfile),str(outputfile)],
                    env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=120)
                prefix.with_suffix('.log').write_text(proc.stdout)
                if proc.returncode:raise RuntimeError(proc.stdout)
                observed={tuple(r.split('\t')) for r in outputfile.read_text().splitlines()}
                h={(a,b) for rel,bound,a,b in observed if rel=='hb' and bound=='must'}
                d={r:{a for rel,bound,a,b in observed if rel=='rf' and bound=='may' and b==r} for r in inst.reads}
                added={(u,r) for r,ws in d.items() if ws for u in inst.event
                       if all(u==w or (u,w) in h for w in ws)}-h
                rounds.append(dict(iteration=iteration,seconds=time.perf_counter()-start,new_cover_edges=len(added)))
                if mode=='k0-plus-cover-closure':
                    expanded=closure(h|added)
                    added=expanded-h
                    co={(a,b) for a,b in expanded if a in inst.write_set and b in inst.write_set
                        and inst.event[a].loc==inst.event[b].loc}
                    co|={(a,b) for rel,bound,a,b in observed if rel=='co' and bound=='must'}
                    co=closure(co)
                    observed.update(('co','must',a,b) for a,b in co)
                    observed={row for row in observed if not(row[:2]==('rf','may') and
                        ((row[3],row[2]) in expanded or any((row[2],w) in co and (w,row[3]) in expanded for w in inst.writes)))}
                if not mode.startswith('k0-plus-cover') or not added:break
                # Feed only sound bounds back through the original external-filter API.
                current={r for r in observed if r[0] in ('rf','co','hb')}
                current.update(('hb','must',a,b) for a,b in added)
                # Other non-memory control events must remain in the HB may universe.
                current={r for r in current if not(r[0]=='hb' and r[1]=='may')}
            else:raise RuntimeError('No fixpoint within 30 rounds')
            raw_rf={(a,b) for b,ws in inst.candidates.items() for a in ws}
            probes={(f't{t}_{i}_pub0',f't{1-t}_{i+1}_wait') for t in range(2) for i in range(1,n)}
            co_must={(a,b) for rel,bound,a,b in observed if rel=='co' and bound=='must'}
            rf_may={(a,b) for rel,bound,a,b in observed if rel=='rf' and bound=='may'}
            row=dict(n=n,mode=mode,iterations=rounds,rf_may=len(rf_may),rf_must=sum(r[:2]==('rf','must') for r in observed),
                hb_must=len(h),co_must=len(co_must),required_common_hb=len(probes),found_common_hb=len(probes & h),
                rf_outside_observed_values=len(rf_may-raw_rf),r5_rf=sum(map(len,new['domains'].values())),
                r5_hb=len(new['H']),r5_co=len(new['L']),r5_hb_missing_from_native=len(new['H']-h),
                r5_rf_removed_but_native_kept=len(rf_may-{(a,b) for b,ws in new['domains'].items() for a in ws}))
            summary.append(row);print(json.dumps(row),flush=True)
            (out/'summary.json').write_text(json.dumps(summary,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--dat3m',required=True);p.add_argument('--out',required=True)
    run(p.parse_args())
