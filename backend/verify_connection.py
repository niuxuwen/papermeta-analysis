"""Exercise the real HTTPS task service, CORS boundary, jobs and score data."""
import json,sys,time,uuid,urllib.request,urllib.error
from pathlib import Path
site=Path(__file__).resolve().parents[1]/'site'
config=json.loads((site/'task-backend.json').read_text(encoding='utf-8'));base=config['base_url']
origin='https://niuxuwen.github.io'
def call(path,method='GET',payload=None,headers=None):
    data=json.dumps(payload,ensure_ascii=False).encode()if payload is not None else None
    request=urllib.request.Request(base+path,data=data,method=method,headers={'Origin':origin,'Content-Type':'application/json',**(headers or {})})
    try:
        with urllib.request.urlopen(request,timeout=30)as r:return r.status,r.headers,json.load(r)if r.status!=204 else None
    except urllib.error.HTTPError as e:return e.code,e.headers,json.load(e)
code,headers,meta=call('api/task-service');assert code==200
manifest=json.loads((site/'snapshot/manifest.json').read_text(encoding='utf-8'))
assert meta['snapshot_id']==manifest['snapshot_id'];assert headers.get('Access-Control-Allow-Origin')==origin
for path in ['admin/','api/status','api/snapshot','api/workspace','api/config','api/interactive-jobs/not-a-valid-capability']:
    code,_,_=call(path);assert code==404,(path,code)
code,_,_=call('api/task-service',headers={'Origin':'https://unrelated.example'});assert code==403
code,h,_=call('api/interactive-jobs','OPTIONS',headers={'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type'});assert code==204 and h['Access-Control-Allow-Origin']==origin
code,_,tax=call('api/taxonomy');assert code==200 and tax['task_profile_available']
def run(kind,payload):
    start=time.monotonic();code,_,job=call('api/interactive-jobs','POST',{'kind':kind,'payload':payload,'request_id':str(uuid.uuid4())});assert code in(200,202),(code,job)
    for _ in range(70):
        if job['state']=='COMPLETE':return job['result'],round(time.monotonic()-start,2)
        assert job['state']not in('FAILED','CANCELLED'),job.get('error')
        time.sleep(.5);code,_,job=call('api/interactive-jobs/'+job['id']);assert code==200
    raise TimeoutError('Interactive job did not complete')
profile,profile_seconds=run('profile',{'description':'阅读医学研究论文，对比实验设计、主要结论和局限，并引用对应文献。'})
assert profile['profile']['domains']==['medicine'];assert sum(c['weight']for c in profile['profile']['capabilities'])>0.99
scored,score_seconds=run('score',{'profile':profile['profile'],'reference_models':[]})
assert scored['snapshot_id']==manifest['snapshot_id'];report=scored['task_index'];assert report['available']and report['models']
result={'base_url':base,'temporary':config.get('temporary',False),'snapshot_id':meta['snapshot_id'],'raw_observations':manifest['observations'],
    'cors':'PASS','private_routes_denied':'PASS','real_profile_analysis':'PASS','real_task_score':'PASS',
    'profile_seconds':profile_seconds,'score_seconds':score_seconds,'model_settings':len(report['models'])}
if len(sys.argv)>1:Path(sys.argv[1]).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
