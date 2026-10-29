const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),{webcrypto}=require('node:crypto');
const source=fs.readFileSync(__dirname+'/site/radar.js','utf8');
function setup(network){
  const stored=new Map(),calls=[],messages=[],ctrl=new AbortController();
  const context={URL,Response,DOMException,AbortController,TypeError,crypto:webcrypto,Date,radarBase:new URL('https://viewer.test/'),
    setTimeout:(fn,ms)=>setTimeout(fn,ms===15000?20:1),clearTimeout,
    sessionStorage:{getItem:k=>stored.get(k),setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)},
    taskMessage:(...args)=>messages.push(args),fetch:async(url,options)=>{calls.push({path:new URL(url).pathname,...options});return network(url,options,calls.length,ctrl);}};
  vm.createContext(context);vm.runInContext(source.slice(source.indexOf('  const jobStorageKey'),source.indexOf('  let resumedInteractive')),context);
  return{context,stored,calls,messages,ctrl,run:()=>context.taskPost('api/task-profile',{description:'整理医学文献'},ctrl)};
}
const id='a'.repeat(43),complete=()=>Response.json({id,state:'COMPLETE',result:{profile:{description:'整理医学文献'}}});
test('lost submission response retries with the same idempotency key and payload',async()=>{
  const s=setup(async(_,options,n)=>{if(n===1)throw new DOMException('signal is aborted without reason','AbortError');return complete();});
  assert.equal((await s.run()).profile.description,'整理医学文献');
  assert.equal(s.calls.length,2);assert.equal(s.calls[0].body,s.calls[1].body);assert.equal(s.stored.size,0);
  assert(s.messages.some(m=>m[1].includes('重新连接')));
});
test('a failed poll resumes the existing job without another submission or cancellation',async()=>{
  const s=setup(async(_,options,n)=>{if(n===1)return Response.json({id,state:'RUNNING'});if(n===2)throw new TypeError('Failed to fetch');return complete();});
  await s.run();assert.equal(s.calls.filter(c=>c.method==='POST').length,1);
  assert.deepEqual(s.calls.slice(1).map(c=>c.path),['/api/interactive-jobs/'+id,'/api/interactive-jobs/'+id]);
  assert(!s.calls.some(c=>c.method==='DELETE'));
});
test('repeated timeouts preserve the job and retry continues polling it',async()=>{
  let recovered=false;
  const s=setup(async(_,options,n)=>{if(n===1)return Response.json({id,state:'RUNNING'});if(recovered)return complete();return new Promise((_,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('signal is aborted without reason','AbortError')),{once:true}));});
  await assert.rejects(s.run(),/任务服务连接中断/);assert.equal(s.stored.size,1);
  recovered=true;await s.run();assert.equal(s.calls.filter(c=>c.method==='POST').length,1);assert.equal(s.stored.size,0);
});
test('snapshot mismatch and authentication failure are not retried',async()=>{
  for(const code of ['task_snapshot_mismatch','task_profile_auth_failed']){
    const s=setup(async()=>Response.json({error:code},{status:503}));await assert.rejects(s.run());assert.equal(s.calls.length,1);
  }
});
test('cancelling while reconnecting stops retries and clears the saved intent',async()=>{
  const s=setup(async(_,options,n,ctrl)=>{ctrl.abort();throw new DOMException('signal is aborted without reason','AbortError');});
  await assert.rejects(s.run(),{name:'AbortError'});assert.equal(s.calls.length,1);assert.equal(s.stored.size,0);
});
test('raw browser abort messages are translated before reaching the task screen',()=>{
  const node={};const context={$:()=>node};vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('  function taskMessage('),source.indexOf('  function dirtyTask(')),context);
  context.taskMessage('task-score-message','signal is aborted without reason','warning');
  assert.match(node.textContent,/网络连接中断/);assert(!node.textContent.includes('signal'));
});
