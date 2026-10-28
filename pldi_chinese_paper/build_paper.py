"""Build the manuscript without running any research experiment."""
from pathlib import Path
import argparse
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--redraw', action='store_true', help='Redraw using bundled frozen JSON')
args = parser.parse_args()
if args.redraw:
    subprocess.run([sys.executable, str(ROOT/'generate_results.py'), '--snapshot'], cwd=ROOT, check=True)
for name in ('xelatex', 'bibtex'):
    if shutil.which(name) is None:
        raise SystemExit(f'{name} is required on PATH (TeX Live with ctex and Fandol).')
commands = [
    ['xelatex', '-interaction=nonstopmode', '-halt-on-error', 'main.tex'],
    ['bibtex', 'main'],
    ['xelatex', '-interaction=nonstopmode', '-halt-on-error', 'main.tex'],
    ['xelatex', '-interaction=nonstopmode', '-halt-on-error', 'main.tex'],
]
for i, command in enumerate(commands, 1):
    with (ROOT/f'build-pass{i}.txt').open('wb') as stream:
        result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    if result.returncode:
        raise SystemExit(f'Build failed; inspect build-pass{i}.txt and main.log.')
log = (ROOT/'main.log').read_text(encoding='utf-8', errors='replace')
bad = [line for line in log.splitlines()
       if any(word in line for word in ('Overfull', 'Missing character', 'undefined references', 'undefined citations'))]
if bad:
    raise SystemExit('Typesetting needs review: '+repr(bad))
destination = ROOT/'output'/'pdf'/'causal_frontier_pldi_zh.pdf'
destination.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(ROOT/'main.pdf', destination)
print('Built '+str(destination))
