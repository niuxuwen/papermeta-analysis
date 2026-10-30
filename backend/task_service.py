"""Task-only gateway over an exact public snapshot; no extraction or admin routes."""
import argparse
from collections import OrderedDict,deque
from copy import deepcopy
import gzip,json,logging,os,re,sys,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError,URLError
from urllib.request import Request,build_opener,ProxyHandler,HTTPRedirectHandler
from urllib.parse import urlsplit,parse_qs
from task_snapshots import PublishedSnapshots,SnapshotUnavailable

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def allowed(method,path):
    if path in {'/api/task-service','/api/taxonomy','/api/task-measurements'}:return method=='GET'
    if path in {'/api/task-profile','/api/task-score','/api/interactive-jobs'}:return method=='POST'
    return bool(method in {'GET','DELETE'} and re.fullmatch(r'/api/interactive-jobs/[A-Za-z0-9_-]{43}',path))

def public_benchmark(b):
    return ((b.get('name_audit')or{}).get('status')!='REVIEW_REQUIRED'
        and str(b.get('benchmark_name')or'').strip()not in {'名称待核验','名称待核实','名称待确认'}
        and 'EXCLUDED'not in [b.get('eligibility'),b.get('status'),b.get('history_status'),(b.get('progress')or{}).get('paper_status')])

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--radar-root',type=Path,required=True)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--snapshot',type=Path)
    source.add_argument('--publication-url')
    parser.add_argument('--port',type=int,default=1894)
    parser.add_argument('--allow-origin',action='append',default=['https://niuxuwen.github.io','https://cowhors.com','https://www.cowhors.com'])
    parser.add_argument('--profile-calls-per-day',type=int,default=24)
    args=parser.parse_args();sys.path.insert(0,str(args.radar_root.resolve()))
    from recent_benchmarks.live_web import make_server
    from recent_benchmarks.catalog_task_scoring import prepare_inputs,score_task,VERSION as TASK_SCORE_VERSION
    from recent_benchmarks.task_labels import validate_profile
    from recent_benchmarks.interactive_profile import analyse_task,TaskProfileFailure
    from recent_benchmarks.taxonomy import TAXONOMY_VERSION
    from recent_benchmarks.task_measurements import projection
    service=SimpleNamespace(args=SimpleNamespace(llm_url=os.environ.get('RADAR_LLM_URL','https://aigateway.paperbypass.com/api/v1/chat/completions'),
        llm_model=os.environ.get('RADAR_LLM_MODEL','qwen/qwen3.8-flash'),llm_transport='requests',request_timeout=55,max_tokens=2200,json_mode='off'))
    profile_available=bool(os.environ.get('RADAR_API_KEY'))
    profile_calls=deque();lock=threading.Lock()
    def profile(description):
        with lock:
            now=time.time()
            while profile_calls and now-profile_calls[0]>=86400:profile_calls.popleft()
            if len(profile_calls)>=args.profile_calls_per_day:raise TaskProfileFailure('task_profile_rate_limited')
            profile_calls.append(now)
        return analyse_task(service,description)
    class Context:
        def __init__(self,data):
            self.snapshot={k:data[k]for k in ('snapshot_id','generated_at','window')}
            self.measurements=data['measurements'];self.index=data['index'];self.catalog=data['catalog']
            self.cache=OrderedDict();self.score_lock=threading.Lock()
            self.internal=make_server('127.0.0.1',0,lambda:self.snapshot,
                task_score_provider=self.score,task_profile_provider=profile if profile_available else None)
            threading.Thread(target=self.internal.serve_forever,daemon=True).start()
            self.url='http://127.0.0.1:'+str(self.internal.server_address[1])
        def score(self,task_profile,references,candidates=None):
            task_profile=validate_profile(task_profile)
            key=json.dumps([task_profile,sorted(candidates)if candidates is not None else None],sort_keys=True,ensure_ascii=False)
            with self.score_lock:
                if key in self.cache:self.cache.move_to_end(key);return deepcopy(self.cache[key])
                task=score_task(self.index,self.catalog,task_profile,min_benchmarks=1,candidate_models=candidates)
                result={**self.snapshot,'task_index':task};self.cache[key]=result
                while len(self.cache)>4:self.cache.popitem(last=False)
                return deepcopy(result)
        def busy(self):
            jobs=self.internal.interactive_jobs
            with jobs.lock:return any(j['state']in {'RUNNING','QUEUED'}for j in jobs.jobs.values())
        def close(self):self.internal.shutdown();self.internal.server_close()
    stopped=threading.Event();store=None
    if args.publication_url:
        store=PublishedSnapshots(args.publication_url,Context);store.refresh()
        def update():
            while not stopped.wait(45):store.refresh()
        threading.Thread(target=update,daemon=True).start()
        def context(sid=None):return store.get(sid)
    else:
        raw=args.snapshot.read_bytes();snapshot=json.loads(gzip.decompress(raw)if raw[:2]==b'\x1f\x8b'else raw)
        if not snapshot.get('snapshot_id')or not snapshot.get('observations'):raise ValueError('A real identified snapshot is required')
        source_index,source_catalog=prepare_inputs(snapshot['index'],[b for b in snapshot['benchmarks']if public_benchmark(b)],snapshot['observations'])
        fixed=Context({**snapshot,'index':source_index,'catalog':source_catalog,
                       'measurements':projection(source_index,source_catalog,snapshot['snapshot_id'])})
        def context(sid=None):
            if sid and sid!=fixed.snapshot['snapshot_id']:raise SnapshotUnavailable('task_snapshot_not_loaded')
            return fixed
    opener=build_opener(ProxyHandler({}),NoRedirect())
    requests=deque();request_lock=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        server_version='PaperMetaTask';sys_version=''
        def log_message(self,*args):pass
        def reply(self,status,data):
            body=data if isinstance(data,bytes)else json.dumps(data,ensure_ascii=False,allow_nan=False).encode()
            self.send_response(status)
            origin=self.headers.get('Origin')
            if origin in args.allow_origin:self.send_header('Access-Control-Allow-Origin',origin)
            self.send_header('Vary','Origin');self.send_header('Cache-Control','no-store')
            self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)))
            self.send_header('X-Content-Type-Options','nosniff');self.end_headers()
            try:self.wfile.write(body)
            except(BrokenPipeError,ConnectionResetError):pass
        def do_OPTIONS(self):
            if self.headers.get('Origin')not in args.allow_origin or not allowed(self.headers.get('Access-Control-Request-Method',''),urlsplit(self.path).path):return self.reply(403,{'error':'forbidden'})
            if any(h.strip().lower()not in {'content-type'}for h in self.headers.get('Access-Control-Request-Headers','').split(',')if h.strip()):return self.reply(403,{'error':'forbidden'})
            self.send_response(204);self.send_header('Access-Control-Allow-Origin',self.headers['Origin']);self.send_header('Vary','Origin')
            self.send_header('Access-Control-Allow-Methods','GET, POST, DELETE, OPTIONS');self.send_header('Access-Control-Allow-Headers','Content-Type');self.send_header('Access-Control-Max-Age','600');self.send_header('Content-Length','0');self.end_headers()
        def handle_request(self):
            if self.headers.get('Origin')and self.headers['Origin']not in args.allow_origin:return self.reply(403,{'error':'forbidden'})
            parts=urlsplit(self.path);query=parse_qs(parts.query,keep_blank_values=True);sid=query.get('snapshot_id',[None])[0]
            if (not allowed(self.command,parts.path)or set(query)-{'snapshot_id'}
                or sid is not None and (len(query['snapshot_id'])!=1 or not re.fullmatch('[a-f0-9]{24}',sid))):return self.reply(404,{'error':'not_found'})
            try:current=context(sid)
            except SnapshotUnavailable:
                if store:store.refresh(wait=True,min_interval=3)
                try:current=context(sid)
                except SnapshotUnavailable:return self.reply(503,{'error':'task_snapshot_not_loaded','retry_after_seconds':3})
            if parts.path=='/api/task-service':return self.reply(200,{'status':'READY',**current.snapshot,'taxonomy_version':TAXONOMY_VERSION,'task_score_method_version':TASK_SCORE_VERSION,'task_score_available':True,'task_profile_available':profile_available,'versioned_snapshots':True})
            if parts.path=='/api/task-measurements':return self.reply(200,current.measurements)
            body=None
            if self.command=='POST':
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if self.headers.get('Transfer-Encoding')or not 0<size<=65536:return self.reply(413,{'error':'request_too_large'})
                    if self.headers.get_content_type()!='application/json':return self.reply(415,{'error':'json_required'})
                    body=self.rfile.read(size);json.loads(body)
                except(ValueError,UnicodeError):return self.reply(400,{'error':'invalid_request'})
                with request_lock:
                    now=time.monotonic()
                    while requests and now-requests[0]>60:requests.popleft()
                    if len(requests)>=30:return self.reply(429,{'error':'task_service_busy'})
                    requests.append(now)
            try:
                request=Request(current.url+parts.path,data=body,method=self.command,headers={'Content-Type':'application/json','Accept-Encoding':'identity'})
                with opener.open(request,timeout=75)as response:
                    value=response.read(40*1024*1024+1)
                    if len(value)>40*1024*1024:return self.reply(502,{'error':'response_too_large'})
                    self.reply(response.status,value)
            except HTTPError as exc:self.reply(exc.code,exc.read(1048576))
            except(URLError,TimeoutError):self.reply(503,{'error':'task_service_unavailable'})
        do_GET=handle_request;do_POST=handle_request;do_DELETE=handle_request
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler);server.daemon_threads=True
    logging.getLogger().setLevel(logging.CRITICAL)
    print(json.dumps({'status':'LISTENING','port':args.port,'publication_mode':bool(store),'task_profile_available':profile_available,'model':service.args.llm_model,'startup_model_calls':0}),flush=True)
    try:server.serve_forever()
    finally:
        stopped.set();server.server_close()
        if store:store.close()
        else:fixed.close()

if __name__=='__main__':main()
