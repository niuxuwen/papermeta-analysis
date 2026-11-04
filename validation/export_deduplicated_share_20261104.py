"""Replay real data, export entity mappings, and preserve the previous share verbatim."""
from pathlib import Path
import collections
import csv
import gzip
import hashlib
import json
import shutil
import sqlite3
import sys
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'backend'))
from benchmark_entities import build_registry
BASE=Path('D:/FDU/wispaper/data-shares/benchmark-data-20261104')
OUT=BASE.parent/'benchmark-data-deduplicated-20261104'

def encode(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'))
def digest(path):
    with path.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    OUT.mkdir(exist_ok=True)
    with gzip.open(BASE/'snapshot.json.gz','rt',encoding='utf8')as f:source=json.load(f)
    registry={**build_registry(source['benchmarks']),'snapshot_id':source['snapshot_id'],'generated_at':source['generated_at']}
    mappings=registry['mappings'];assert len(mappings)==len(source['benchmarks'])
    assert len({(m['paper_id'],m['benchmark_id'])for m in mappings})==len(mappings)
    for m in mappings:
        assert (m['status']=='RESOLVED')==(m['entity_id']is not None and m['variant_id']is not None)
    registry_file=OUT/'benchmark_entities.json';registry_file.write_text(encode(registry),encoding='utf8')
    (REPO/'validation/benchmark-entities-real-20261104.json').write_text(encode(registry),encoding='utf8')
    # A compact full-source fixture for the actual JS display projection.
    fixture={k:source[k]for k in ('snapshot_id','benchmarks','observations','index')}
    # Preserve only rows necessary for source-membership/identity tests; score records are kept intact in original archive.
    fixture['benchmarks']=[{k:b[k]for k in ('paper_id','benchmark_id','benchmark_name','paper_title','eligibility','status','history_status','name_audit','directory_identity','catalog_identity','directory_sources')if k in b}for b in source['benchmarks']]
    fixture['observations']=[{k:r[k]for k in ('paper_id','benchmark_id','observation_id','model_canonical','value_raw','value_numeric')if k in r}for r in source['observations']]
    fixture['index']={'models':[{'model_canonical':m['model_canonical'],'score':m.get('score')}for m in source['index']['models']], 'groups':[]}
    (REPO/'validation/entity-projection-real-fixture.json').write_text(encode(fixture),encoding='utf8')
    for path in BASE.iterdir():
        if path.name in {'prepare_share.py','validation.json','README.txt','SHA256SUMS.txt'}or not path.is_file():continue
        if not (OUT/path.name).exists():shutil.copy2(path,OUT/path.name)
    con=sqlite3.connect(OUT/'research.sqlite')
    entities=[]
    for e in registry['entities']:
        entities.append({**{k:e[k]for k in ('entity_id','canonical_name','reference_url','match_basis')},
            'source_records':len(e['sources']),'source_papers':len({r['paper_id']for r in e['sources']}),
            'variant_count':len(e['variants']),'aliases':e['aliases']})
    tables={'benchmark_entities':entities,'benchmark_variants':registry['variants'],'benchmark_entity_sources':mappings}
    for name,rows in tables.items():
        fields=list(rows[0]) if rows else ['entity_id']
        con.execute('DROP TABLE IF EXISTS '+name)
        con.execute('CREATE TABLE '+name+' ('+','.join('"'+f+'" TEXT'for f in fields)+')')
        def vals(row):return [encode(row.get(f))if isinstance(row.get(f),(list,dict))else row.get(f)for f in fields]
        con.executemany('INSERT INTO '+name+' VALUES ('+','.join('?'for f in fields)+')',[vals(r)for r in rows])
        with (OUT/(name+'.csv')).open('w',encoding='utf-8-sig',newline='')as f:
            writer=csv.writer(f);writer.writerow(fields);writer.writerows(vals(r)for r in rows)
    con.execute('CREATE UNIQUE INDEX IF NOT EXISTS entity_source_key ON benchmark_entity_sources(paper_id,benchmark_id)')
    con.execute('CREATE INDEX IF NOT EXISTS entity_source_entity ON benchmark_entity_sources(entity_id)')
    assert con.execute('SELECT COUNT(*) FROM observations').fetchone()[0]==len(source['observations'])
    # The original six tables must match every original cell, not just their counts.
    con.execute('ATTACH DATABASE ? AS original',(str(BASE/'research.sqlite'),))
    for table in ('observations','benchmarks','model_scores','metric_groups','group_scores','capability_annotations'):
        assert con.execute('SELECT COUNT(*) FROM (SELECT * FROM main.'+table+' EXCEPT SELECT * FROM original.'+table+')').fetchone()[0]==0
        assert con.execute('SELECT COUNT(*) FROM (SELECT * FROM original.'+table+' EXCEPT SELECT * FROM main.'+table+')').fetchone()[0]==0
    con.commit();assert con.execute('PRAGMA integrity_check').fetchone()[0]=='ok';con.close()
    assert digest(OUT/'snapshot.json.gz')==digest(BASE/'snapshot.json.gz')
    examples={e['canonical_name']:{'sources':len(e['sources']),'variants':len(e['variants'])}for e in registry['entities']if e['reference_url']}
    report={**registry['statistics'],'snapshot_id':source['snapshot_id'],'source_time':source['generated_at'],
        'examples':examples,'original_tables_cell_equality':'PASS','source_archive_sha256':'PASS','sqlite_integrity':'PASS','model_calls':0}
    (OUT/'deduplication_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    readme=(BASE/'README.txt').read_text(encoding='utf-8-sig')
    extra=f'''跨论文归并更新（2026-11-04）

全部来源记录：{len(mappings)} 条，按规则已归并 {len(registry['entities'])} 个 Benchmark 实体、{len(registry['variants'])} 个版本/子集。
身份待核来源：{registry['statistics']['unresolved_source_records']} 条，单列保留，不计作已归并实体总数。
实体匹配包括：已登记别名、具有区分度名称的精确规范化匹配、共享资源且有明确别名的匹配；不使用模糊字符串强行合并。RESOLVED 表示已按公开规则分配实体，不表示逐个经人工独立认证。match_basis 保留匹配依据。无资源的精确名称匹配仍可能存在未检出的同名异物；已识别的冲突单列待核。统计不是“所有真实评测集已穷尽”。

新增文件/SQLite 表：benchmark_entities（每个实体一行）、benchmark_variants（版本/子集）、benchmark_entity_sources（原论文/Benchmark 与实体映射）；benchmark_entities.json 含完整规则版本、引用链接与对应关系。
名称待核验、Accuracy/Overall、未确定的短缩写及有冲突的名称不凑入实体总数。版本/语言/子集不同的 variant_id 不同。MMLU 与 MMLU-Pro、HumanEval 与 HumanEval+ 不合并。
原始六张表和 snapshot.json.gz 逐值保留，包含旧 catalog_identity/directory_identity（来源管理口径）；研究时请通过新增 entity_id / variant_id 统计独立项目。原始实验组、成绩和评分未合并重算，来源身份也不被覆盖。

SQL 示例（去重后实体数）：
SELECT COUNT(*) FROM benchmark_entities;
SQL 示例（查一个 Benchmark 在各论文中的记录）：
SELECT b.* FROM benchmarks b JOIN benchmark_entity_sources m USING(paper_id,benchmark_id) JOIN benchmark_entities e USING(entity_id) WHERE e.canonical_name='MMLU';

''' + readme
    (OUT/'README.txt').write_text(extra,encoding='utf-8-sig')
    names=[p.name for p in OUT.iterdir()if p.is_file()and p.name!='SHA256SUMS.txt']
    (OUT/'SHA256SUMS.txt').write_text(''.join(digest(OUT/n)+'  '+n+'\n'for n in sorted(names)),encoding='ascii')
    package=OUT.parent/'benchmark-research-data-deduplicated-20261104.zip'
    with ZipFile(package,'w',ZIP_DEFLATED,compresslevel=6)as archive:
        for p in OUT.iterdir():
            if p.is_file():archive.write(p,p.name,compress_type=ZIP_STORED if p.suffix=='.gz'else ZIP_DEFLATED)
    with ZipFile(package)as archive:assert archive.testzip()is None
    report.update(package=str(package),package_bytes=package.stat().st_size,package_sha256=digest(package))
    (REPO/'validation/benchmark-entities-share-validation-20261104.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=True),flush=True)

if __name__=='__main__':main()
