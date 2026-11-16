"""Resumable date reviewer over real pinned source evidence, separate from scoring.

Existing audited facts are reused only after quote/hash/alias/novelty checks.
New claims retain pending first dates until a qualifying official public event
is found. No score queues, model retries or paper windows are changed.
"""
import argparse
from collections import Counter,defaultdict
from datetime import date,datetime,timedelta,timezone
from functools import lru_cache
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import shlex
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote,urlsplit
import urllib.request
import xml.etree.ElementTree as ET

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'runtime'))
from recent_benchmarks.automatic_date_policy import catalog,fact_evidence
from recent_benchmarks.release_ledger import source_projection,digest,validate_registry

POLICY='automatic-benchmark-dates-v2'
UTC=timezone.utc
BJ=timezone(timedelta(hours=8))


def now():return datetime.now(UTC).isoformat()
def norm(x):return ' '.join(str(x).split()).casefold()
def atomic(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(path.suffix+'.pending')
    with tmp.open('w',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,separators=(',',':'));f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)


def source_signature(row):
    return digest(source_projection(row))


def proof(url,text,method='CURRENT_SOURCE_HASH_AND_QUOTE_CHECK'):
    return dict(primary=True,review_status='VERIFIED',url=url,quote=text[:1800],reviewed_at=now(),review_method=method)


def read_document(path):
    raw=path.read_bytes();data=json.loads(raw)
    if not isinstance(data,list):raise ValueError('Source content list must be an array')
    parts=[]
    for item in data:
        if isinstance(item,dict):
            for k in ['text','table_caption','table_footnote','table_body']:
                v=item.get(k)
                if isinstance(v,str):parts.append(v)
                elif isinstance(v,list):parts.extend(str(s)for s in v)
    return hashlib.sha256(raw).hexdigest(),'\n'.join(parts)


class Sources:
    def __init__(self,project):
        self.project=project.resolve();self.runs=defaultdict(list)
        for p in (project/'data/runs').iterdir():
            if p.is_dir() and p.name.startswith('live-'):self.runs['recent-'+p.name[5:21]].append(p)
        self.documents_read=0
        self.thread_cache=threading.local()

    @lru_cache(maxsize=20000)
    def stamp(self,paper_id):
        stamps=[]
        for root in self.runs.get(paper_id,[]):
            p=root/'evidence'/(paper_id+'.json')
            if p.exists():
                s=p.stat();stamps.append((p.name,s.st_size,s.st_mtime_ns))
        return stamps

    def get(self,paper_id):
        previous=getattr(self.thread_cache,'paper',None)
        if previous and previous[0]==paper_id:return previous[1]
        result=self._read(paper_id);self.thread_cache.paper=(paper_id,result);return result

    @lru_cache(maxsize=12)
    def _read(self,paper_id):
        choices=[]
        for root in self.runs.get(paper_id,[]):
            p=root/'evidence'/(paper_id+'.json')
            if p.exists():choices.append((p.stat().st_mtime,root,p))
        if not choices:return None,'NO_CAPTURED_PAPER_EVIDENCE'
        _,root,path=max(choices)
        data=json.loads(path.read_text(encoding='utf-8'))
        if (data.get('paper') or {}).get('paper_id')!=paper_id:return None,'PAPER_ID_MISMATCH'
        value=data.get('source_path');sha=data.get('source_sha256')
        if not value or not sha:return None,'SOURCE_REFERENCE_MISSING'
        p=(root/str(value).replace('\\','/')).resolve()
        if not p.is_relative_to(root.resolve()) or not p.name.endswith('_content_list.json'):
            return None,'UNSAFE_SOURCE_REFERENCE'
        if not any(x in p.relative_to(root.resolve()).parts for x in ['mineru','html']):return None,'SOURCE_OUTSIDE_PARSER_OUTPUT'
        if not p.is_file():return None,'SOURCE_FILE_MISSING'
        got,text=read_document(p)
        if got!=sha:return None,'SOURCE_HASH_MISMATCH'
        self.documents_read+=1
        return {'raw':data,'text':text,'normalized_text':norm(text),'source_sha256':sha},None


