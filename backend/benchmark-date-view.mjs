import {judge} from './judge-client.mjs';

export function dateLabel(row) {
  if(row.benchmark_date_status==='VERIFIED_FIRST_PUBLIC'&&row.benchmark_first_public_date)
    return 'Benchmark 首发：'+row.benchmark_first_public_date+'（已核实）';
  if(row.benchmark_date_status==='NOT_A_BENCHMARK')return '独立 Benchmark 首发日期：不适用';
  if(row.first_public_on_or_before)return 'Benchmark 首发：待核；最迟 '+row.first_public_on_or_before+' 已公开';
  return 'Benchmark 首发：待核';
}

export async function renderReleaseDate(node,benchmark,{snapshotId,queryFunction=judge}={}) {
  const key=JSON.stringify([snapshotId,benchmark.paper_id,benchmark.benchmark_id]);
  node.dataset.releaseLookup=key;node.textContent='Benchmark 首发：待核（正在读取日期台账）';
  try {
    const result=await queryFunction(benchmark.paper_id+'::'+benchmark.benchmark_id,new URL('./manifest.json',import.meta.url),
      (url,options)=>fetch(url,{...options,signal:AbortSignal.timeout(8000)}));
    if(node.dataset.releaseLookup!==key||node.isConnected===false)return;
    if(!snapshotId||result.snapshot_id!==snapshotId)throw Error('首发台账与当前成绩快照不一致，待同步');
    const matches=result.matches.filter(r=>r.source_refs.some(s=>s.paper_id===benchmark.paper_id&&s.benchmark_id===benchmark.benchmark_id));
    if(matches.length!==1)throw Error('尚未核实唯一身份');
    const row=matches[0];node.textContent=dateLabel(row)+' ';
    const a=document.createElement('a');a.textContent='查看日期证据';
    const url=new URL('./judge.html',import.meta.url);url.searchParams.set('q',row.entity_id);
    a.href=url.href;node.append(a);
  } catch(error) {
    if(node.dataset.releaseLookup!==key||node.isConnected===false)return;
    node.textContent='Benchmark 首发：待核（'+error.message+'）';
  }
}
