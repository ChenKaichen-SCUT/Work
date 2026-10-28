"""Package the self-contained paper, frozen plotting inputs, and review notes."""
from pathlib import Path
import argparse
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, default=ROOT.parent/'artifacts'/'pldi_chinese_paper_20261028.zip')
args = parser.parse_args()
files = sorted({*ROOT.glob('*.tex'), *ROOT.glob('*.bib'), *ROOT.glob('*.py'),
                ROOT/'README.zh.txt', ROOT/'requirements-paper.txt', ROOT/'.gitignore',
                *[p for folder in ('data','generated','figures','internal','output/pdf')
                  for p in (ROOT/folder).rglob('*') if p.is_file()]})
assert (ROOT/'output/pdf/causal_frontier_pldi_zh.pdf') in files
manifest = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
args.output.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(args.output, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
    for p in files:
        entry = zipfile.ZipInfo('pldi_chinese_paper/'+p.relative_to(ROOT).as_posix(), (2026,10,28,0,0,0))
        entry.compress_type = zipfile.ZIP_DEFLATED
        bundle.writestr(entry, p.read_bytes())
    entry = zipfile.ZipInfo('pldi_chinese_paper/PACKAGE_MANIFEST.json', (2026,10,28,0,0,0))
    entry.compress_type = zipfile.ZIP_DEFLATED
    bundle.writestr(entry, json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
print(json.dumps({'files':len(files), 'zip_bytes':args.output.stat().st_size,
                  'sha256':hashlib.sha256(args.output.read_bytes()).hexdigest()}, indent=2))
