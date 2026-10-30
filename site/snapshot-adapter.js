/* Verified, same-origin publications. No server jobs or external model calls. */
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
  let taskEvidencePromise;
  const sha256=async raw=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',raw)),b=>b.toString(16).padStart(2,'0')).join('');
  async function resilientPart(meta,{signal,onBytes=()=>{}}={}){
    for(let attempt=0;attempt<3;attempt++){
      abort(signal);const ctrl=new AbortController(),cancel=()=>ctrl.abort(signal.reason),timer=setTimeout(()=>ctrl.abort(),20000);
      signal?.addEventListener('abort',cancel,{once:true});
      try{
        const raw=await bytes(meta.path,ctrl.signal);
        if(raw.length!==meta.bytes||await sha256(raw)!==meta.sha256)throw Error('COMPARISON_INTEGRITY_FAILURE');
        onBytes(raw.length);return raw;
      }catch(error){
        abort(signal);
        const temporary=ctrl.signal.aborted||['AbortError','TimeoutError','TypeError'].includes(error.name)||[502,503,504].includes(error.status);
        if(!temporary||attempt===2)throw error;
      }finally{clearTimeout(timer);signal?.removeEventListener('abort',cancel);}
    }
  }
  let comparisonPromise;
  window.RadarLoadComparison=function({signal,onProgress=()=>{}}={}){
    return comparisonPromise||(comparisonPromise=(async()=>{
      const m=await manifest(),meta=m.comparisons;
      if(!meta||meta.snapshot_id!==m.snapshot_id)throw Error('COMPARISON_DATA_UNAVAILABLE');
      const index=JSON.parse(new TextDecoder().decode(await resilientPart(meta,{signal})));
      if(index.snapshot_id!==m.snapshot_id||!index.parts?.length||!index.parts.every(p=>safePath(p.path)))throw Error('COMPARISON_SNAPSHOT_MISMATCH');
      let cursor=0,received=0;const parts=new Array(index.parts.length);
      onProgress('正在读取共同测试来源…');
      async function download(){while(cursor<index.parts.length){const i=cursor++;parts[i]=await resilientPart(index.parts[i],{signal,onBytes:n=>{received+=n;onProgress(`正在读取共同测试来源 · ${Math.round(received/index.bytes*100)}%`);}});}}
      await Promise.all(Array.from({length:Math.min(4,index.parts.length)},download));abort(signal);
      const joined=new Uint8Array(index.bytes);let offset=0;for(const part of parts){joined.set(part,offset);offset+=part.length;}
      if(offset!==index.bytes||await sha256(joined)!==index.sha256)throw Error('COMPARISON_INTEGRITY_FAILURE');
      const data=JSON.parse(new TextDecoder().decode(await gunzip(joined)));
      if(data.snapshot_id!==m.snapshot_id||!Array.isArray(data.groups))throw Error('COMPARISON_SNAPSHOT_MISMATCH');
      const browse=await window.RadarLoadRanking({signal}),labels=new Map(data.labels.map(row=>[JSON.stringify([row.paper_id,row.benchmark_id]),row.labels]));
      return {...browse,comparison_loaded:true,index:{...browse.index,groups:data.groups},capability_annotations:data.annotations,
        benchmarks:browse.benchmarks.map(b=>({...b,enrichment:{labels:labels.get(JSON.stringify([b.paper_id,b.benchmark_id]))||{}}}))};
    })().catch(error=>{comparisonPromise=null;throw error;}));
  };
  let modelIndexPromise;const modelPromises=new Map();
  async function verifiedAsset(meta,signal){
    if(!meta||!safePath(meta.path))throw Error('INVALID_SNAPSHOT_PATH');
    const raw=await bytes(meta.path,signal),hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',raw)),b=>b.toString(16).padStart(2,'0')).join('');
    if(raw.length!==meta.bytes||hash!==meta.sha256)throw Error('MODEL_SOURCE_INTEGRITY_FAILURE');
    return JSON.parse(new TextDecoder().decode(await gunzip(raw)));
  }
  window.RadarLoadModel=function(name,{signal}={}){
    if(modelPromises.has(name))return modelPromises.get(name);
    const promise=(async()=>{
      const m=await manifest();
      if(!modelIndexPromise)modelIndexPromise=verifiedAsset(m.model_details,signal).catch(error=>{modelIndexPromise=null;throw error;});
      const index=await modelIndexPromise;
      if(index.snapshot_id!==m.snapshot_id||!Object.hasOwn(index.models,name))throw Error('MODEL_SOURCE_UNAVAILABLE');
      const data=await verifiedAsset(index.models[name],signal);
      if(data.snapshot_id!==m.snapshot_id||data.model_name!==name)throw Error('MODEL_SOURCE_SNAPSHOT_MISMATCH');
      return data;
    })().catch(error=>{modelPromises.delete(name);throw error;});
    modelPromises.set(name,promise);return promise;
  };
  let rankingPromise;
  let publicationCheck;
  window.RadarCheckPublication=function({signal}={}){
    return publicationCheck||(publicationCheck=(async()=>{
      const current=await manifest();
      const next=JSON.parse(new TextDecoder().decode(await bytes('snapshot/current.json',signal)));
      if(next.snapshot_id===current.snapshot_id)return null;
      if(next.format!=='radar-static-snapshot-v1'||!Array.isArray(next.parts)||!next.parts.every(p=>safePath(p.path))||
        !next.ranking||next.ranking.snapshot_id!==next.snapshot_id||!Number.isFinite(Date.parse(next.generated_at))||
        Date.parse(next.generated_at)<Date.parse(current.generated_at))throw Error('INVALID_PUBLICATION');
      const snapshot=await verifiedAsset(next.ranking,signal);
      if(snapshot.snapshot_id!==next.snapshot_id||snapshot.catalog_loaded!==true||snapshot.sources_loaded!==false)throw Error('PUBLICATION_SNAPSHOT_MISMATCH');
      // Prepare and verify the new generation before replacing any cached data.
      return {snapshot,commit(){
        manifestPromise=Promise.resolve(next);rankingPromise=Promise.resolve(snapshot);
        workspacePromise=decodedPromise=comparisonPromise=modelIndexPromise=taskEvidencePromise=null;
        modelPromises.clear();window.RadarTaskMeasurements=null;
        window.RadarHomeSnapshot=snapshot;
        return snapshot;
      }};
    })().finally(()=>{publicationCheck=null;}));
  };
  window.RadarLoadRanking=function({signal}={}){
    return rankingPromise||(rankingPromise=(async()=>{
      const m=await manifest(),meta=m.ranking;
      if(!meta||meta.snapshot_id!==m.snapshot_id||!safePath(meta.path))throw Error('RANKING_DATA_UNAVAILABLE');
      const raw=await bytes(meta.path,signal);
      const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',raw)),b=>b.toString(16).padStart(2,'0')).join('');
      if(raw.length!==meta.bytes||hash!==meta.sha256)throw Error('RANKING_INTEGRITY_FAILURE');
      const data=JSON.parse(new TextDecoder().decode(await gunzip(raw)));
      if(data.snapshot_id!==m.snapshot_id||data.sources_loaded!==false)throw Error('RANKING_SNAPSHOT_MISMATCH');
      return data;
    })().catch(error=>{rankingPromise=null;throw error;}));
  };
  window.RadarLoadTaskEvidence=function(){
    if(taskEvidencePromise)return taskEvidencePromise;
    taskEvidencePromise=(async()=>{
      const m=await manifest(),meta=m.task_evidence;
      if(!meta||meta.format!=='radar-static-task-evidence-v1'||meta.snapshot_id!==m.snapshot_id||!safePath(meta.path))throw Error('TASK_EVIDENCE_UNAVAILABLE');
      let raw;
      for(let attempt=0;attempt<2;attempt++){
        const ctrl=new AbortController(),timer=setTimeout(()=>ctrl.abort(),25000);
        try{raw=await bytes(meta.path,ctrl.signal);break;}
        catch(error){
          const temporary=ctrl.signal.aborted||error.name==='AbortError'||error.name==='TimeoutError'||error instanceof TypeError||[502,503,504].includes(error.status);
          if(!temporary)throw error;
          if(attempt===1)throw Error('任务评测数据读取超时或连接中断。当前输入已保留，请点击“重新读取候选模型”后重试。');
        }finally{clearTimeout(timer);}
      }
        const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',raw)),b=>b.toString(16).padStart(2,'0')).join('');
        if(raw.length!==meta.bytes||hash!==meta.sha256)throw Error('TASK_EVIDENCE_INTEGRITY_FAILURE');
        const data=JSON.parse(new TextDecoder().decode(await gunzip(raw)));
        if(data.format!==meta.format||data.snapshot_id!==m.snapshot_id||data.snapshot?.snapshot_id!==m.snapshot_id||data.measurements?.snapshot_id!==m.snapshot_id||data.task_method_version!==meta.task_method_version)throw Error('TASK_SNAPSHOT_MISMATCH');
        return data;
    })().catch(error=>{taskEvidencePromise=null;throw error;});
    return taskEvidencePromise;
  };
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
    if(window.RadarTaskConnection?.supports(route,method))return window.RadarTaskConnection.request(route,init);
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
    const css=document.createElement('style');css.id='snapshot-readonly-style';css.textContent='body[data-snapshot-mode] #view-tasks>:not(.snapshot-notice){display:none!important}.snapshot-notice{margin:20px 0;padding:24px;border:1px solid #dfE7f1;border-radius:16px;background:#fff;color:#33475d;line-height:1.9}.snapshot-notice h2{font-size:18px;margin:0 0 10px}.snapshot-notice p{margin:6px 0;font-size:14px}';document.head.append(css);
    const task=document.getElementById('visitor-task')?.closest('.visitor-composer');
    if(task){task.hidden=true;const info=document.createElement('article');info.className='visitor-composer snapshot-notice';const h=document.createElement('h2');h.textContent='评测数据更新';const p=document.createElement('p');p.textContent='浏览模型综合评分、评测原始成绩和论文来源。后台核验通过的数据自动发布，页面标注最近一批数据的时间。';const asof=document.createElement('p');asof.id='snapshot-asof';info.append(h,p,asof);task.after(info);manifest().then(m=>{asof.textContent='数据截至 '+new Date(m.generated_at).toLocaleString('zh-CN',{hour12:false});}).catch(()=>{});}
    const hint=document.querySelector('.visitor-hero-links span');if(hint)hint.textContent='查看评测范围与原始来源。';
    const view=document.getElementById('view-tasks');if(view){const note=document.createElement('section');note.id='snapshot-task-gate';note.className='snapshot-notice';const h=document.createElement('h2');h.textContent='任务选模型暂未开放';const p=document.createElement('p');p.textContent='当前版本提供模型表现、评测目录和来源查询。任务需求分析与选型暂不可用，可先查阅相关评测和原始成绩。';note.append(h,p);view.append(note);}
    const refresh=document.getElementById('refresh');if(refresh){refresh.textContent='检查更新';refresh.title='检查已发布的新数据；后台每五分钟检查一次';}
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',applyReadOnlyUI,{once:true});else applyReadOnlyUI();
})();
