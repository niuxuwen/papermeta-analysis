"""Actual dated arXiv announcements and first-introduction adjudication.

Submission timestamps never select a release day. A first-public decision also
needs a v1 author benchmark-introduction claim, no captured prior publication,
and a successful primary arXiv prior-name search containing the current paper.
Linked-project or venue uncertainty remains pending for a separate review.
"""
from datetime import datetime,timezone,timedelta
from html.parser import HTMLParser
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlencode

POLICY='author-v1-actual-announcement-prior-search-v1'


class Announcements(HTMLParser):
    def __init__(self):
        super().__init__();self.h3=False;self.header='';self.day=None;self.entries={}
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='h3':self.h3=True;self.header=''
        if tag=='a'and self.day:
            m=re.fullmatch(r'/abs/(\d{4}\.\d{4,5})(?:v\d+)?',a.get('href',''))
            if m:self.entries[m[1]]={'date':self.day,'heading':self.header}
    def handle_data(self,text):
        if self.h3:self.header+=text
    def handle_endtag(self,tag):
        if tag!='h3':return
        self.h3=False;m=re.search(r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),\s*(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})',self.header)
        self.day=datetime.strptime(m[1],'%d %b %Y').date().isoformat()if m else None


def primary_category(paper):
    xml=paper.get('source_metadata',{}).get('raw_entry_xml','')
    if xml:
        root=ET.fromstring(xml)
        for e in root.iter():
            if e.tag.endswith('primary_category'):return e.attrib.get('term')
    return None


def introduction(text,name):
    # The introduced object must itself be a benchmark; methods evaluated on a
    # benchmark and component names do not satisfy this independent check.
    pattern=r'\b(?:we|here we|this paper)\s+(?:introduce|present|propose|release|construct|build)\s+(?:a\s+)?'+re.escape(name)+r'(?![\w-])[^.!?\n]{0,210}'
    for m in re.finditer(pattern,text,re.I):
        clause=m.group(0);description=clause[len(clause.split(name,1)[0])+len(name):]if name in clause else clause
        if not re.search(r'\bbenchmark\b|evaluation suite|evaluation dataset|test suite',description,re.I):continue
        if re.search(r'\b(?:method|model|algorithm|framework)\b',description,re.I):continue
        return clause
    return None


def prior_search_url(name):
    return 'https://export.arxiv.org/api/query?'+urlencode({'search_query':'all:"'+name+'"','start':0,'max_results':100,'sortBy':'submittedDate','sortOrder':'ascending'})


def prior_search_clear(raw,current_id):
    root=ET.fromstring(raw);ns={'a':'http://www.w3.org/2005/Atom'};ids=set()
    for e in root.findall('a:entry',ns):
        value=e.findtext('a:id',default='',namespaces=ns);m=re.search(r'(\d{4}\.\d{4,5})(?:v\d+)?$',value)
        if m:ids.add(m[1])
    if current_id not in ids:return False,'CURRENT_V1_NOT_PRESENT_IN_PRIOR_SEARCH'
    if ids!={current_id}:return False,'OTHER_PAPERS_WITH_SAME_NAME_REQUIRE_IDENTITY_REVIEW'
    return True,None