def select_benchmark(row,context):
    name=row.get('benchmark_name','');matches=[]
    for b in context['raw'].get('benchmarks',[]):
        names=[b.get('name',''),*b.get('aliases',[])]
        if b.get('benchmark_id')==row['benchmark_id'] or any(norm(n)==norm(name)for n in names):matches.append(b)
    if len(matches)!=1:return None,'SOURCE_BENCHMARK_IDENTITY_AMBIGUOUS'
    b=matches[0]
    facts=[b,*b.get('evidence',[])]
    if any(x.get('identity_conflict') or x.get('date_source_mismatch') for x in facts):return None,'SOURCE_IDENTITY_CONFLICT'
    quotes=[x.get('evidence_quote','')for x in facts]
    valid=[q for q in quotes if isinstance(q,str) and len(q.strip())>=12 and norm(q) in context['normalized_text']]
    identifying=[q for q in valid if norm(name) in norm(q)]
    # Parser paragraph/table boundaries can differ from the extraction quote.
    # Re-read an actual captured paragraph around the exact name, requiring a
    # substantial lexical alignment with the original evidence. Keep the real
    # source paragraph as the new quote; never label generated prose as a quote.
    if not identifying:
        tokens=lambda s:set(re.findall(r'[a-z0-9]{3,}',norm(s)))
        source=context.get('text','');pos=norm(source).find(norm(name))
        if pos>=0:
            for paragraph in source.splitlines():
                if norm(name)not in norm(paragraph):continue
                words=tokens(paragraph)
                for q in quotes:
                    wanted=tokens(q)
                    if (len(wanted)>=16 and len(words&wanted)>=16
                            and len(words&wanted)/len(wanted)>=0.7):
                        identifying.append(paragraph);break
    if not identifying:return None,'BENCHMARK_QUOTE_NOT_IN_PINNED_SOURCE'
    return {**b,'checked_quote':min(identifying,key=len)},None


def repos_for(row,b,context):
    snippets=[b['checked_quote'],(context['raw'].get('paper')or{}).get('abstract_text','')]
    text=context['text'];label=row['benchmark_name'];pos=text.casefold().find(label.casefold())
    if pos>=0:snippets.append(text[max(0,pos-1000):pos+3500])
    refs=set()
    for text in snippets:
        for owner,repo in re.findall(r'https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)',text):
            repo=repo.removesuffix('.git').rstrip('.')
            if owner not in {'features','topics','orgs'} and repo:refs.add(owner+'/'+repo)
    return sorted(refs)[:3]


def base_record(row,b,context):
    paper=context['raw']['paper'];url=paper.get('url')or row.get('source_url')
    if not url or not url.startswith('https://'):raise ValueError('Pinned source URL unavailable')
    text=b['checked_quote'];position=text.casefold().find(row['benchmark_name'].casefold())
    if position>=0 and len(text)>1800:text=text[max(0,position-200):position+1500]
    return {'entity_id':'auto-source-'+digest([row['paper_id'],row['benchmark_id']])[:24],
        'name':row['benchmark_name'],'aliases':b.get('aliases',[]),'kind':'BENCHMARK','scope':'LLM' if b.get('tests_llms')is True else 'UNVERIFIED',
        'decision':'PENDING','identity_evidence':proof(url,text),
        'source_refs':[{'paper_id':row['paper_id'],'benchmark_id':row['benchmark_id'],'source_signature':source_signature(row)}],
        'source_checks':[{'paper_id':row['paper_id'],'benchmark_id':row['benchmark_id'],
            'source_sha256':context['source_sha256'],'quote_verified':True,'novelty':b.get('novelty'),'checked_at':now()}],
        'events':[],'review_notes':'已重新校验原文哈希及引句；当前仍缺首次公开日期主证据。'}


def audited_old(row,b,context):
    data,_=catalog();facts=[b,*b.get('evidence',[])]
    if any(f.get('novelty')!='EXISTING' for f in facts) or b.get('tests_llms')is not True:return None
    names=[b.get('name'),*b.get('aliases',[])]
    if norm(b.get('name'))in {'math','drop'} and b.get('name')not in {'MATH','DROP'}:return None
    matches=[f for f in data['facts'] if all(isinstance(n,str)and norm(n)in {norm(a)for a in f['aliases']}for n in names)]
    if len(matches)!=1:return None
    f=matches[0];record=base_record(row,b,context)
    record.update(entity_id='auto-known-'+f['id'],name=f['name'],aliases=f['aliases'],decision='EXISTING_OR_UPDATE',scope='LLM',
        review_notes='复用已审核历史主来源；本次已校验当前论文原文哈希、引句、新旧判断和精确别名。上界不等于首发日。')
    record['events']=[{'kind':'KNOWN_PUBLIC_EXISTENCE','date':f['public_by'],'timezone':'Asia/Shanghai',
        'date_basis':f['bound_basis'],'publication_verified':True,'proves_public_existence':True,'evidence':fact_evidence(f)}]
    return record


