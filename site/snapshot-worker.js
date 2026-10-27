/* Decode the immutable evidence archive away from the interface thread. */
'use strict';
importScripts('snapshot-codec.js');
self.onmessage=async event=>{
 try{
  const {manifest:m,base}=event.data;
  if(!Array.isArray(m.parts)||!m.parts.length)throw Error('INVALID_SNAPSHOT_MANIFEST');
  const parts=new Array(m.parts.length);let cursor=0,received=0;
  const total=m.parts.reduce((n,p)=>n+p.bytes,0);
  const progress=text=>self.postMessage({type:'progress',text});
  progress('正在按需加载完整评测数据…');
  async function download(){while(cursor<m.parts.length){
   const i=cursor++,part=m.parts[i];
   if(!/^snapshot\/[a-zA-Z0-9._/-]+$/.test(part.path)||part.path.split('/').includes('..'))throw Error('INVALID_SNAPSHOT_PATH');
   const response=await fetch(new URL(part.path,base),{cache:'force-cache'});
   if(!response.ok)throw Error('SNAPSHOT_ASSET_UNAVAILABLE');
   parts[i]=new Uint8Array(await response.arrayBuffer());
   if(parts[i].length!==part.bytes)throw Error('SNAPSHOT_PART_LENGTH');
   received+=part.bytes;progress(`正在加载完整评测数据 · ${Math.round(received/total*100)}%`);
  }}
  await Promise.all(Array.from({length:Math.min(3,m.parts.length)},download));
  const joined=new Uint8Array(total);let offset=0;
  for(const part of parts){joined.set(part,offset);offset+=part.length;}
  const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',joined)),b=>b.toString(16).padStart(2,'0')).join('');
  if(digest!==m.workspace_sha256)throw Error('SNAPSHOT_INTEGRITY_FAILURE');
  progress('下载完成 · 正在后台解析来源成绩…');
  const text=await new Response(new Blob([joined]).stream().pipeThrough(new DecompressionStream('gzip'))).text();
  const snapshot=decodeSnapshot(JSON.parse(text));
  self.postMessage({type:'ready',snapshot});
 }catch(error){self.postMessage({type:'error',error:error.message});}
};
