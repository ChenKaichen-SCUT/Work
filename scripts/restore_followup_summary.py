"""Restore the exact frozen aggregate without overwriting an existing result."""
import gzip
import hashlib
import json
from pathlib import Path


def main():
    folder=Path(__file__).resolve().parents[1]/'results/causal_followup_20261028'
    meta=json.loads((folder/'summary.storage.json').read_text(encoding='utf8'))
    source=folder/meta['stored_name'];target=folder/meta['original_name']
    packed=source.read_bytes()
    assert hashlib.sha256(packed).hexdigest()==meta['stored_sha256']
    restored=gzip.decompress(packed)
    assert len(restored)==meta['original_bytes']
    assert hashlib.sha256(restored).hexdigest()==meta['original_sha256']
    if target.exists():
        if target.read_bytes()!=restored:
            raise RuntimeError('Existing summary differs; preserve it separately before restoring the frozen aggregate')
        print('Existing summary matches the frozen SHA256:',meta['original_sha256'])
    else:
        with target.open('xb') as output:output.write(restored)
        print('Restored and verified:',target)


if __name__=='__main__':main()