class PrimaryCache:
    def __init__(self,db,project=None):
        self.db=db;self.last=0.;self.reads=0;proxies={}
        network=project/'deployment/network.env'if project else None
        if network and network.exists():
            for line in network.read_text().splitlines():
                parts=shlex.split(line,comments=True)
                if parts and parts[0]=='export':parts=parts[1:]
                if len(parts)==1 and '='in parts[0]:
                    key,value=parts[0].split('=',1)
                    if key.lower()in {'http_proxy','https_proxy'}:proxies[key.lower().removesuffix('_proxy')]=value
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler(proxies))
    def get(self,url):
        host=urlsplit(url).hostname
        if host not in {'api.github.com','raw.githubusercontent.com','github.com'}:raise ValueError('Primary host not allowed')
        pause_key='github_pause_until'if host=='api.github.com'else 'primary_pause:'+host
        row=self.db.execute('SELECT body,status,expires FROM http_cache WHERE url=?',(url,)).fetchone()
        if row and row[2]>time.time():
            if row[1]!=200:raise RuntimeError('CACHED_HTTP_'+str(row[1]))
            return row[0]
        pause=self.db.execute('SELECT value FROM meta WHERE key=?',(pause_key,)).fetchone()
        if pause and float(pause[0])>time.time():raise RuntimeError('PRIMARY_HOST_BACKOFF')
        time.sleep(max(0,3.2-(time.monotonic()-self.last)))
        req=urllib.request.Request(url,headers={'User-Agent':'benchmark-date-review/1.0','Accept':'application/vnd.github+json'})
        self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('primary_activity',json.dumps({'url':url,'started_at':now()})))
        self.db.commit()
        try:
            with self.opener.open(req,timeout=25) as response:raw=response.read(3*1024*1024+1);status=response.status
            if len(raw)>3*1024*1024:raise ValueError('Primary response too large')
        except urllib.error.HTTPError as e:
            raw=b'';status=e.code
            if status in {403,429}:
                reset=e.headers.get('X-RateLimit-Reset','')
                until=float(reset) if reset.isdigit() and float(reset)>time.time() else time.time()+3600
                self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(pause_key,str(until)))
        except (urllib.error.URLError,TimeoutError,OSError):
            raw=b'';status=598
            self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(pause_key,str(time.time()+60)))
        self.last=time.monotonic();self.reads+=1
        expires=time.time()+(3600 if status in {403,429} else 86400 if status!=200 else 3600)
        self.db.execute('INSERT OR REPLACE INTO http_cache VALUES(?,?,?,?)',(url,raw,status,expires))
        self.db.commit()
        if status!=200:raise RuntimeError('PRIMARY_HTTP_'+str(status))
        return raw


def release_records(repo,cache):
    try:return json.loads(cache.get('https://api.github.com/repos/'+repo+'/releases?per_page=10'))
    except RuntimeError:
        # Official release Atom feed avoids treating an API quota as the end of
        # source research. Its updated timestamp proves a bound, not firstness.
        root=ET.fromstring(cache.get('https://github.com/'+repo+'/releases.atom'));ns={'a':'http://www.w3.org/2005/Atom'}
        result=[]
        for e in root.findall('a:entry',ns):
            link=e.find('a:link',ns);url=link.get('href','')if link is not None else ''
            if not url.startswith('https://github.com/'+repo+'/releases/tag/'):continue
            stamp=e.findtext('a:updated',namespaces=ns)
            if not stamp:continue
            result.append({'html_url':url,'published_at':stamp,'updated_at':stamp,'_atom_only':True,
                'tag_name':url.split('/releases/tag/',1)[1],
                'body':e.findtext('a:content',default='',namespaces=ns)})
        return result


