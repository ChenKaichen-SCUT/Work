"""Aggregate raw records, keep censored runs, audit identical complete answers."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import statistics


def analyze(root):
    rows = []
    environments = {}
    for campaign in sorted(p for p in root.iterdir() if p.is_dir()):
        env = campaign/'environment.json'
        if not env.exists():
            continue
        environments[campaign.name] = json.loads(env.read_text())
        for path in sorted(campaign.glob('[0-9]*.json')):
            record = json.loads(path.read_text())
            record['campaign'] = campaign.name; record['record_path'] = str(path.relative_to(root))
            rows.append(record)
    answers = {}; checked = defaultdict(set); mismatches = []
    grouped = defaultdict(list)
    for r in rows:
        spec = r['spec']; key = (r['campaign'], spec['family'], spec['n'], spec['method'])
        grouped[key].append(r)
        if r['status'] == 'ok':
            answer_key = (spec['family'], spec['n'], r['query_sha256'])
            if answer_key in answers and answers[answer_key] != r['answers_sha256']:
                mismatches.append(r['record_path'])
            answers[answer_key] = r['answers_sha256']; checked[answer_key].add(spec['method'])
    aggregates = []
    metrics = ('compile_seconds', 'setup_seconds', 'complete_query_seconds', 'first_complete_total_seconds',
               'states', 'transitions', 'label_literals', 'unique_label_literals', 'label_descriptors',
               'clauses', 'cnf_variables', 'max_interface', 'max_layer_states', 'peak_rss_kib', 'elapsed_seconds')
    for (campaign, family, n, method), rs in sorted(grouped.items()):
        ok = [r for r in rs if r['status'] == 'ok']
        out = dict(campaign=campaign, family=family, n=n, method=method, repetitions=len(rs),
                   completed=len(ok), statuses={s: sum(r['status'] == s for r in rs)
                                               for s in sorted({r['status'] for r in rs})},
                   failures=[dict(path=r['record_path'], stage=r.get('stage'), reason=r.get('reason'))
                             for r in rs if r['status'] != 'ok'])
        for metric in metrics:
            values = [r[metric] for r in ok if metric in r]
            if values:
                out[metric] = dict(median=statistics.median(values), min=min(values), max=max(values))
        if ok:
            out['query_count'] = ok[0]['query_count']; out['sat_queries'] = ok[0]['sat_queries']
            out['total_compile_setup_64queries'] = statistics.median(
                r['compile_seconds']+r['setup_seconds']+r['complete_query_seconds'] for r in ok)
        aggregates.append(out)
    report = dict(records=len(rows), completed_records=sum(r['status'] == 'ok' for r in rows),
                  statuses={s: sum(r['status'] == s for r in rows) for s in sorted({r['status'] for r in rows})},
                  complete_query_evaluations=sum(r.get('query_count', 0) for r in rows if r['status'] == 'ok'),
                  identical_query_sets=len(checked), cross_method_sets=sum(len(s) > 1 for s in checked.values()),
                  mismatches=mismatches, environments=environments, aggregates=aggregates)
    headline = [r for r in rows if r['campaign'] in ('final', 'cnf_final', 'frontier_final')]
    report['headline'] = dict(records=len(headline), completed_records=sum(r['status'] == 'ok' for r in headline),
                             complete_query_evaluations=sum(r.get('query_count', 0) for r in headline if r['status'] == 'ok'),
                             statuses={s: sum(r['status'] == s for r in headline) for s in sorted({r['status'] for r in headline})})
    (root/'analysis.json').write_text(json.dumps(report, indent=2))
    lines = ['SERVER CONSTRUCTION RESULTS: medians over completed repetitions',
             'UNKNOWN runs remain censored; no timings imputed for them.',
             'Headline rows: final, cnf_final, frontier_final. Other runs are exploratory.',
             'campaign family n method ok/all compile_s setup_s complete64_s states clauses RSS_MiB']
    for row in aggregates:
        def val(metric, digits=6):
            return f"{row[metric]['median']:.{digits}f}" if metric in row else '-'
        rss = f"{row['peak_rss_kib']['median']/1024:.2f}" if 'peak_rss_kib' in row else '-'
        lines.append(f"{row['campaign']} {row['family']} {row['n']} {row['method']} "
                     f"{row['completed']}/{row['repetitions']} {val('compile_seconds')} {val('setup_seconds')} "
                     f"{val('complete_query_seconds')} {val('states',0)} {val('clauses',0)} {rss}")
    lines.append(f"Cross-method answer mismatches: {len(mismatches)}")
    (root/'tables.txt').write_text('\n'.join(lines)+'\n')
    if mismatches or report['statuses'].get('ERROR', 0):
        raise SystemExit('Correctness/error audit failed')
    return report


def main():
    p = argparse.ArgumentParser(); p.add_argument('--root', default='results/construction'); a = p.parse_args()
    report = analyze(Path(a.root))
    print(json.dumps({k: report[k] for k in ('records', 'completed_records', 'statuses',
                                           'complete_query_evaluations', 'cross_method_sets', 'mismatches')}, indent=2))


if __name__ == '__main__':
    main()
