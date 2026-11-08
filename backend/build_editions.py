"""Package both language routes and the deterministic task scorer for this publication."""
import base64
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import tarfile
from urllib.request import urlopen
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
RUNTIME = "0.27.7"
CHECKSUM = "RUSVJlhQdfWfgO9hVHCiXoG+nVZQRS5D9FzgpLJ/VcgGBLSAKoPL8kTiOikxbHQm1kRISeWUBdulEgO26qpSRA=="

def package_runtime():
    folder = SITE / "task-runtime" / RUNTIME
    folder.mkdir(parents=True, exist_ok=True)
    with urlopen(f"https://registry.npmjs.org/pyodide/-/pyodide-{RUNTIME}.tgz", timeout=90) as response:
        archive = response.read()
    if base64.b64encode(hashlib.sha512(archive).digest()).decode() != CHECKSUM:
        raise ValueError("Python runtime failed integrity check")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for name in ("pyodide.js","pyodide.asm.js","pyodide.asm.wasm","python_stdlib.zip","pyodide-lock.json","README.md"):
            (folder/name).write_bytes(tar.extractfile("package/"+name).read())
    with ZipFile(SITE/"task-engine.zip","w",compression=ZIP_DEFLATED) as bundle:
        for file in sorted((ROOT/"task_engine").glob("*.py")):
            bundle.write(file, "task_engine/"+file.name)

def editions():
    manifest = json.loads((SITE/"snapshot/current.json").read_bytes())
    assert manifest["automatic_publication"] and not manifest.get("local_frozen")
    sid = manifest["snapshot_id"]
    gen = SITE/"snapshot"/sid
    boards = json.loads((SITE/"capability-rankings.json").read_bytes())
    assert boards["snapshot"] == sid and set(boards["boards"]) == {"Science","Coding","General","Agent"}
    shutil.move(SITE/"capability-rankings.json",gen/"capability-rankings.json")
    shutil.move(SITE/"snapshot-elo-data.js",gen/"elo.js")
    ranking = json.loads(gzip.decompress((SITE/manifest["ranking"]["path"]).read_bytes()))
    names = {str(b.get(k) or "") for b in ranking["benchmarks"] for k in ("benchmark_name","paper_title")}
    names.update(m["model_canonical"] for m in ranking["index"]["models"])
    labels = json.loads((ROOT/"language/auto.json").read_text(encoding="utf-8"))
    for line in (ROOT/"language/editorial.txt").read_text(encoding="utf-8-sig").splitlines():
        key, value = line.split("|",1)
        labels[key] = value
    dictionary = {"labels":labels,"names":sorted(n for n in names if re.search(r"[\u3400-\u9fff]",n))}
    (gen/"dictionary.js").write_text("window.paperMateEnglish="+json.dumps(dictionary,ensure_ascii=False)+";",encoding="utf-8")
    (gen/"task-manifest.json").write_text(json.dumps({k:manifest[k] for k in ("snapshot_id","task_inputs","generated_at")}),encoding="utf-8")
    for name in ("index.html","benchmark.html","benchmark/index.html"):
        source = (SITE/name).read_text(encoding="utf-8")
        source = re.sub(r'\./snapshot-elo-data\.js(?:\?v=[a-f0-9]+)?',f'/snapshot/{sid}/elo.js',source)
        source = re.sub(r'((?:src|href)=")\./([^"/]+\.(?:css|js))',r'\1/\2',source)
        for english in (False,True):
            text = source
            additions = '<link rel="stylesheet" href="/english.css"><script defer src="/language.js"></script>'
            if english:
                text = re.sub(r'<html\b[^>]*>', '<html lang="en">', text, count=1)
                additions += f'<script defer src="/snapshot/{sid}/dictionary.js"></script><script defer src="/english.js"></script>'
            text = text.replace('<meta charset="utf-8">','<meta charset="utf-8">'+additions,1)
            target = SITE/name if english else SITE/"zh"/name
            target.parent.mkdir(exist_ok=True,parents=True)
            target.write_text(text,encoding="utf-8")
    if (SITE/"vendor-logos").exists():
        shutil.copytree(SITE/"vendor-logos", SITE/"zh/vendor-logos",dirs_exist_ok=True)
    print("Published language routes and four capability boards for",sid,flush=True)

if __name__ == "__main__":
    package_runtime()
    editions()