def official_events(row,b,context,cache):
    record=base_record(row,b,context);paper=context['raw']['paper'];new=b.get('novelty')=='NEW'
    links=repos_for(row,b,context)
    if not links:return record,'NEEDS_PRIMARY_DATE','NO_OFFICIAL_REPOSITORY_IN_TARGET_CONTEXT'
    found=False;errors=[]
    for repo in links:
        try:
            releases=release_records(repo,cache)
            for release in releases:
                if release.get('draft') or not release.get('published_at'):continue
                tag=release.get('tag_name','')
                pinned='https://raw.githubusercontent.com/'+repo+'/'+quote(tag,safe='')+'/README.md'
                readme=cache.get(pinned).decode('utf-8',errors='replace')
                if norm(row['benchmark_name']) not in norm(readme):continue
                body=release.get('body')or''
                if norm(row['benchmark_name'])not in norm(body):continue
                found=True;url=release['html_url'];published=release['published_at'];at=release.get('updated_at')or published
                unedited=at==published and not release.get('_atom_only')
                body_quote=body[:1400] or release.get('name')or tag
                record['events'].append({'kind':'CODE_RELEASE' if unedited else 'KNOWN_PUBLIC_EXISTENCE','at':at,'publication_verified':True,
                    'proves_public_existence':True,'evidence':proof(url,body_quote,'OFFICIAL_RELEASE_AND_PINNED_README'),
                    'version_published_at':published,'release_body_unedited':unedited,
                    'pinned_readme_url':pinned,'pinned_readme_sha256':hashlib.sha256(readme.encode()).hexdigest()})
                # Exact firstness is much narrower than a version/data release.
                if (new and unedited and paper.get('metadata_verification')=='V1_DECLARED'
                        and re.search(r'\bfirst public (?:release|introduction) of (?:the )?'+re.escape(row['benchmark_name'])+r'\b',body,re.I)):
                    meta=json.loads(cache.get('https://api.github.com/repos/'+repo));stamp=datetime.fromisoformat(at.replace('Z','+00:00'))
                    created=datetime.fromisoformat(meta['created_at'].replace('Z','+00:00'))
                    submitted=datetime.fromisoformat(paper['publication_date'].replace('Z','+00:00'))
                    history=b.get('history')or{}
                    if (created.astimezone(BJ).date()==stamp.astimezone(BJ).date() and submitted>=stamp
                            and not history.get('papers') and not b.get('identity_conflict')):
                        first={'kind':'FIRST_PUBLIC_INTRODUCTION','at':at,'date_basis':'PUBLISHER_RELEASE_TIMESTAMP',
                            'publication_verified':True,'proves_public_existence':True,'evidence':proof(url,body_quote,'FIRST_VERSION_SOURCE_CROSS_CHECK')}
                        record.update(decision='CONFIRMED_NEW',firstness_evidence=proof(url,body_quote,'FIRST_VERSION_SOURCE_CROSS_CHECK'))
                        # Same primary repository/name is one public entity even
                        # when multiple independent papers evaluate it.
                        record['entity_id']='auto-first-public-'+digest([repo,norm(row['benchmark_name'])])[:24]
                        record['events'].append(first)
            if found:break
        except Exception as e:errors.append(type(e).__name__+(':'+str(e)[:180]if isinstance(e,RuntimeError)else ':PRIMARY_FETCH_UNAVAILABLE'))
    record['review_notes']='官方版本发布和固定版本README已检查；版本发布日期不会自动当成首次公开日。'+(';'.join(errors)if errors else '')
    return record,('VERIFIED_FIRST_DAY' if record['decision']=='CONFIRMED_NEW' else 'VERIFIED_PUBLIC_BOUND' if found else 'FETCH_BLOCKED' if errors else 'NEEDS_PRIMARY_DATE'),(';'.join(errors)if errors else 'FIRSTNESS_OR_FIRST_PUBLIC_DAY_NOT_ESTABLISHED')


