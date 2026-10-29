'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const node = (tag, text, cls) => {const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
  const format = v => typeof v==='number'&&Number.isFinite(v)?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:1}).format(v):'—';
  const navigate = view => window.RadarApp?.navigate(view);

  // Keep all tested controls and their IDs, but let visitors reveal complexity
  // when they need it instead of presenting the complete workbench at once.
  const editor=document.querySelector('.task-editor');
  $('eligibility').value='ELIGIBLE';
  $('task-description').rows=4;
  const requirements=node('details',null,'visitor-requirements');
  requirements.append(node('summary','调整需求与能力权重'));
  const editorHeading=editor.querySelector('.task-editor-heading');
  while(editorHeading.nextSibling)requirements.append(editorHeading.nextSibling);
  const profileSummary=node('div',null,'visitor-profile-summary');
  editor.append(profileSummary,requirements);
  editorHeading.querySelector('h3').textContent='能力需求配置';
  const candidate=document.querySelector('.candidate-browser');
  const candidates=node('details',null,'visitor-candidates');
  const candidateSummary=node('summary','调整参与比较的模型');candidates.append(candidateSummary);
  for(const selector of ['.candidate-toolbar','.candidate-actions','.candidate-layout'])candidates.append(candidate.querySelector(selector));
  candidate.querySelector('.task-submit').before(candidates);
  candidate.querySelector('h3').textContent='候选模型比较';
  document.querySelector('#view-tasks .journey').remove();
  document.querySelector('#view-tasks .section-head h2').textContent='任务选模型';
  document.querySelector('#view-tasks .section-head .eyebrow').remove();
  const pair=document.querySelector('.paired-values'),pairDetails=node('details',null,'visitor-pair-details');
  pairDetails.append(node('summary','共同测试结果 · 双模型比较'));
  pair.before(pairDetails);pairDetails.append(pair);
  const modelRoot=$('view-models');modelRoot.append(pairDetails);
  const commonJump=node('button','查看共同测试结果','common-evidence-jump');commonJump.type='button';
  commonJump.onclick=()=>window.RadarApp?.openCommonTests();
  modelRoot.querySelector('.section-head').append(commonJump);
  pairDetails.addEventListener('toggle',()=>{if(pairDetails.open){window.RadarApp?.openCommonTests();window.dispatchEvent(new Event('resize'));}});
  const coverage=$('model-coverage'),coverageDetails=node('details',null,'visitor-coverage-details');
  coverageDetails.append(node('summary','查看各模型的评测覆盖'));coverage.before(coverageDetails);coverageDetails.append(coverage);
  coverageDetails.addEventListener('toggle',()=>{if(coverageDetails.open)window.dispatchEvent(new Event('resize'));});
  $('visual-highlights').classList.add('visitor-unused-overview');
  document.querySelector('#view-benchmarks .section-head h2').textContent='评测目录';
  document.querySelector('#view-models > .section-head h2').textContent='模型表现';
  document.querySelector('#view-models > .section-head p').textContent='汇总模型评测结果，并提供原始成绩与来源查询。';
  const filters=document.querySelector('#view-benchmarks .filters');
  const map=node('button','能力分布','visitor-map-link');map.type='button';map.onclick=()=>navigate('capabilities');filters.after(map);
  $('close-detail').textContent='返回评测目录';
  $('close-detail').addEventListener('click',()=>window.scrollTo({top:0,behavior:'instant'}));
  new MutationObserver(()=>{document.body.dataset.visitorDetail=String(!$('detail').hidden);}).observe($('detail'),{attributes:true,attributeFilter:['hidden']});
  document.addEventListener('click',event=>{
    const anchor=event.target.closest('a[href]');if(!anchor||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey||anchor.target==='_blank')return;
    const url=new URL(anchor.href);if(url.origin!==location.origin||url.pathname!=='/benchmark')return;
    const dialog=anchor.closest('dialog');if(window.RadarApp?.openBenchmark(url.searchParams.get('paper_id'),url.searchParams.get('benchmark_id'))){event.preventDefault();dialog?.close();}
  });

  $('visitor-start-task').onclick=()=>{
    navigate('tasks');
    if($('visitor-task').value.trim()){
      $('task-description').value=$('visitor-task').value.trim();
      $('task-description').dispatchEvent(new Event('input',{bubbles:true}));
      $('profile-message').textContent='任务描述已载入。可提交能力需求分析，或手动配置能力与权重。';
    }
    $('task-description').focus({preventScroll:true});
  };
  for(const button of document.querySelectorAll('[data-template]'))button.onclick=()=>window.RadarApp?.useTemplate(button.dataset.template);

  function syncProfile(){
    profileSummary.replaceChildren();
    const label=node('p','所选能力','visitor-profile-label');profileSummary.append(label);
    const scope=['task-domains','task-types'].flatMap(id=>[...$(id).selectedOptions].map(option=>option.textContent));
    label.textContent=scope.length?scope.join(' · '):'所选能力';
    for(const row of document.querySelectorAll('.weight-row')){
      if(!row.querySelector('input[type=checkbox]')?.checked)continue;
      profileSummary.append(node('span',row.querySelector('label').textContent+' '+row.querySelector('output').textContent,'visitor-weight-chip'));
    }
    const selected=$('reference-count').textContent;
    candidateSummary.textContent='调整参与比较的模型'+(selected?' · '+selected:'');
  }
  new MutationObserver(syncProfile).observe($('capability-weights'),{childList:true,subtree:true,characterData:true});
  new MutationObserver(syncProfile).observe($('reference-count'),{childList:true,subtree:true,characterData:true});
  let lastSnapshot=null;
  $('visitor-top-models').addEventListener('click',async event=>{
    const button=event.target.closest('[data-home-model]');if(!button||button.disabled)return;
    button.disabled=true;button.setAttribute('aria-busy','true');
    try{await window.RadarApp.openModel(button.dataset.homeModel,'');}
    finally{button.disabled=false;button.removeAttribute('aria-busy');}
  });
  window.addEventListener('radar:render',event=>{
    const {snapshot,view}=event.detail;
    document.body.dataset.visitorView=view;
    if(!snapshot)return;
    if(lastSnapshot===snapshot)return;lastSnapshot=snapshot;
    const ready=snapshot.detail_loaded!==false;
    if(!ready||snapshot.sources_loaded===false)return;
    const V=window.RadarViz;
    V.setModelRegistry(snapshot.model_registry);
    const models=V.modelData(snapshot,'').rows.filter(r=>typeof r.score==='number'&&Number.isFinite(r.score)).sort((a,b)=>b.score-a.score||a.name.localeCompare(b.name));
    const unique=[];for(const row of models)if(!unique.some(r=>r.name===row.name))unique.push(row);
    const top=$('visitor-top-models');top.replaceChildren();
    for(const [i,row] of unique.slice(0,6).entries()){
      const button=node('button',null,'visitor-model-row');button.type='button';button.setAttribute('aria-label',`查看 ${row.name} 的模型详情，综合分 ${format(row.score)}`);
      const info=V.modelInfo(row.name),label=node('span',null,'visitor-model-name');label.append(node('strong',row.name),node('small',`${info.vendor} · ${row.nBenchmarks??'—'} 项评测`));
      const swatch=node('span',null,'visitor-model-swatch');swatch.style.background=V.vendorColor(info.vendor);
      button.append(node('span',String(i+1).padStart(2,'0'),'visitor-rank'),swatch,label,node('strong',format(row.score),'visitor-model-score'));
      button.onclick=()=>window.RadarApp.openModel(row.name,'');top.append(button);
    }
    if(!unique.length)top.append(node('p','当前数据版本尚未发布综合评分，单项评测成绩仍可查询。','visitor-loading'));
    const byBenchmark=new Map();for(const r of snapshot.observations||[]){const key=JSON.stringify([r.paper_id,r.benchmark_id]);const stat=byBenchmark.get(key)||{count:0,models:new Set()};stat.count++;if(r.model_canonical)stat.models.add(r.model_canonical);byBenchmark.set(key,stat);}
    const directorySeen=new Set();
    const featured=snapshot.benchmarks.filter(b=>b.eligibility==='ELIGIBLE'&&byBenchmark.has(JSON.stringify([b.paper_id,b.benchmark_id])))
      .sort((a,b)=>(Date.parse(b.paper_first_published)||0)-(Date.parse(a.paper_first_published)||0)||a.benchmark_name.localeCompare(b.benchmark_name)).filter(b=>{const key=V.directoryKey(b);if(directorySeen.has(key))return false;directorySeen.add(key);return true;}).slice(0,4);
    const list=$('visitor-featured');list.replaceChildren();
    for(const b of featured){
      const stat=byBenchmark.get(JSON.stringify([b.paper_id,b.benchmark_id]));
      const button=node('button',null,'visitor-benchmark-row');button.type='button';button.setAttribute('aria-label',`查看 ${b.benchmark_name} 的评测详情`);
      const copy=node('span',null,'visitor-benchmark-copy');copy.append(node('strong',b.benchmark_name),node('span',b.paper_title,'visitor-benchmark-description'),node('small',`${stat.models.size} 个模型 · ${format(stat.count)} 条来源成绩`));
      button.append(copy);button.onclick=()=>window.RadarApp.openBenchmark(b.paper_id,b.benchmark_id);list.append(button);
    }
    if(!featured.length)list.append(node('p','当前窗口尚无可展示的已核验成绩。','visitor-loading'));
  });
})();
