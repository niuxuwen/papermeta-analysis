'use strict';
let engine;
async function initialize(meta) {
  const base = '/task-runtime/0.27.7/';
  importScripts(base+'pyodide.js');
  const runtime = await loadPyodide({indexURL:base});
  const [library, inputs] = await Promise.all([fetch('/task-engine.zip'), fetch('/'+meta.task_inputs.path)]);
  if (!library.ok || !inputs.ok) throw Error('Cannot load task data');
  runtime.unpackArchive(await library.arrayBuffer(),'zip');
  const packed = await inputs.arrayBuffer();
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',packed)),x=>x.toString(16).padStart(2,'0')).join('');
  if (digest !== meta.task_inputs.sha256 || packed.byteLength !== meta.task_inputs.bytes) throw Error('Task input integrity failure');
  runtime.FS.writeFile('/inputs.gz',new Uint8Array(packed));
  runtime.globals.set('expected_id',meta.snapshot_id);
  runtime.runPython(`
import json,gzip,sys
sys.path.insert(0,'.')
from task_engine.catalog_task_scoring import score_task
with gzip.open('/inputs.gz','rt',encoding='utf8') as stream:
    data=json.load(stream)
assert data['snapshot_id']==expected_id
def score(payload):
    result=score_task(data['index'],data['catalog'],payload['profile'],min_benchmarks=1,
        candidate_models=payload.get('candidate_models'),as_of=data['window'].get('end') or data['generated_at'])
    return json.dumps({**{k:data[k] for k in ('window','generated_at','snapshot_id')},'task_index':result},allow_nan=False)
`);
  runtime.FS.unlink('/inputs.gz');
  return runtime;
}
onmessage=async({data:{meta,payload}})=>{
  try {
    engine=engine||await initialize(meta);
    engine.globals.set('payload_json',JSON.stringify(payload));
    postMessage({state:'COMPLETE',result:JSON.parse(engine.runPython('score(json.loads(payload_json))'))});
  } catch(error) { console.error('Task scoring:',error.message); postMessage({state:'FAILED',error:'task_score_failed'}); }
};
