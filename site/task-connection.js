/* The public task scorer runs the published Python rules over this edition's inputs. */
(() => {
  'use strict';
  const boot = JSON.parse(document.getElementById('snapshot-bootstrap').textContent);
  const manifest = boot.manifest;
  const jobs = new Map();
  const prefix = 'papermate-score:'+manifest.snapshot_id+':';
  const response = (body,status=200) => Response.json(body,{status});
  const supports = (route,method) => method==='GET' && ['/api/taxonomy','/api/task-measurements'].includes(route) ||
    method==='POST' && ['/api/task-profile','/api/task-score','/api/interactive-jobs'].includes(route) ||
    ['GET','DELETE'].includes(method) && /^\/api\/interactive-jobs\/[A-Za-z0-9_-]{43}$/.test(route);
  async function connect({measurements=true}={}) {
    if (measurements && !window.RadarTaskMeasurements) {
      const evidence = await window.RadarLoadTaskEvidence();
      if (evidence.measurements?.snapshot_id !== manifest.snapshot_id || evidence.task_method_version !== 12) throw Error('task_snapshot_mismatch');
      window.RadarTaskMeasurements=evidence.measurements;
    }
    if (!window.RadarTaskConnected) {
      window.RadarTaskConnected=true;
      document.getElementById('snapshot-readonly-style')?.remove();
      document.getElementById('snapshot-task-gate')?.remove();
      const composer=document.getElementById('visitor-task')?.closest('.visitor-composer');
      if(composer) composer.hidden=false;
      const analyze=document.getElementById('analyse-task');
      if(analyze) analyze.disabled=true;
      const privacy=document.querySelector('.task-privacy');
      if(privacy) privacy.textContent='手动设置任务能力与权重后即可评分。任务评分在当前浏览器内完成。';
      window.dispatchEvent(new CustomEvent('radar:task-connected'));
    }
    return {snapshotId:manifest.snapshot_id};
  }
  function launch(id,payload) {
    const worker=new Worker('/task-score-worker.js');
    const job={id,state:'RUNNING',started:Date.now(),worker};
    jobs.set(id,job);
    const finish=outcome=>{
      Object.assign(job,outcome);
      worker.terminate();
      job.worker=null;
      try { sessionStorage.removeItem(prefix+id); } catch {}
    };
    worker.onmessage=({data})=>finish(data);
    worker.onerror=()=>finish({state:'FAILED',error:'task_score_failed'});
    worker.postMessage({meta:manifest,payload});
    return job;
  }
  async function request(route,init={}) {
    if(route==='/api/taxonomy') return fetch('/task-taxonomy.json');
    if(route==='/api/task-profile') return response({error:'task_profile_unavailable'},503);
    await connect();
    if(route==='/api/task-measurements') return response(window.RadarTaskMeasurements);
    if(route==='/api/interactive-jobs' || route==='/api/task-score'){
      const body=JSON.parse(init.body);
      if(body.kind && body.kind!=='score') return response({error:'task_profile_unavailable'},503);
      const payload=body.payload||body;
      const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(body.request_id||crypto.randomUUID()));
      const id=btoa(String.fromCharCode(...new Uint8Array(digest))).replaceAll('+','-').replaceAll('/','_').replaceAll('=','');
      let job=jobs.get(id);
      if(!job){
        for(const [oldId,old] of jobs) if(!old.worker && jobs.size>=3) jobs.delete(oldId);
        try{sessionStorage.setItem(prefix+id,JSON.stringify(payload));}catch{}
        job=launch(id,payload);
      }
      if(route==='/api/task-score'){
        while(job.state==='RUNNING') await new Promise(resolve=>setTimeout(resolve,150));
        return job.result?response(job.result):response({error:job.error},500);
      }
      return response({id,state:job.state,result:job.result},202);
    }
    const id=route.split('/').pop();
    let job=jobs.get(id);
    if(init.method==='DELETE'){
      job?.worker?.terminate(); jobs.delete(id);
      try{sessionStorage.removeItem(prefix+id);}catch{}
      return response({id,state:'CANCELLED'});
    }
    if(!job){
      let previous;
      try { previous=JSON.parse(sessionStorage.getItem(prefix+id)); } catch {}
      if(previous) job=launch(id,previous);
    }
    if(!job) return response({error:'job_expired_or_unknown'},404);
    return response({id,state:job.state,error:job.error,result:job.result,elapsed_seconds:Math.floor((Date.now()-job.started)/1000)});
  }
  window.RadarTaskConnection=Object.freeze({supports,connect,request});
  const start=()=>connect({measurements:false});
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',start,{once:true}); else start();
})();