def run(reviewer,limit=128):
    from automatic_date_review import now,proof,base_record,select_benchmark,source_signature,repos_for,norm
    from recent_benchmarks.automatic_date_policy import catalog
    from recent_benchmarks.release_ledger import digest
    db=reviewer.db
    db.execute('''CREATE TABLE IF NOT EXISTS firstness_checks(key TEXT PRIMARY KEY,signature TEXT,status TEXT,reason TEXT,updated TEXT,attempts INTEGER DEFAULT 0)''')
    db.execute('''CREATE TABLE IF NOT EXISTS arxiv_announcements(paper TEXT,category TEXT,day TEXT,receipt TEXT,PRIMARY KEY(paper,category))''')
    manual={(ref['paper_id'],ref['benchmark_id']):e['decision']for e in reviewer.manual['entities']for ref in e.get('source_refs',[])}
    tasks=[];contexts={};categories=set()
    cutoff=(datetime.now(timezone.utc)-timedelta(days=18)).isoformat()[:10]
    rows=db.execute("SELECT * FROM tasks WHERE active=1 AND json_extract(row_json,'$.paper_first_published')>=? ORDER BY priority,key",(cutoff,)).fetchall()
    for task in rows:
        row=json.loads(task['row_json']);pair=row['paper_id'],row['benchmark_id']
        if pair in manual and manual[pair]!='PENDING':continue
        context,error=reviewer.sources.get(row['paper_id'])
        if error:continue
        b,error=select_benchmark(row,context)
        if error or b.get('novelty')!='NEW' or b.get('tests_llms')is not True:continue
        paper=context['raw']['paper'];category=primary_category(paper)
        if not category or not re.fullmatch(r'[A-Za-z-]+(?:\.[A-Za-z-]+)?',category):continue
        claim=introduction(paper.get('abstract_text',''),row['benchmark_name'])
        if not claim:continue
        contexts[task['key']]=(row,b,context,claim,category);tasks.append(task);categories.add(category)
        if len(tasks)>=max(128,limit*2):break
    for category in sorted(categories):
        url='https://arxiv.org/list/'+category+'/pastweek?show=2000'
        try:
            raw=reviewer.primary.get(url);html=raw.decode('utf-8');parser=Announcements()
            if 'Authors and titles for recent submissions'not in html:continue
            parser.feed(html)
            for paper,entry in parser.entries.items():
                receipt={**entry,'url':url,'sha256':hashlib.sha256(raw).hexdigest(),'retrieved_at':now()}
                old=db.execute('SELECT day FROM arxiv_announcements WHERE paper=?AND category=?',(paper,category)).fetchone()
                if old and old[0]!=entry['date']:continue
                db.execute('INSERT OR REPLACE INTO arxiv_announcements VALUES(?,?,?,?)',(paper,category,entry['date'],json.dumps(receipt)))
            db.commit()
        except Exception as e:
            db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('announcement_error:'+category,type(e).__name__));db.commit()
    done=0
    known_names={norm(a)for f in catalog()[0]['facts']for a in f['aliases']}
    for task in tasks:
        if done>=limit:break
        row,b,context,claim,category=contexts[task['key']];paper=context['raw']['paper'];pid=paper.get('arxiv_id')
        found=db.execute('SELECT receipt FROM arxiv_announcements WHERE paper=?AND category=?',(pid,category)).fetchone()
        if not found:continue
        receipt=json.loads(found[0]);signature=digest([POLICY,task['signature'],receipt['date']])
        previous=db.execute('SELECT * FROM firstness_checks WHERE key=?',(task['key'],)).fetchone()
        if previous and previous['signature']==signature:
            age=datetime.now(timezone.utc)-datetime.fromisoformat(previous['updated'])
            if previous['status']=='VERIFIED_FIRST_DAY':
                if age<timedelta(days=1):continue
            elif previous['status']!='FETCH_BLOCKED' or previous['attempts']>=3 or age<timedelta(hours=1):continue
        status='FIRSTNESS_REVIEW_REQUIRED';reason=None;record=base_record(row,b,context)
        eventproof=proof(receipt['url'],receipt['heading']+' […] arXiv:'+pid,'ACTUAL_PRIMARY_CATEGORY_DATED_ANNOUNCEMENT')
        eventproof.update(source_sha256=receipt['sha256'],date_heading=receipt['heading'],listed_arxiv_id=pid)
        record['events'].append({'kind':'KNOWN_PUBLIC_EXISTENCE','date':receipt['date'],'timezone':'Asia/Shanghai',
            'publication_verified':True,'proves_public_existence':True,'evidence':eventproof})
        xml=paper.get('source_metadata',{}).get('raw_entry_xml','')
        if paper.get('metadata_verification')!='V1_DECLARED':reason='SOURCE_VERSION_NOT_PINNED_V1'
        elif norm(row['benchmark_name'])in known_names:reason='AUDITED_EXISTING_IDENTITY_REQUIRES_RECONCILIATION'
        elif paper.get('doi')or re.search(r'journal_ref|journal.reference|Published in|Accepted (?:by|to|at)',xml,re.I):reason='PRIOR_VENUE_OR_DOI_REQUIRES_EARLIER_PUBLICATION_CHECK'
        elif (b.get('history')or{}).get('papers'):reason='CAPTURED_PRIOR_PAPER_REQUIRES_RECONCILIATION'
        elif repos_for(row,b,context):reason='LINKED_PROJECT_RELEASE_REQUIRES_PRIOR_DATE_RECONCILIATION'
        else:
            url=prior_search_url(row['benchmark_name'])
            try:
                raw=reviewer.primary.get(url);clear,reason=prior_search_clear(raw,pid)
                if reason=='CURRENT_V1_NOT_PRESENT_IN_PRIOR_SEARCH':status='FETCH_BLOCKED'
                if clear:
                    record.update(entity_id='auto-paper-first-'+digest([pid,norm(row['benchmark_name'])])[:24],
                        decision='CONFIRMED_NEW',firstness_evidence=proof(paper['url'],claim,'AUTHOR_NEW_BENCHMARK_CLAIM_AND_PRIMARY_PRIOR_NAME_SEARCH'),
                        prior_search={'url':url,'sha256':hashlib.sha256(raw).hexdigest(),'scope':'arXiv exact-name scholarly metadata; current paper present and no other paper match','checked_at':now()})
                    record['events'][0].update(kind='FIRST_PUBLIC_INTRODUCTION',date_basis='PAPER_FIRST_PUBLICATION_WITH_NEW_CLAIM')
                    status='VERIFIED_FIRST_DAY';reason='AUTHOR_V1_NEW_BENCHMARK_CLAIM_ACTUAL_ANNOUNCEMENT_AND_PRIOR_SEARCH'
            except Exception as e:status='FETCH_BLOCKED';reason='PRIOR_SEARCH_'+type(e).__name__
        # Preserve any already captured earlier public event. The ledger's
        # chronology guard rejects a first day later than known public evidence.
        if task['label']:
            old=json.loads(task['label']);record['events'].extend(old.get('events',[]))
        record['review_notes']='已补官方实际公告日；不是提交日代理。首发还检查v1新benchmark声明、既有身份、历史论文、正式出版及项目来源；有未决线索保留待核。'+str(reason or'')
        if status=='FIRSTNESS_REVIEW_REQUIRED':status='VERIFIED_PUBLIC_BOUND'
        db.execute('UPDATE tasks SET status=?,reason=?,label=?,source_read=1,updated=? WHERE key=?',(status,reason,json.dumps(record,ensure_ascii=False),now(),task['key']))
        attempts=previous['attempts']+1 if previous and previous['signature']==signature else 1
        db.execute('INSERT OR REPLACE INTO firstness_checks VALUES(?,?,?,?,?,?)',(task['key'],signature,status,reason,now(),attempts))
        db.execute('INSERT INTO history VALUES(?,?,?,?,?)',(now(),task['key'],status,reason,task['signature']));db.commit();done+=1
        if done%8==0:reviewer.export()
    db.commit();reviewer.export();return {'candidates':len(tasks),'adjudicated':done}
