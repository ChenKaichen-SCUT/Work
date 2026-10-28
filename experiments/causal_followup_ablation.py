"""Complete prior mechanism accounting plus matched long-gap input-order runs."""
import json
import hashlib
import statistics
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiments.causal_bench import save,run_one
from experiments.causal_followup_inputs import OUT


def metrics(rows):
    good=[r for r in rows if r['status']=='OK']
    if not good:return dict(statuses=[r['status'] for r in rows])
    first=good[0]
    return dict(repeats=len(good),K=first['plan_stats']['actual_K'],groups=first['plan_stats']['groups'],
        Smax=first['compile_stats']['max_layer_states'],states=first['compile_stats']['states'],
        transitions=first['compile_stats']['transitions'],
        T_plan=statistics.median(r['plan_seconds'] for r in good),
        T_compile=statistics.median(r['compile_seconds'] for r in good),
        T_query100=statistics.median(r['query_seconds'] for r in good),
        T_cold100=statistics.median(r['cold_seconds']+r['query_seconds'] for r in good),
        answer_hashes=[q['answer_sha256'] for q in first['queries']])


def main():
    sources=sorted((ROOT/'wmcheck').glob('*.py'))+[Path(__file__),ROOT/'experiments/causal_bench.py']
    def hashes():return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    frozen=hashes()
    old=ROOT/'results/causal_20261028/runs';tables=[]
    for n in (2,8,16):
        for family,label in [('history','sparse_special'),('ordinary','sparse_input_order'),('dense','dense_special')]:
            rows=[json.loads((old/f'{family}_B2_n{n}_r{rep}.json').read_text()) for rep in range(3)]
            tables.append(dict(rounds=n,version=label,provenance='frozen previous batch',**metrics(rows)))
    for n in (8,16,32):
        matched=[]
        for layout in ('special','ordinary'):
            rows=[]
            for rep in range(3):
                path=OUT/'ablation_runs'/f'gap_{layout}_n{n}_r{rep}.json'
                row=run_one(dict(method='B2',rounds=n,long_gap=True,layout=layout,repeat=rep),path,
                            seconds=40,memory_mib=1024,queries=100)
                rows.append(row)
                if row['status']!='OK':break
            entry=dict(rounds=n,version='gap_'+layout,provenance='new matched batch',**metrics(rows));tables.append(entry);matched.append(entry)
        if all('answer_hashes' in r for r in matched):assert matched[0]['answer_hashes']==matched[1]['answer_hashes']
        save(OUT/'ablation.json',tables)
    save(OUT/'ablation.json',tables)
    save(OUT/'ablation_source_verification.json',dict(unchanged=hashes()==frozen,source_sha256=frozen))
    assert hashes()==frozen


if __name__=='__main__':main()
