"""Local typesetting audit; does not execute research experiments."""
from pathlib import Path
import json, re, shutil, subprocess
from pypdf import PdfReader
from PIL import Image, ImageOps, ImageDraw
root=Path(__file__).resolve().parent
qa=root/'qa'; qa.mkdir(exist_ok=True)
pdf=PdfReader(root/'main.pdf')
tool=shutil.which('pdftotext')
if tool is None: raise SystemExit('pdftotext is needed for Chinese text extraction.')
subprocess.run([tool, '-layout', '-enc', 'UTF-8', str(root/'main.pdf'), str(qa/'poppler.txt')], check=True)
pages=(qa/'poppler.txt').read_text(encoding='utf-8').split('\f')[:len(pdf.pages)]
(qa/'extracted.txt').write_text('\n\n'.join(f'PAGE {i+1}\n{s}' for i,s in enumerate(pages)),encoding='utf-8')
images=sorted(p for p in qa.glob('final-*.png') if re.fullmatch(r'final-\d+\.png',p.name))
if not images: images=sorted(qa.glob('page-*.png'))
for start in range(0,len(images),4):
    sheet=Image.new('RGB',(1450,2080),'#dddddd')
    draw=ImageDraw.Draw(sheet)
    for offset,p in enumerate(images[start:start+4]):
        im=Image.open(p).convert('RGB'); im.thumbnail((710,1000))
        x=(offset%2)*725+(725-im.width)//2
        y=(offset//2)*1040+30
        sheet.paste(im,(x,y)); draw.text((x,y-22),f'Page {start+offset+1}',fill='black')
    sheet.save(qa/f'contact-{start//4+1:02}.png')
report={'pages':len(pages),'rendered_pages':len(images),
        'page_text_lengths':[len(p) for p in pages],
        'unresolved_question_marks':[(i+1) for i,p in enumerate(pages) if '??' in p],
        'replacement_characters':[(i+1) for i,p in enumerate(pages) if '\ufffd' in p],
        'log_findings':re.findall(r'^.*(?:Overfull|Missing character|undefined).*$',(root/'main.log').read_text(encoding='utf-8',errors='replace'),re.M),
        'page_starts':[p[:95].replace('\n',' ') for p in pages]}
(qa/'pdf_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='page_starts'},ensure_ascii=True))
