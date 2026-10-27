/* Frozen, same-origin source data only. No server jobs or external model calls. */
(function(){
  'use strict';
  const originalFetch=window.fetch.bind(window),base=new URL('./',document.currentScript.src);
  let manifestPromise,workspacePromise;
  const embedded=document.getElementById?.('snapshot-bootstrap');
  const bootstrap=embedded?JSON.parse(embedded.textContent):null;
  if(bootstrap)window.RadarHomeSnapshot=bootstrap.snapshot;
  window.RadarSnapshotMode=true;
  const json=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json; charset=utf-8'}});
  const safePath=path=>typeof path==='string'&&/^snapshot\/[a-zA-Z0-9._/-]+$/.test(path)&&!path.split('/').includes('..');
  const abort=signal=>{if(signal?.aborted)throw signal.reason||new DOMException('Aborted','AbortError');};
  async function bytes(path,signal){
    if(!safePath(path))throw Error('INVALID_SNAPSHOT_PATH');
    const response=await originalFetch(new URL(path,base),{signal,cache:['snapshot/manifest.json','snapshot/current.json'].includes(path)?'no-store':'force-cache'});
    if(!response.ok)throw Object.assign(Error('SNAPSHOT_ASSET_UNAVAILABLE'),{status:response.status});
    return new Uint8Array(await response.arrayBuffer());
  }
  async function manifest(){
    return manifestPromise||(manifestPromise=(async()=>{
      const data=bootstrap?.manifest||JSON.parse(new TextDecoder().decode(await bytes('snapshot/current.json')));
      if(data.format!=='radar-static-snapshot-v1'||!Array.isArray(data.parts)||!data.parts.every(p=>safePath(p.path)))throw Error('INVALID_SNAPSHOT_MANIFEST');
      return data;
    })().catch(e=>{manifestPromise=null;throw e;}));
  }
  async function gunzip(data){
    if(typeof DecompressionStream!=='function')throw Error('SNAPSHOT_BROWSER_UNSUPPORTED');
    return new Uint8Array(await new Response(new Blob([data]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer());
  }
  async function loadWorkspace(){
    if(workspacePromise)return workspacePromise;
    workspacePromise=(async()=>{
      const m=await manifest(),parts=new Array(m.parts.length);let cursor=0;
      async function worker(){while(cursor<m.parts.length){const i=cursor++;parts[i]=await bytes(m.parts[i].path);if(parts[i].length!==m.parts[i].bytes)throw Error('SNAPSHOT_PART_LENGTH');}}
      await Promise.all(Array.from({length:Math.min(3,m.parts.length)},worker));
      const joined=new Uint8Array(parts.reduce((n,p)=>n+p.length,0));let offset=0;
      for(const p of parts){joined.set(p,offset);offset+=p.length;}
      const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',joined)),b=>b.toString(16).padStart(2,'0')).join('');
      if(hash!==m.workspace_sha256)throw Error('SNAPSHOT_INTEGRITY_FAILURE');
      return gunzip(joined);
    })().catch(e=>{workspacePromise=null;throw e;});
    return workspacePromise;
  }
  let decodedPromise;
  window.RadarLoadWorkspace=function({signal,onProgress}={}){
    if(decodedPromise)return decodedPromise;
    decodedPromise=(async()=>{
      const m=await manifest();abort(signal);
      if(typeof Worker!=='function')return JSON.parse(new TextDecoder().decode(await loadWorkspace()));
      return new Promise((resolve,reject)=>{
        const worker=new Worker(new URL('snapshot-worker.js',base));
        const finish=(error,data)=>{signal?.removeEventListener('abort',cancel);worker.terminate();error?reject(error):resolve(data);};
        const cancel=()=>finish(signal.reason||new DOMException('Aborted','AbortError'));
        worker.onmessage=event=>{const message=event.data;if(message.type==='progress')onProgress?.(message.text);else if(message.type==='ready')finish(null,message.snapshot);else finish(Error(message.error||'SNAPSHOT_DECODE_FAILED'));};
        worker.onerror=()=>finish(Error('SNAPSHOT_WORKER_FAILED'));
        signal?.addEventListener('abort',cancel,{once:true});
        if(signal?.aborted){cancel();return;}
        worker.postMessage({manifest:m,base:base.href});
      });
    })().catch(error=>{decodedPromise=null;throw error;});
    return decodedPromise;
  };
  window.fetch=async function(input,init={}){
    const url=new URL(typeof input==='string'||input instanceof URL?input:input.url,location.href);
    const route=url.origin===base.origin&&url.pathname.startsWith(base.pathname)?'/'+url.pathname.slice(base.pathname.length):'';
    if(!route.startsWith('/api/'))return originalFetch(input,init);
    const method=(init.method||(input instanceof Request?input.method:'GET')).toUpperCase();
    if(!['GET','HEAD'].includes(method))return json({error:'SNAPSHOT_READ_ONLY'},403);
    abort(init.signal);
    let data;
    if(route==='/api/workspace'||route==='/api/snapshot')data=await loadWorkspace();
    else if(route==='/api/overview')data=await gunzip(await bytes((await manifest()).overview,init.signal));
    else if(route==='/api/benchmark'){
      if([...url.searchParams.keys()].some(k=>!['paper_id','benchmark_id'].includes(k))||['paper_id','benchmark_id'].some(k=>url.searchParams.getAll(k).length!==1))return json({error:'invalid_benchmark_identity'},400);
      const key=JSON.stringify([url.searchParams.get('paper_id'),url.searchParams.get('benchmark_id')]);
      const m=await manifest();
      const digest=m.details_root?Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(key))),b=>b.toString(16).padStart(2,'0')).join('').slice(0,32):null;
      const path=digest?m.details_root+digest+'.json.gz':m.details?.[key];
      if(!path)return json({error:'not_found'},404);
      try{data=await gunzip(await bytes(path,init.signal));}catch(error){if(error.status===404)return json({error:'not_found'},404);throw error;}
    }else return json({error:'SNAPSHOT_READ_ONLY'},404);
    abort(init.signal);
    return new Response(method==='HEAD'?null:data,{headers:{'Content-Type':'application/json; charset=utf-8','X-Radar-Mode':'frozen-snapshot'}});
  };
  function applyReadOnlyUI(){
    document.body.dataset.snapshotMode='true';
    const css=document.createElement('style');css.textContent='body[data-snapshot-mode] #view-tasks>:not(.snapshot-notice){display:none!important}.snapshot-notice{margin:20px 0;padding:24px;border:1px solid #dfE7f1;border-radius:16px;background:#fff;color:#33475d;line-height:1.9}.snapshot-notice h2{font-size:18px;margin:0 0 10px}.snapshot-notice p{margin:6px 0;font-size:14px}';document.head.append(css);
    const task=document.getElementById('visitor-task')?.closest('.visitor-composer');
    if(task){task.hidden=true;const info=document.createElement('article');info.className='visitor-composer snapshot-notice';const h=document.createElement('h2');h.textContent='评测数据快照';const p=document.createElement('p');p.textContent='浏览模型综合评分、评测原始成绩和论文来源。本版本数据固定，不进行实时采集或模型调用。';const asof=document.createElement('p');asof.id='snapshot-asof';info.append(h,p,asof);task.after(info);manifest().then(m=>{asof.textContent='快照截至 '+new Date(m.generated_at).toLocaleString('zh-CN',{hour12:false});}).catch(()=>{});}
    const hint=document.querySelector('.visitor-hero-links span');if(hint)hint.textContent='查看评测范围与原始来源。';
    const view=document.getElementById('view-tasks');if(view){const note=document.createElement('section');note.className='snapshot-notice';const h=document.createElement('h2');h.textContent='任务选型服务尚未接入';const p=document.createElement('p');p.textContent='当前为固定快照版本，可查看模型表现、评测目录和来源详情。任务需求分析及重新计算需要连接后端服务，本版本不提供这些操作。';note.append(h,p);view.append(note);}
    const refresh=document.getElementById('refresh');if(refresh){refresh.textContent='重新载入';refresh.title='重新读取同一份固定快照';}
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',applyReadOnlyUI,{once:true});else applyReadOnlyUI();
})();
