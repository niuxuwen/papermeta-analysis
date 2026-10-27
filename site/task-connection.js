/* Only interactive task routes use the configured backend; evidence stays static. */
(function(){
  'use strict';
  const base=new URL('./',document.currentScript.src),network=window.fetch.bind(window);
  let connection;
  const supports=(route,method)=>['/api/task-profile','/api/task-score','/api/interactive-jobs'].includes(route)?method==='POST':route==='/api/taxonomy'?method==='GET':/^\/api\/interactive-jobs\/[A-Za-z0-9_-]{43}$/.test(route)&&['GET','DELETE'].includes(method);
  async function connect(){
    if(connection)return connection;
    connection=(async()=>{
      const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),10000);
      try{
        const response=await network(new URL('task-backend.json',base),{cache:'no-store',credentials:'omit',signal:controller.signal});
        if(!response.ok)throw Error('TASK_SERVICE_NOT_CONFIGURED');
        const config=await response.json();if(!config.enabled)throw Error('TASK_SERVICE_NOT_CONFIGURED');
        const url=new URL(config.base_url);
        const local=['127.0.0.1','localhost'].includes(url.hostname)&&['127.0.0.1','localhost'].includes(location.hostname);
        if((url.protocol!=='https:'&&!local)||url.username||url.password||url.search||url.hash||url.pathname!=='/')throw Error('INVALID_TASK_SERVICE');
        const health=await network(new URL('api/task-service',url),{cache:'no-store',credentials:'omit',signal:controller.signal});
        if(!health.ok)throw Error('TASK_SERVICE_UNAVAILABLE');
        const service=await health.json();
        const bootstrap=JSON.parse(document.getElementById('snapshot-bootstrap').textContent);
        if(service.snapshot_id!==bootstrap.snapshot.snapshot_id)throw Error('TASK_SNAPSHOT_MISMATCH');
        if(service.status!=='READY'||!service.task_score_available)throw Error('TASK_SERVICE_UNAVAILABLE');
        window.RadarTaskConnected=true;activate(service);window.dispatchEvent(new CustomEvent('radar:task-connected'));
        return {url,service};
      }finally{clearTimeout(timeout);}
    })().catch(error=>{connection=null;throw error;});
    return connection;
  }
  function activate(service){
    document.getElementById('snapshot-readonly-style')?.remove();
    document.getElementById('snapshot-task-gate')?.remove();
    const composer=document.getElementById('visitor-task')?.closest('.visitor-composer');if(composer)composer.hidden=false;
    document.getElementById('snapshot-asof')?.closest('.snapshot-notice')?.remove();
    const analyse=document.getElementById('analyse-task');if(analyse)analyse.disabled=!service.task_profile_available;
    const privacy=document.querySelector('.task-privacy');if(privacy)privacy.textContent='仅在提交任务分析时发送任务描述；任务评分使用本页对应的评测数据。';
  }
  async function request(route,init){
    if(!supports(route,(init?.method||'GET').toUpperCase()))return new Response(JSON.stringify({error:'not_found'}),{status:404,headers:{'Content-Type':'application/json'}});
    try{const {url}=await connect();return network(new URL(route.slice(1),url),{...init,credentials:'omit',redirect:'error'});}
    catch(error){if(error.name==='AbortError')throw error;return new Response(JSON.stringify({error:error.message==='TASK_SNAPSHOT_MISMATCH'?'task_snapshot_mismatch':'task_service_unavailable'}),{status:503,headers:{'Content-Type':'application/json'}});}
  }
  window.RadarTaskConnection=Object.freeze({supports,connect,request});
  function start(){
    const gate=document.getElementById('snapshot-task-gate');
    if(gate){gate.querySelector('h2').textContent='正在连接任务服务';gate.querySelector('p').textContent='连接完成后，可分析任务需求、调整能力权重并比较模型。';}
    connect().catch(error=>{
      if(!gate)return;
      gate.querySelector('h2').textContent='任务服务暂不可用';
      gate.querySelector('p').textContent=error.message==='TASK_SNAPSHOT_MISMATCH'?'任务数据与本页版本尚未同步，请稍后重试。':'模型评分与评测来源仍可浏览，请稍后重新连接任务服务。';
      if(!gate.querySelector('button')){const retry=document.createElement('button');retry.type='button';retry.textContent='重新连接';retry.onclick=()=>{retry.remove();start();};gate.append(retry);}
    });
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