class Reviewer:
    def __init__(self,project,state,manual,work_db=None):
        self.project=project;self.state=state;state.mkdir(parents=True,exist_ok=True)
        self.durable=state/'queue.sqlite';self.work_db=work_db
        self.db=sqlite3.connect(work_db or self.durable);self.db.row_factory=sqlite3.Row
        if work_db and self.durable.exists():
            previous=sqlite3.connect(self.durable);previous.backup(self.db);previous.close()
        self.db.executescript('''CREATE TABLE IF NOT EXISTS tasks(key TEXT PRIMARY KEY,signature TEXT,row_json TEXT,priority INTEGER,status TEXT,reason TEXT,label TEXT,source_read INTEGER,active INTEGER,updated TEXT);
        CREATE TABLE IF NOT EXISTS http_cache(url TEXT PRIMARY KEY,body BLOB,status INTEGER,expires REAL);
        CREATE TABLE IF NOT EXISTS history(at TEXT,key TEXT,status TEXT,reason TEXT,signature TEXT);
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);''')
        if 'research_attempts'not in {r[1]for r in self.db.execute('PRAGMA table_info(tasks)')}:
            self.db.execute('ALTER TABLE tasks ADD COLUMN research_attempts INTEGER NOT NULL DEFAULT 0')
        self.manual=manual;self.manual_refs={(r['paper_id'],r['benchmark_id'])for e in manual['entities']for r in e.get('source_refs',[])}
        self.sources=Sources(project);self.primary=PrimaryCache(self.db,project)

    def persist(self):
        if not self.work_db:return
        self.db.commit();temp=self.durable.with_suffix('.checkpoint.sqlite')
        target=sqlite3.connect(temp)
        try:self.db.backup(target)
        finally:target.close()
        with temp.open('r+b')as f:os.fsync(f.fileno())
        os.replace(temp,self.durable)

    def ingest(self,source,publication):
        import ijson
        h=hashlib.sha256()
        with source.open('rb')as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
        if h.hexdigest()!=publication['source_sha256']:raise ValueError('Input publication/source mismatch')
        with gzip.open(source,'rb')as f:sid=next(ijson.items(f,'snapshot_id'),None)
        if sid!=publication['snapshot_id']:raise ValueError('Input snapshot ID mismatch')
        self.db.execute('UPDATE tasks SET active=0')
        end=datetime.fromisoformat(publication['generated_at'].replace('Z','+00:00')).astimezone(BJ).date()
        start=end-timedelta(days=7)
        with gzip.open(source,'rb')as f:
            for row in ijson.items(f,'benchmarks.item',use_float=True):
                if not row.get('paper_id')or not row.get('benchmark_id'):continue
                value=source_projection(row);value['evidence_quote']=row.get('evidence_quote','')
                key=digest([row['paper_id'],row['benchmark_id']]);signature=digest([source_signature(row),self.sources.stamp(row['paper_id']),POLICY])
                day=str(row.get('paper_first_published',''))[:10]
                priority=0 if start.isoformat()<=day<end.isoformat() and row.get('date_basis')in {'PAPER_V1_PROXY','FIRST_DISCLOSURE','EXPLICIT_RELEASE'} else 1
                self.db.execute('''INSERT INTO tasks(key,signature,row_json,priority,status,reason,label,source_read,active,updated) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET
                    row_json=excluded.row_json,priority=excluded.priority,active=1,
                    status=CASE WHEN tasks.signature=excluded.signature THEN tasks.status ELSE 'PENDING' END,
                    reason=CASE WHEN tasks.signature=excluded.signature THEN tasks.reason ELSE '' END,
                    research_attempts=CASE WHEN tasks.signature=excluded.signature THEN tasks.research_attempts ELSE 0 END,
                    label=CASE WHEN tasks.signature=excluded.signature THEN tasks.label ELSE NULL END,
                    source_read=CASE WHEN tasks.signature=excluded.signature THEN tasks.source_read ELSE 0 END,
                    signature=excluded.signature''',(key,signature,json.dumps(value,ensure_ascii=False),priority,'PENDING','',None,0,1,now()))
        self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('publication',json.dumps(publication)));self.db.commit();self.persist()

    def check(self,task,research=False):
        row=json.loads(task['row_json']);pair=row['paper_id'],row['benchmark_id']
        if pair in self.manual_refs:return 'MANUAL_PRESERVED','EXISTING_REVIEWED_REGISTRY',None,0
        context,error=self.sources.get(row['paper_id'])
        if error:return 'SOURCE_BLOCKED',error,None,0
        b,error=select_benchmark(row,context)
        if error:return 'IDENTITY_BLOCKED',error,None,1
        old=audited_old(row,b,context)
        if old:return 'VERIFIED_PUBLIC_BOUND','AUDITED_HISTORICAL_FACT_AND_CURRENT_SOURCE_REVALIDATED',old,1
        record=base_record(row,b,context)
        records=[b,*b.get('evidence',[])];dates=[r for r in records if r.get('date_basis')=='EXPLICIT_RELEASE' and r.get('release_date') and r.get('date_quote')]
        for d in dates:
            q=d['date_quote'];day=d['release_date']
            if len(q)>=12 and norm(q)in context['normalized_text'] and norm(row['benchmark_name'])in norm(q) and day in q:
                record['events'].append({'kind':'PUBLIC_ANNOUNCEMENT','date':day,'author_date_claim':day,'timezone':'UNSPECIFIED',
                    'publication_verified':True,'proves_public_existence':True,'evidence':proof(record['identity_evidence']['url'],q)})
        if record['events']:return 'SOURCE_DATE_CLAIM','EXPLICIT_SOURCE_DAY_TIMEZONE_OR_FIRSTNESS_PENDING',record,1
        if b.get('novelty')=='NEW' and b.get('tests_llms')is True and repos_for(row,b,context):
            if research:
                label,status,reason=official_events(row,b,context,self.primary);return status,reason,label,1
            return 'RESEARCH_PENDING','OFFICIAL_PRIMARY_RELEASE_CHECK_REQUIRED',record,1
        record['source_novelty']=b.get('novelty');record['review_notes']='原文及新旧判断已核对；日期尚缺可验证首发公告或历史公开记录。不能把本次论文日期当首发。'
        return 'NEEDS_PRIMARY_DATE','NO_VERIFIABLE_FIRST_PUBLIC_EVENT_IN_CAPTURED_SOURCE',record,1

    def export(self):
        self.persist()
        groups={};counts=Counter();source_read=0;quote_checks=0
        for task in self.db.execute('SELECT * FROM tasks WHERE active=1'):
            counts[task['status']]+=1;source_read+=task['source_read']
            if not task['label']:continue
            quote_checks+=task['source_read']
            record=json.loads(task['label']);eid=record['entity_id']
            if eid not in groups:groups[eid]=record
            else:
                groups[eid]['source_refs'].extend(record['source_refs']);groups[eid]['source_checks'].extend(record.get('source_checks',[]))
                known={digest(e)for e in groups[eid]['events']}
                groups[eid]['events'].extend(e for e in record['events']if digest(e)not in known)
        registry={'version':1,'entities':sorted(groups.values(),key=lambda r:r['entity_id'])}
        validate_registry(registry)
        pub=json.loads(self.db.execute('SELECT value FROM meta WHERE key=?',('publication',)).fetchone()[0])
        progress={'policy':POLICY,'snapshot_id':pub['snapshot_id'],'source_sha256':pub['source_sha256'],'updated_at':now(),
            'source_records':sum(counts.values()),'states':dict(counts),'source_artifact_checks_completed':source_read,
            'source_quote_checks_completed':quote_checks,
            'exact_first_day_records':counts['VERIFIED_FIRST_DAY'],'public_bound_records':counts['VERIFIED_PUBLIC_BOUND'],
            'unread_source_records':counts['SOURCE_BLOCKED'],'pending_source_pass':counts['PENDING'],
            'pending_primary_research':counts['RESEARCH_PENDING'],'source_pass_complete':not counts['PENDING'],
            'all_first_dates_resolved':counts['VERIFIED_FIRST_DAY']==sum(counts.values()),
            'notice':'源文核对、时间上界和精确首发日分别计数；检查完一轮不等于全部日期已核实。'}
        envelope={'format':'automatic-date-registry-v1','policy':POLICY,'source_snapshot_id':pub['snapshot_id'],
            'source_sha256':pub['source_sha256'],'registry':registry,'progress':progress}
        atomic(self.state/'registry.json',envelope);atomic(self.state/'progress.json',progress)
        return progress

    def checkpoint(self):
        self.persist()
        counts={r[0]:r[1]for r in self.db.execute('SELECT status,COUNT(*)FROM tasks WHERE active=1 GROUP BY status')}
        value={'policy':POLICY,'updated_at':now(),'states':counts,'source_records':sum(counts.values()),
            'source_artifact_checks_completed':self.db.execute('SELECT COALESCE(SUM(source_read),0)FROM tasks WHERE active=1').fetchone()[0],
            'source_quote_checks_completed':self.db.execute('SELECT COALESCE(SUM(source_read),0)FROM tasks WHERE active=1 AND label IS NOT NULL').fetchone()[0],
            'source_pass_complete':not counts.get('PENDING'),'notice':'检查点；待核项不计已核实首发日期。'}
        atomic(self.state/'progress.json',value);return value

    def run(self,*,research=False,limit=0,workers=8,priority=None):
        statuses=('RESEARCH_PENDING',) if research else ('PENDING',)
        marks=','.join('?'for _ in statuses)
        retry_cutoff=(datetime.now(UTC)-timedelta(hours=1)).isoformat()
        clause='status IN ('+marks+')'
        params=list(statuses)
        if research:
            clause+=' OR (status=\'FETCH_BLOCKED\' AND research_attempts<3 AND updated<?)';params.append(retry_cutoff)
        if priority is not None:clause='('+clause+') AND priority=?';params.append(priority)
        tasks=self.db.execute('SELECT * FROM tasks WHERE active=1 AND ('+clause+') ORDER BY priority,json_extract(row_json,\'$.paper_id\'),key',params).fetchall()
        if limit:tasks=tasks[:limit]
        if not research:
            groups=defaultdict(list)
            for task in tasks:groups[json.loads(task['row_json'])['paper_id']].append(task)
            def check_paper(group):
                result=[]
                for task in group:
                    try:outcome=self.check(task)
                    except Exception as e:outcome=('SOURCE_BLOCKED',type(e).__name__+':'+str(e)[:180],None,0)
                    result.append((task,outcome))
                return result
            done=0;papers=list(groups.values())
            with ThreadPoolExecutor(max_workers=max(1,min(workers,16)))as pool:
                for offset in range(0,len(papers),32):
                    for checked in pool.map(check_paper,papers[offset:offset+32]):
                        for task,(status,reason,label,read)in checked:
                            self.db.execute('UPDATE tasks SET status=?,reason=?,label=?,source_read=?,updated=? WHERE key=?',
                                (status,reason,json.dumps(label,ensure_ascii=False)if label else None,read,now(),task['key']))
                            self.db.execute('INSERT INTO history VALUES(?,?,?,?,?)',(now(),task['key'],status,reason,task['signature']))
                            done+=1
                        interval=512 if self.work_db else 64
                        if done//interval!=(done-len(checked))//interval:self.db.commit();print(json.dumps(self.checkpoint(),ensure_ascii=False),flush=True)
                    self.db.commit()
                    if offset%512==0:self.export()
            return self.export()
        done=0
        for selected in tasks:
            if limit and done>=limit:break
            task=self.db.execute('SELECT * FROM tasks WHERE key=?',(selected['key'],)).fetchone()
            try:status,reason,label,read=self.check(task,research=research)
            except Exception as e:status,reason,label,read='SOURCE_BLOCKED',type(e).__name__+':'+str(e)[:180],None,0
            self.db.execute('UPDATE tasks SET status=?,reason=?,label=?,source_read=?,updated=? WHERE key=?',
                (status,reason,json.dumps(label,ensure_ascii=False)if label else None,read,now(),task['key']))
            self.db.execute('INSERT INTO history VALUES(?,?,?,?,?)',(now(),task['key'],status,reason,task['signature']))
            if research:self.db.execute('UPDATE tasks SET research_attempts=research_attempts+1 WHERE key=?',(task['key'],))
            done+=1
            if research:self.db.commit();self.export()
            if done%64==0:self.db.commit();print(json.dumps(self.checkpoint(),ensure_ascii=False),flush=True)
            if done%1024==0:self.export()
        self.db.commit();return self.export()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--project',type=Path,required=True);p.add_argument('--state',type=Path,required=True)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--publication',type=Path,required=True);p.add_argument('--manual',type=Path,required=True)
    p.add_argument('--research',action='store_true');p.add_argument('--limit',type=int,default=0)
    p.add_argument('--workers',type=int,default=8)
    a=p.parse_args();r=Reviewer(a.project,a.state,json.loads(a.manual.read_text(encoding='utf-8')))
    r.ingest(a.source,json.loads(a.publication.read_text(encoding='utf-8')));print(json.dumps(r.run(research=a.research,limit=a.limit,workers=a.workers),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
