export function normalizeQuery(value) {
  if(typeof value!=='string'||!value.trim()||value.length>512)throw Error('请输入最多512字的名称、ID或链接');
  let key=value.normalize('NFKC').trim().toLowerCase().replace(/\s+/gu,' ');
  const m=key.match(/^https:\/\/(?:www\.)?arxiv\.org\/(?:abs|html|pdf)\/(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?\/?$/u);
  return m?m[1]:key;
}
export async function sha256(bytes) {
  return [...new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');
}
export async function judge(query,manifestURL=new URL('./manifest.json',import.meta.url),fetcher=fetch) {
  const key=normalizeQuery(query),response=await fetcher(manifestURL,{cache:'no-cache'});
  if(!response.ok)throw Error('判断接口暂不可用');
  const manifest=await response.json();
  if(manifest.format!=='benchmark-release-judgment-api-v1')throw Error('接口版本不匹配');
  const root=new URL(manifest.api_root,manifestURL);
  async function shard(meta) {
    if(meta?.empty===true)return {};
    if(!meta||!/^((lookup|judgments)\/[a-f0-9]{2}\.json)$/u.test(meta.path))throw Error('无效数据路径');
    const url=new URL(meta.path,root);
    if(url.origin!==root.origin)throw Error('数据来源不匹配');
    const r=await fetcher(url);if(!r.ok)throw Error('证据数据加载失败，请重试');
    const raw=await r.arrayBuffer();
    if(raw.byteLength!==meta.bytes||await sha256(raw)!==meta.sha256)throw Error('证据数据校验失败');
    const data=JSON.parse(new TextDecoder().decode(raw));
    if(['snapshot_id','source_sha256','registry_sha256','generation'].some(k=>data[k]!==manifest[k]))throw Error('数据快照不一致');
    return data.items;
  }
  const prefix=(await sha256(new TextEncoder().encode(key))).slice(0,2);
  const ids=(await shard(manifest.lookup[prefix]))[key]||[],cache=new Map(),matches=[];
  for(const id of ids.slice(0,50)) {
    const p=(await sha256(new TextEncoder().encode(id))).slice(0,2);
    if(!cache.has(p))cache.set(p,await shard(manifest.judgments[p]));
    const row=cache.get(p)[id];if(!row)throw Error('判断条目缺失');matches.push(row);
  }
  const status=ids.length===1?'MATCHED':ids.length?'AMBIGUOUS':'NOT_FOUND';
  return {snapshot_id:manifest.snapshot_id,source_sha256:manifest.source_sha256,source_generated_at:manifest.source_generated_at,
    query,normalized_query:key,result_status:status,judgment:ids.length===1?matches[0].judgment:'PENDING',
    is_new_in_report_period:ids.length===1?matches[0].is_new_in_report_period:null,
    needs_research:ids.length!==1||matches[0].needs_research,match_count:ids.length,matches,truncated:ids.length>50,
    notice:manifest.notice};
}
