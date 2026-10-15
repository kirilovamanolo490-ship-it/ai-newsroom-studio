"""Rebuild the local index and its reader-facing archive without touching editions."""
from pathlib import Path
import json, shutil, argparse
from news_archive import rebuild, DEFAULT_ROOT

def build(root=DEFAULT_ROOT):
    root=Path(root)
    result=rebuild(root)
    public=root/'research/evidence'
    source=root/'research/report-redesign'
    data=json.loads((public/'archive/data.json').read_text())
    assets=public/'assets'; assets.mkdir(parents=True,exist_ok=True)
    for name in ('archive.css','archive.js'):
        shutil.copy2(source/name,assets/name)
    template=(source/'archive.html').read_text()
    (public/'index.html').write_text(template.replace('__DEFAULT_DATE__',''))
    (public/'archive/index.html').write_text(template.replace('__DEFAULT_DATE__',''))
    for date in sorted({e['date'] for e in data['editions']}):
        path=public/date/'index.html'; path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(template.replace('__DEFAULT_DATE__',date))
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=DEFAULT_ROOT)
    print(json.dumps(build(parser.parse_args().root),ensure_ascii=False))
