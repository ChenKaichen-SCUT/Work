"""Reanalyse existing exact-query timings; never extrapolate a crossover.

Use a restored paper bundle (experiments/paper_unpack.py). Every prefix median
includes each run's own construction and setup. The SAT/BDD comparator is the
uncharged lower envelope of the named measured strategies, not an online policy.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics


def curve(root, row):
    records = [json.loads((root / p).read_text()) for p in row['records']]
    good = [r for r in records if r['status'] == 'ok' and len(r.get('query_times', ())) >= 512]
    if len(good) != 5:
        return None
    sequences = []
    for r in good:
        total = r['compile_seconds'] + r.get('setup_seconds', 0)
        seq = []
        for elapsed in r['query_times'][:512]:
            total += elapsed; seq.append(total)
        sequences.append(seq)
    return dict(values=[statistics.median(xs) for xs in zip(*sequences)],
                records=[r for r in row['records']],
                hashes=sorted({r['query_sha256'] for r in good}),
                answers=good[0]['answer_hashes'][:512])


def analyze(root):
    root = Path(root)
    raw = (root/'analysis.json').read_bytes()
    rows = json.loads(raw)['aggregates']
    sources = [r for r in rows if (r['campaign'], r['method']) in
               (('primary', 'dynamic'), ('pruning', 'frontier-direct-co'))]
    result = []
    for row in sources:
        own = curve(root, row)
        if own is None:
            continue
        for baseline, allowed in (
            ('strong-SAT', {('sat_strong', 'sat-up-assisted'), ('sat_strong', 'sat-phase-assisted')}),
            ('relational-BDD', {('bdd_relational', 'bdd-relational'), ('bdd_coherence', 'bdd-coherence-first')}),
        ):
            others = [(r, curve(root, r)) for r in rows if r['id'] == row['id']
                      and (r['campaign'], r['method']) in allowed]
            others = [(r, c) for r, c in others if c is not None]
            if not others:
                continue
            for r, c in others:
                if c['hashes'] != own['hashes'] or c['answers'] != own['answers']:
                    raise ValueError('Mismatched query/answer stream: ' + row['id'])
            best = [min(c['values'][i] for _, c in others) for i in range(512)]
            wins = [a <= b for a, b in zip(own['values'], best)]
            first = next((j+1 for j, win in enumerate(wins) if win), None)
            last_loss = max((j+1 for j, win in enumerate(wins) if not win), default=0)
            sustained = last_loss+1 if last_loss < 512 else None
            result.append(dict(id=row['id'], case=row['case'], method=row['method'], baseline=baseline,
                first_observed_crossover=first, sustained_through_512_from=sustained,
                winning_prefixes=sum(wins),
                checkpoints={str(n): dict(ours=own['values'][n-1], baseline=best[n-1]) for n in (1, 8, 64, 512)},
                source_records=own['records'], baseline_records=[p for _, c in others for p in c['records']],
                query_sha256=own['hashes'][0]))
    return dict(source_analysis_sha256=hashlib.sha256(raw).hexdigest(),
        interpretation='Measured ordered prefixes only. Five successful repeats per strategy. No inference beyond 512 or to other workloads.',
        comparator='Pointwise best measured strategy, selection cost uncharged; not an implementable online selection claim.',
        new_ports_algorithm_included=False, rows=result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--out', default='results/compilation_economics.json')
    args = parser.parse_args()
    result = analyze(args.root)
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2)+'\n', encoding='utf8')
    for r in result['rows']:
        if r['id'] in ('c002', 'c004', 'c005', 'c007', 'c008', 'c011', 'c012', 'c013', 'a016'):
            print(r['id'], r['method'], r['baseline'], 'first', r['first_observed_crossover'],
                  'sustained', r['sustained_through_512_from'], 'wins', r['winning_prefixes'],
                  '512', r['checkpoints']['512'])


if __name__ == '__main__':
    main()
