"""Small, authorized real-provider counterexample retest; no private task data."""
import json,time,uuid,urllib.request
from pathlib import Path
ROOT=Path(__file__).parent
CASES=[
 ('image_text_output','分析输入图片，输出纯文本摘要。','image','any'),
 ('screenshot_output','阅读这张截图，结果仅文本输出。','image','any'),
 ('transcript','根据会议录音的逐字稿整理纪要，不需要处理音频。','any','any'),
 ('video_description','输入是视频的文字描述，不提供视频文件。','any','any'),
 ('browser','必须使用浏览器检索新闻并提供来源链接。','any','retrieval'),
 ('actual_audio','把录音先转成文字，再总结。','audio','any'),
 ('mixed_input','同时分析图片和音频输入，输出纯文本总结。','audio+image','any'),
]
def req(route,payload=None):
 r=urllib.request.Request('http://127.0.0.1:1895/api/'+route,data=json.dumps(payload,ensure_ascii=False).encode()if payload is not None else None,headers={'Origin':'https://cowhors.com','Content-Type':'application/json'})
 with urllib.request.urlopen(r,timeout=20)as f:return json.load(f)
h=req('task-service');report={'snapshot_id':h['snapshot_id'],'method':h['task_score_method_version'],'cases':{},'actual_provider_requests':0}
assert report['method']==12
for name,text,media,access in CASES:
 start=time.monotonic();report['actual_provider_requests']+=1
 try:
  j=req('interactive-jobs',{'kind':'profile','payload':{'description':text},'request_id':uuid.uuid4().hex})
  while time.monotonic()-start<100:
   d=req('interactive-jobs/'+j['id'])
   if d['state']=='COMPLETE':break
   if d['state']in {'FAILED','CANCELLED'}:raise RuntimeError(d.get('error',d['state']))
   time.sleep(.5)
  else:raise TimeoutError('bounded request timed out')
  p=d['result']['profile'];assert p['description']==text
  assert p['constraints']['modality']==media,p['constraints']
  assert p['constraints']['knowledge_access']==access,p['constraints']
  report['cases'][name]={'status':'PASS','profile':p}
 except Exception as e:report['cases'][name]={'status':'FAIL','error':str(e)}
 report['cases'][name]['seconds']=round(time.monotonic()-start,2)
 (ROOT/'task-v12-live-profiles.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(name,report['cases'][name]['status'],flush=True)
