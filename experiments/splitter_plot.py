"""Render the frozen splitter audit, keeping fresh batches distinct from reuse."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.input.read_text())
    factor = [r for r in data['factorization_runs'] if r['workers'] == 3 and r['status'] == 'OK']
    whole = [r for r in data['runs'] if r['workers'] == 3 and r['duplicate_stop']
             and not r['global_init_hb'] and r['status'] == 'OK']
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.7), constrained_layout=True)
    axes[0].plot([r['batches'] for r in factor], [r['max_interface'] for r in factor], 'o-', label='Object factorization')
    axes[0].plot([r['batches'] for r in whole], [r['stats']['max_interface'] for r in whole], 's--', label='Whole-trace layout')
    axes[0].set(xscale='log', xlabel='Fresh grid batches (3 workers)', ylabel='Maximum event interface', ylim=(0, 16))
    axes[0].legend(frameon=False)
    axes[1].loglog([r['batches'] for r in factor], [r['compile_seconds'] for r in factor], 'o-', label='Object factorization')
    axes[1].loglog([r['batches'] for r in whole], [r['stats']['compile_seconds'] for r in whole], 's--', label='Whole-trace layout')
    axes[1].set(xlabel='Fresh grid batches (3 workers)', ylabel='Compilation seconds')
    axes[1].legend(frameon=False)
    for ax in axes:
        ax.grid(alpha=.25)
    fig.suptitle('Release/acquire splitter port: fresh objects, not in-place reuse', fontsize=11)
    for ext in ('png', 'svg'):
        fig.savefig(args.input.parent/('splitter_scaling.'+ext), dpi=180)
    plt.close(fig)


if __name__ == '__main__':
    main()
