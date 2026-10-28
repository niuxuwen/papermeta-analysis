'use strict';
(() => {
  const visitorEdition=document.body?.dataset?.edition==='visitor';
  const radarBase = (() => {
    const url = new URL(location.href);url.search='';url.hash='';
    if(/\/admin\/?$/.test(url.pathname))url.pathname=url.pathname.replace(/admin\/?$/,'');
    else if(!url.pathname.endsWith('/'))url.pathname=/\/(classic|benchmark|index\.html)$/.test(url.pathname)?url.pathname.slice(0,url.pathname.lastIndexOf('/')+1):url.pathname+'/';
    return url;
  })();
  for(const a of document.querySelectorAll('a[href^="./"]'))a.href=new URL(a.getAttribute('href'),radarBase).href;
  const $ = id => document.getElementById(id);
  const state = {snapshot:null, view:visitorEdition?'home':'benchmarks', query:'', eligibility:visitorEdition?'ELIGIBLE':'all', sort:'coverage', selected:null, group:'', benchmarkLimit:40, scoreLimit:80, modelLimit:100, loading:false, domain:'', taskType:'', capability:''};
  let requestedModel=new URL(location.href).searchParams.get('model');
  const Viz=window.RadarViz;
  let visualSetting=null, detailVisualSetting=null, detailVisualMetric='';
  const rankingPanels=new Map();
  function selectedRankingPanel(setting){const panels=(state.snapshot?.index?.score_panels||[]).filter(p=>p.model_setting===setting);return panels.find(p=>p.panel_id===rankingPanels.get(setting))||panels[0];}
  function rankingData(){return Viz.modelData(state.snapshot,visualSetting,selectedRankingPanel(visualSetting)?.panel_id);}
  function scopedModels(){const rows=state.snapshot?.index?.models||[];if(state.snapshot?.index?.method?.score_unit!=='z_score')return rows;return rows.map(m=>{const panel=selectedRankingPanel(m.model_setting);return panel?.models?.find(x=>x.model_canonical===m.model_canonical)||{...m,score:null,publication_score:null,publication_eligible:false,score_panel_id:panel?.panel_id||null,score_components:[],missing_score_groups:[],provisional:true,status:'PARTIAL',blocked_group_ids:[],publication_status:panel?'INCOMPLETE_COMMON_PANEL':'NO_COMMON_RELATIVE_PANEL'};});}
  const chartAxis=a=>{const b=state.snapshot?.benchmarks.find(b=>b.paper_id===a.paper_id&&b.benchmark_id===a.benchmark_id);if(b)selectBenchmark(b);};
  const overviewRanking=Viz.create($('overview-ranking'),{compact:true,initial:'bar',onAxis:chartAxis,onModel:openModel});
  const overviewCoverage=Viz.create($('overview-coverage'),{compact:true,initial:'bar',title:'可比评测覆盖情况',onAxis:chartAxis,onModel:openModel});
  $('visual-highlights').addEventListener('toggle',()=>{if($('visual-highlights').open){overviewRanking.redraw();overviewCoverage.redraw();}});
  const modelVisuals=Viz.create($('model-visuals'),{initial:'bar',onAxis:chartAxis,onModel:openModel});
  const modelCoverage=Viz.create($('model-coverage'),{initial:'bar',title:'证据覆盖 · 可比 Benchmark 数',onAxis:chartAxis,onModel:openModel});
  const taskVisuals=Viz.create($('task-visuals'),{initial:'bar',title:'任务相关模型对比',onAxis:chartAxis,onModel:openModel});
  const detailVisuals=Viz.create($('detail-visuals'),{initial:'bar',onAxis:chartAxis,onModel:openModel});
  const labels = {COMPLETE:'已有核验成绩',EXCLUDED:'已排除',FAILED:'处理失败',PENDING:'等待处理',RUNNING:'正在处理',REVIEW:'等待补证',RETRY_EXHAUSTED:'补证次数耗尽',EXPIRED:'已过期',ELIGIBLE:'资格已核验',RUNNING_SERVICE:'服务运行中',DEGRADED:'服务降级',STOPPED:'服务已停止'};
  const text = v => typeof v === 'string' ? v : v == null ? '—' : String(v);
  const number = v => typeof v === 'number' && Number.isFinite(v) ? v : null;
  const statFmt=v=>number(v)===null?'—':v!==0&&Math.abs(v)<0.0001?v.toExponential(3):new Intl.NumberFormat('zh-CN',{maximumFractionDigits:4}).format(v);
  const fmt = v => number(v) === null ? '—' : new Intl.NumberFormat('zh-CN',{maximumFractionDigits:1}).format(v);
  const date = v => v && Number.isFinite(Date.parse(v)) ? new Date(v).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}) : '日期待核验';
  const identity = b => `${b.paper_id}\u0000${b.benchmark_id}`;
  const el = (tag, content, cls) => {const node=document.createElement(tag);if(content!=null)node.textContent=text(content);if(cls)node.className=cls;return node;};
  const empty = (target,title,detail) => {target.replaceChildren();const box=el('div',null,'empty');box.append(el('strong',title),el('span',detail));target.append(box);};
  function link(url,label) {const a=el('a',label);try{const u=new URL(url);if(!['http:','https:'].includes(u.protocol)||u.username||u.password)throw Error();a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';}catch{return el('span',label);}return a;}
  let indexedSnapshot=null, observationsByBenchmark=new Map(), groupsByBenchmark=new Map();
  function indexEvidence() {
    if(indexedSnapshot===state.snapshot)return;
    observationsByBenchmark=new Map();groupsByBenchmark=new Map();indexedSnapshot=state.snapshot;
    for(const [rows,byBenchmark] of [[state.snapshot?.observations||[],observationsByBenchmark],[state.snapshot?.score_groups||state.snapshot?.index?.groups||[],groupsByBenchmark]]){
      for(const row of rows){const id=identity(row);if(!byBenchmark.has(id))byBenchmark.set(id,[]);byBenchmark.get(id).push(row);}
    }
  }
  const observations = b => {indexEvidence();return observationsByBenchmark.get(identity(b))||[];};
  const groups = b => {indexEvidence();return groupsByBenchmark.get(identity(b))||[];};
  const badge = (value, eligible=false) => el('span',labels[value]||text(value),`badge ${eligible?'good':String(value).includes('REVIEW')?'warning':''}`);
  const settingLabel=value=>value===''?'未另列实验设置':/^(?:cell|row|column):\d+(?::\d+)*$/.test(value)?'设置待核验':Viz.publicLabel(value,'设置待核验');
  let modelDialog=null;
  function modelLink(name,setting) {
    const button=el('button',name,'model-link');button.type='button';button.setAttribute('aria-label','查看 '+name+' 的模型详情');button.onclick=()=>openModel(name,setting);return button;
  }
  function openModel(name,initialSetting,{section}={}) {
    if(!state.snapshot||state.snapshot.detail_loaded===false)return;
    modelDialog?.close();
    const dialog=el('dialog',null,'model-dialog'),head=el('div',null,'model-dialog-head'),identityBlock=el('div',null,'model-dialog-identity'),title=el('h2',name),close=el('button','×','model-dialog-close');
    const producer=Viz.modelInfo(name),vendor=el('p',producer.vendor+' / 模型档案','model-dialog-vendor');
    title.id='model-detail-title';dialog.setAttribute('aria-labelledby',title.id);close.type='button';close.setAttribute('aria-label','关闭模型详情');close.title='关闭模型详情';close.onclick=()=>dialog.close();identityBlock.append(vendor,title);head.append(identityBlock,close);
    const body=el('div',null,'model-dialog-body'),intro=el('p','汇总该模型的参测项目、原始成绩与评分依据。','model-dialog-intro'),stats=el('div',null,'model-dialog-stats');stats.setAttribute('aria-label','当前实验设置的模型概览');
    const catalogSection=el('section',null,'model-benchmark-catalog model-detail-panel'),catalogTitle=el('h3','参测项目'),catalogNote=el('p',null,'model-catalog-note'),catalogSearch=el('input'),catalogToolbar=el('div',null,'model-catalog-toolbar'),catalogList=el('div',null,'model-catalog-list'),catalogMore=el('button',null,'model-source-more');
    const controls=el('div',null,'model-settings'),label=el('label','实验设置 '),select=el('select');select.setAttribute('aria-label','模型详情实验设置');label.append(select);controls.append(label);
    const summary=el('p',null,'model-detail-summary'),content=el('div'),sourcePanel=el('section',null,'model-detail-panel model-detail-sources'),sourceSearch=el('input'),scorePanel=el('section',null,'model-detail-panel model-detail-scoring'),scoreContent=el('div'),audit=el('details',null,'explanation model-name-audit'),auditBody=el('p',null,'method-note');
    sourceSearch.type='search';sourceSearch.placeholder='搜索评测名称或指标…';sourceSearch.setAttribute('aria-label','搜索模型成绩');
    catalogSearch.type='search';catalogSearch.placeholder='搜索参测项目…';catalogSearch.setAttribute('aria-label','搜索模型参测项目');catalogMore.type='button';catalogToolbar.append(catalogTitle,catalogSearch);catalogSection.append(catalogToolbar,catalogNote,catalogList,catalogMore);
    summary.setAttribute('role','status');sourcePanel.append(sourceSearch,summary,content);audit.append(el('summary','名称与来源说明'),auditBody);scorePanel.append(scoreContent,audit);
    const tabs=el('div',null,'model-dialog-tabs'),tabButtons=new Map(),panels=new Map([['overview',catalogSection],['sources',sourcePanel],['score',scorePanel]]);tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','模型档案内容');
    let activeTab=section==='score'?'score':'overview';
    function activateTab(key){
      activeTab=key;
      for(const [id,panel] of panels){panel.hidden=id!==key;const tab=tabButtons.get(id);tab.setAttribute('aria-selected',String(id===key));tab.tabIndex=id===key?0:-1;}
      if(key==='score'){const breakdown=scoreContent.querySelector('.score-breakdown');if(breakdown)breakdown.open=true;}
    }
    for(const [key,text] of [['overview','概览'],['sources','评测成绩'],['score',visitorEdition?'评分说明':'评分依据']]){
      const tab=el('button',text);tab.type='button';tab.id='model-tab-'+key;tab.setAttribute('role','tab');tab.setAttribute('aria-controls','model-panel-'+key);panels.get(key).id='model-panel-'+key;panels.get(key).setAttribute('role','tabpanel');panels.get(key).setAttribute('aria-labelledby',tab.id);tab.onclick=()=>activateTab(key);
      tab.addEventListener('keydown',event=>{const keys=[...panels.keys()],index=keys.indexOf(key),next=event.key==='ArrowRight'?keys[(index+1)%keys.length]:event.key==='ArrowLeft'?keys[(index+keys.length-1)%keys.length]:event.key==='Home'?keys[0]:event.key==='End'?keys.at(-1):null;if(next){event.preventDefault();activateTab(next);tabButtons.get(next).focus();}});
      tabs.append(tab);tabButtons.set(key,tab);
    }
    const scoreContext=el('p',null,'model-score-context');body.append(intro,controls,stats,scoreContext,tabs,catalogSection,sourcePanel,scorePanel);dialog.append(head,body);
    let setting=initialSetting,limit=12,openGroups=new Set();
    let catalogLimit=6;
    function drawCatalog(){
      const all=Viz.modelBenchmarkCatalog(state.snapshot,name),verified=all.filter(item=>item.verifiedRecords>0).length,query=catalogSearch.value.trim().toLocaleLowerCase(),items=all.filter(item=>[item.benchmark.benchmark_name,item.benchmark.paper_title].some(value=>String(value||'').toLocaleLowerCase().includes(query))).sort((a,b)=>Number(a.benchmark.name_audit?.status==='REVIEW_REQUIRED')-Number(b.benchmark.name_audit?.status==='REVIEW_REQUIRED'));
      catalogNote.textContent=`全部实验设置合计 ${all.length} 项评测 · ${verified} 项已有核验来源${all.length>verified?' · '+(all.length-verified)+' 项待核验':''}`;
      catalogList.replaceChildren();for(const item of items.slice(0,catalogLimit)){
        const card=el('article',null,'model-catalog-item'),copy=el('div',null,'model-catalog-copy'),a=el('a',item.benchmark.benchmark_name),action=el('a','查看评测','model-catalog-action');a.href=action.href=new URL('benchmark/?'+new URLSearchParams({paper_id:item.benchmark.paper_id,benchmark_id:item.benchmark.benchmark_id,...(state.snapshot?.visitor_catalog_filtered?{}:{edition:'admin'})}),radarBase).href;action.setAttribute('aria-label','查看 '+item.benchmark.benchmark_name+' 的评测详情');
        const meta=el('div',null,'model-catalog-evidence');copy.append(a,el('span',item.benchmark.paper_title||'来源论文','model-catalog-paper'));meta.append(el('span',`${item.records} 条来源 · ${item.comparableRecords} 条可比${item.verifiedRecords?'':' · 名称待核验'}`,'model-roster-meta'));
        const settings=el('details',null,'model-catalog-settings');settings.append(el('summary',item.settings.length+' 种实验设置'),el('p',item.settings.map(settingLabel).join('；')));meta.append(settings);copy.append(meta);card.append(copy,action);catalogList.append(card);
      }
      if(!items.length)catalogList.append(el('p',all.length?'没有匹配的 Benchmark。':'当前窗口尚无可列出的来源成绩。','model-catalog-note'));catalogMore.hidden=items.length<=catalogLimit;catalogMore.textContent=`继续显示 · 还有 ${items.length-catalogLimit} 个 Benchmark`;
    }
    catalogSearch.oninput=()=>{catalogLimit=6;drawCatalog();};catalogMore.onclick=()=>{catalogLimit+=6;drawCatalog();};sourceSearch.oninput=()=>{limit=12;draw();};
    function draw(){
      drawCatalog();
      const data=Viz.modelEvidence(state.snapshot,name),ranked=[...data.settings].sort((a,b)=>data.groups.filter(g=>g.model_setting===b).length-data.groups.filter(g=>g.model_setting===a).length);
      if(!data.settings.includes(setting))setting=ranked[0];
      select.replaceChildren();for(const value of data.settings)select.append(new Option(settingLabel(value),value));select.value=setting??'';select.disabled=!data.settings.length;
      const catalog=new Map((state.snapshot.benchmarks||[]).map(b=>[identity(b),b])),sourceName=r=>catalog.get(identity(r))?.benchmark_name||Viz.publicLabel(r.benchmark,'来源 Benchmark');
      const rows=data.sources.filter(r=>r.model_setting===setting).sort((a,b)=>sourceName(a).localeCompare(sourceName(b))||text(a.metric).localeCompare(text(b.metric))),groups=data.groups.filter(g=>g.model_setting===setting),usable=new Set(groups.flatMap(g=>g.scores.filter(s=>s.model_canonical===name).flatMap(s=>s.observation_ids||[])));
      const benchmarks=new Set(groups.map(g=>g.benchmark_identity||JSON.stringify([g.paper_id,g.benchmark_id])));
      summary.textContent=`${benchmarks.size} 个有可比成绩的 Benchmark · ${rows.length} 条来源记录 · 数据更新 ${date(state.snapshot.generated_at)}`;
      content.replaceChildren();scoreContent.replaceChildren();stats.replaceChildren();
      const scored=scopedModels().find(m=>m.model_canonical===name&&m.model_setting===setting),published=Viz.publicationScore(scored||{},state.snapshot.index.method?.min_benchmarks||3);
      for(const [value,text] of [[published,scored?.score_unit==='z_score'?'相对参考分':'综合分 · 0–100'],[scored?.scored_benchmarks??scored?.n_benchmarks??null,'计分评测'],[benchmarks.size,'可比评测'],[rows.length,'来源记录']]){const item=el('div',null,'model-stat'),number=el('strong',fmt(value));item.append(el('span',text),number);stats.append(item);}
      scoreContext.textContent=published===null?Viz.publicationLabel(scored||{}):'数据更新 '+date(state.snapshot.generated_at);

      if(scored&&visitorEdition){
        const overview=el('section',null,'visitor-score-overview');
        overview.append(el('h3','综合评分概览'),el('p',published===null?'当前实验设置尚无综合评分，可查看已有的单项评测成绩。':'综合评分汇总当前版本中的已测表现，范围为 0–100。','visitor-score-intro'));
        const facts=el('dl',null,'visitor-score-facts');
        for(const [label,value]of [['综合分',fmt(published)],['计分评测',(scored.scored_benchmarks??scored.n_benchmarks??0)+' 项'],['参考区间',published!==null&&scored.score_interval?.length===2?scored.score_interval.map(fmt).join('–'):'—']]){
          const fact=el('div');fact.append(el('dt',label),el('dd',value));facts.append(fact);
        }
        overview.append(facts);
        if(published!==null)overview.append(el('p','参考区间表示评分的不确定范围。不同模型的评测覆盖可能不同，应结合共同参测项目和原始成绩比较。','visitor-score-note'));
        const sources=el('button','查看评测成绩','visitor-score-source');sources.type='button';sources.onclick=()=>activateTab('sources');overview.append(sources);scoreContent.append(overview);
      }else if(scored){
        const breakdown=el('details',null,'explanation score-breakdown');breakdown.append(el('summary','综合评分计算明细 · '+Viz.publicationLabel(scored)));
        breakdown.addEventListener('toggle',()=>{if(!breakdown.open||breakdown.dataset.loaded)return;breakdown.dataset.loaded='true';
          if(state.snapshot.index.method?.opponent_adjusted){
            const balanced=state.snapshot.index.method.version>=5;
            breakdown.append(el('p',state.snapshot.index.method.version>=14?'综合分按核对后的任务表现、来源权重和共同对手拟合，不施加厂商或版本排序约束。干预增益、被识别对象诊断量及明确的次要实验条件不进入默认总榜，原始记录保留。':state.snapshot.index.method.version===13?'先拟合分任务与共享强度，再对同厂商重复共同证据作最小一致性校正。至少两篇独立论文持续支持且无相反共同来源时，综合分须保持该方向；循环冲突不强行排序。型号新旧不参与判断。原始记录完整保留。':state.snapshot.index.method.version>=12?'仅汇总最终任务表现。先传入已核验的任务分类，再限制每个模型在论文和评测中的来源预算；分任务联合拟合，采用温和时间衰减，不按型号版本施加排序。原始成绩保留。':state.snapshot.index.method.version>=11?'仅使用最终任务表现；提示或干预增益、统计诊断量另列。来源按模型对限权，分任务拟合并采用温和时间衰减，不施加硬排序约束。原始记录完整保留。':state.snapshot.index.method.version>=10?'按模型对分摊论文与评测来源预算，在各任务类别内分配时间权重，联合拟合任务表现和综合强度。允许任务之间的胜负交叉，不施加硬排序约束。原始成绩保留，缺测不填零。':state.snapshot.index.method.version===9?'按模型对平分来源预算，再做共同证据一致性校正：至少两篇独立论文持续支持、且共同来源没有相反方向时，综合强度不再大幅倒挂。相互冲突的约束可能得到同分。原始成绩不变，型号新旧和厂商不进入规则。':state.snapshot.index.method.version>=8?'综合分只使用跨任务共享强度。同条件成绩首先进入相应任务的专项表现，模型在各任务上的表现再通过部分共享联合校准。专项偏强或偏弱单独拟合，未测任务不伪造成绩。同一模型对的论文与评测来源预算分别封顶。':state.snapshot.index.method.version>=7?'先排除排名稳定性等派生统计，按来源任务标签平衡贡献，再利用同场原始成绩和共同对手联合拟合。双模型组无独立尺度时只作半权重的胜负比较，不声称保留连续分差大小。原始成绩和来源均保留。':balanced?'将同条件原始分差按参考标准差转换为软比较，联合利用共同对手校准。每个模型在每篇论文、每项 Benchmark 的比较权重分别不超过1，再分摊指标及对手权重。综合分只发布给覆盖合格的参考网络成员，缺测不补零。':state.snapshot.index.method.version>=4?'将完全同条件的原始分差除以同组参考标准差，再用 sigmoid 转成连续软比较，保留分差大小。通过共同对手联合拟合；每个完整参测模型在每项 Benchmark 中的总比较权重为1。正则强度0.3，缺测不补原始成绩。':'从完全相同评测条件下的原始成绩生成胜、负、平，通过共同对手联合拟合相对强度。Benchmark 内指标分摊权重；同场对手越多，每对分摊的权重越小。缺测不补零，未连接主网络的模型不混排。','method-note'),el('p',state.snapshot.index.method.version>=10?`纳入 ${scored.scored_benchmarks} 项 Benchmark · 直接对手 ${scored.direct_opponents} 个 · 综合分 ${scored.publication_score==null?'未发布':fmt(scored.publication_score)} · 约95%模型区间 ${scored.score_interval?.map(fmt).join('–')||'—'}`:state.snapshot.index.method.version===9?`纳入 ${scored.scored_benchmarks} 项 Benchmark · 直接对手 ${scored.direct_opponents} 个 · 综合分 ${scored.publication_score==null?'未发布':fmt(scored.publication_score)} · 基础拟合分 ${fmt(scored.base_publication_score)}`:`纳入 ${scored.scored_benchmarks} 项 Benchmark · 直接对手 ${scored.direct_opponents} 个 · 综合分 ${scored.publication_score==null?'未发布':fmt(scored.publication_score)} · 约95%模型区间 ${scored.score_interval?.map(fmt).join('–')||'—'} · 区间重叠相容名次 ${scored.rank_interval?.join('–')||'—'}/${scored.rank_population}`),el('p',state.snapshot.index.method.version>=14?'区间由当前分任务拟合和来源论文聚类误差计算，与柱状图分数对应。':state.snapshot.index.method.version===13?'区间对当前一致性规则和观测分差条件化，通过活跃约束的线性组合重新传播误差，并保留基础拟合误差下限。它是条件参考区间，不是无条件名次置信区间。':state.snapshot.index.method.version===9?'校正后综合分尚未估计置信区间；保留的基础拟合区间只用于审计，不画成校正分的误差线。同分不表示已证明模型能力相同。':balanced?'近似区间取正则化模型信息方差和来源论文聚类方差的较大值。同一论文里的指标不当作独立来源。它不能消除领域覆盖和选择性报告偏差。':'区间取正则化模型信息方差和 Benchmark 聚类稳健方差的较大值，是近似模型区间。相容名次按边际区间重叠计算，不是联合95%名次置信区间。中性先验强度单独记录，不是论文成绩；领域差异与选择性报告仍可能影响结果。','method-note'));
            if(state.snapshot.index.method.version>=10){
              const temporal=state.snapshot.index.method.temporal_scoring;
              if(state.snapshot.index.method.version===11)breakdown.append(el('p','中性收缩强度0.3：在真实快照中按论文与评测来源家族进行嵌套留出验证，从6个候选值中选择。验证未支持放松稀疏证据收缩；此结论限于本版数据，不保证未测任务的名次。','method-note'));
              breakdown.append(el('p',`评分基准日期 ${temporal?.as_of||'未指定'}；时间衰减半衰期 ${temporal?.half_life_days??'停用'} 天，系数下限 ${temporal?.floor??0.5}。同一评测的重复来源共用最早日期，缺失或未来日期采用下限权重。`,'method-note'),el('p','PAPER_V1_PROXY 表示论文首次提交日期代理，尚非独立核实的评测首发日期。时间参数为当前声明的策略，尚未经过长期外部验证。区间使用本次最终拟合重新计算。','method-note'));
            }
            if((state.snapshot.index.method.version===9||state.snapshot.index.method.version===13)&&scored.source_consensus){
              const correction=el('details'),c=scored.source_consensus;correction.append(el('summary','共同来源一致性校正'),el('p',`基础拟合分 ${fmt(scored.base_publication_score)} → 综合分 ${fmt(scored.publication_score)}；关联 ${c.related_rules?.length||0} 条重复来源比较约束。缺测不补零，不增加真实来源数量。`));
              for(const rule of c.related_rules||[]){const row=el('p',`${rule.winner} ≥ ${rule.loser} · ${rule.decisive_papers} 篇独立论文支持`);for(const proof of rule.sources){const g=(state.snapshot.index.groups||[]).find(g=>g.paper_id===proof.paper_id&&(g.benchmark_identity||g.benchmark_id)===proof.benchmark_identity);if(g){const a=el('a',' 来源');a.href=new URL('benchmark/?'+new URLSearchParams({paper_id:g.paper_id,benchmark_id:g.benchmark_id,...(state.snapshot?.visitor_catalog_filtered?{}:{edition:'admin'})}),radarBase).href;row.append(a);}}correction.append(row);}breakdown.append(correction);
            }
            if(scored.shared_strength_model){
              breakdown.append(el('p','下面的专项修正表示该任务拟合强度相对于跨任务共享强度的偏移，不是原始成绩或正确率；综合分由共享强度映射，并按当前版本声明的共同来源一致性规则校正。','method-note'));
              const taskNames={software:'代码',knowledge:'知识',reasoning_data:'推理与数据',language_documents:'语言与文档',visual:'视觉',agents:'交互执行',unclassified:'未分类来源'};
              const list=el('ul',null,'evidence-list');
              for(const task of scored.fitted_task_strengths||[])list.append(el('li',`${taskNames[task.task_stratum]||task.task_stratum} · ${task.benchmarks} 项 Benchmark · 专项修正 ${task.task_deviation>0?'+':''}${statFmt(task.task_deviation)}`));
              breakdown.append(list);
            }
            if(balanced)breakdown.append(el('p',`综合榜参考网络覆盖 ${scored.core_benchmarks??0} 项评测、${scored.core_source_papers??0} 篇论文；准入要求 ${state.snapshot.index.method.min_benchmarks} 项${state.snapshot.index.method.min_source_papers>1?'、'+state.snapshot.index.method.min_source_papers+' 篇来源论文':'，不另设论文篇数门槛'}。原始成绩仍可查看。`,'method-note'));
            const evidence=scored.ranking_evidence, pair=evidence?.above_comparison;
            if(evidence){
              breakdown.append(el('p',`按拟合分展示的位置：${evidence.point_estimate_position}；这是点估计顺序，不是已确定的能力名次。`,'method-note'));
              if(pair)breakdown.append(el('p',`与上方模型 ${evidence.above_model}：${pair.shared_benchmarks} 项同场 Benchmark、${pair.shared_groups} 个同条件组。`+(pair.shared_benchmarks?` 本模型按 Benchmark 汇总为 ${pair.benchmark_wins} 胜 / ${pair.benchmark_ties} 平 / ${pair.benchmark_losses} 负；这是描述性结果，不是显著性检验。`:'没有直接交手；两者分差来自共同对手的间接拟合，不能据此断言谁更强。'),'method-note'));
            }
          }else if(scored.score_unit==='composite_0_100'){
            breakdown.append(el('p','对模型已测的合格 Benchmark 等权汇总，同一 Benchmark 内指标等权。以下贡献相加得到原始加权 Z，再乘证据量系数 n/(n+3)，最后按标准正态累计概率映射到 0–100。系数表示向参考均值收缩，不是把缺测填为零。','method-note'),el('p',`纳入 ${scored.scored_benchmarks} 项 Benchmark · 原始 Z ${statFmt(scored.unshrunk_z)} · 证据系数 ${statFmt(scored.evidence_reliability)} · 收缩后 Z ${statFmt(scored.aggregate_z)} · 综合分 ${scored.publication_score==null?'证据不足':fmt(scored.publication_score)}`));
          }else breakdown.append(el('p',scored.score_unit==='z_score'?'原值减去同组参考均值，除以总体标准差；负向指标反转，再按固定权重汇总。0 为参考均值，负值不表示能力为负。只比较同一集合版本；缺项不补零。':'原始成绩按来源量程转换为 0–100，再乘固定权重。以下分项贡献相加才是综合分；缺项不补零、不重新分配权重。','method-note'));
          const displayedComponents=(scored.score_components||[]).filter(c=>!state.snapshot.visitor_catalog_filtered||catalog.has(identity(c)));
          const componentDetails=el('details',null,'model-score-components');componentDetails.append(el('summary',`逐项计分来源 · ${displayedComponents.length} 组`));
          for(const c of displayedComponents){const b=catalog.get(identity(c)),item=el('section',null,'model-source-section');item.append(el('h4',b?.benchmark_name||'来源 Benchmark'));
            if(c.score_unit==='source_pairwise_win_fraction')item.append(el('p',`${c.metric} · 原值 ${statFmt(c.raw_value)} · 同场胜率（含平局半分）${fmt(c.normalized_score*100)}% · 每对比较权重 ${statFmt(c.pair_weight)}`+(Number.isFinite(c.comparison_target)?` · 平均软比较目标 ${statFmt(c.comparison_target)} · 参考标准差 ${statFmt(c.comparison_scale_sd)}`:'')),el('p','同条件直接对手：'+c.opponents.join('、')+(c.comparison_method?' · 尺度方法：'+({SOURCE_REFERENCE_SD:'同组参考标准差',VERIFIED_QUARTER_RANGE:'核验量程的四分之一',SAME_SOURCE_PEER_SD:'同源其他评测组标准差',TWO_MODEL_ORDINAL_ONLY:'仅胜负，半权重；无连续分差尺度'}[c.comparison_method]||c.comparison_method):'')+(c.task_strata?' · 任务组：'+c.task_strata.join('、')+' · 任务权重因子 '+statFmt(c.task_balance_factor):''),'method-note'));
            else item.append(el('p',`${c.metric} · 原值 ${statFmt(c.raw_value)} → ${c.score_unit==='z_score'?'Z 分数':'标准化'} ${statFmt(c.normalized_score)} · 权重 ${fmt(c.weight*100)}% · 贡献 ${statFmt(c.contribution)}`),el('p',c.score_unit==='z_score'?`同组参考 ${c.reference_count} 个模型 · 均值 ${statFmt(c.mean)} · 总体标准差 ${statFmt(c.standard_deviation)} · ${Viz.directionLabel(c.direction)}`:`来源范围 ${c.lower_bound}–${c.upper_bound} ${c.unit} · ${Viz.directionLabel(c.direction)}`,'method-note'));
            if(c.evidence_quote)item.append(el('p',c.evidence_quote,'method-note'));const a=el('a','查看来源成绩');a.href=new URL('benchmark/?'+new URLSearchParams({paper_id:c.paper_id,benchmark_id:c.benchmark_id,...(state.snapshot?.visitor_catalog_filtered?{}:{edition:'admin'})}),radarBase).href;item.append(a);componentDetails.append(item);}
          if(displayedComponents.length)breakdown.append(componentDetails);
          if(!displayedComponents.length)breakdown.append(el('p','当前尚无通过完整核验的综合评分分项。原始成绩见下方。'));
          if(scored.missing_score_groups?.length)breakdown.append(el('p',`指定集合中还有 ${scored.missing_score_groups.length} 个分项缺失或需要重新核验，因此没有完整总分。`));
        });scoreContent.append(breakdown);
      }
      if(!rows.length)empty(content,'当前设置暂无来源记录','切换其他实验设置查看；缺失成绩不补零。');
      else{
        const query=sourceSearch.value.trim().toLocaleLowerCase(),matchingRows=rows.filter(row=>!query||[sourceName(row),row.metric,row.row_key].some(value=>String(value||'').toLocaleLowerCase().includes(query))),grouped=Viz.modelSourceGroups(matchingRows);
        if(!grouped.length)empty(content,'未检索到匹配成绩','请调整评测名称或指标关键词。');
        const ready=row=>usable.has(row.observation_id)&&row.model_verified===true&&row.comparable===true&&!row.extraction_in_progress;
        for(const group of grouped.slice(0,limit)){
          const entry=el('details',null,'model-benchmark-group'),heading=el('summary'),b=catalog.get(identity(group.rows[0])),name=el('strong',sourceName(group.rows[0])),meta=el('span',`${group.rows.length} 条来源 · ${group.rows.filter(ready).length} 条可比`,'model-group-count');
          heading.append(name,meta);entry.append(heading);entry.open=openGroups.has(group.id);entry.addEventListener('toggle',()=>{if(!entry.isConnected)return;if(entry.open)openGroups.add(group.id);else openGroups.delete(group.id);});
          const inner=el('div',null,'model-group-body'),links=el('div',null,'model-group-links'),a=el('a','查看 Benchmark');a.href=new URL('benchmark/?'+new URLSearchParams({paper_id:group.paper,benchmark_id:group.benchmark,...(state.snapshot?.visitor_catalog_filtered?{}:{edition:'admin'})}),radarBase).href;links.append(a,link(b?.paper_url,'论文来源'));inner.append(links);
          const tables=[...new Set(group.sections.map(section=>section.table))];
          for(const section of group.sections){
            const sectionBox=el('section',null,'model-source-section'),wrap=el('div',null,'table-wrap'),table=el('table'),thead=el('thead'),header=el('tr'),body=el('tbody'),conditions=group.sections.filter(s=>s.table===section.table);
            if(group.sections.length>1)sectionBox.append(el('h4',`来源表 ${tables.indexOf(section.table)+1}${conditions.length>1?' · 测试条件 '+(conditions.indexOf(section)+1):''}`));
            for(const t of ['指标 / 子任务','论文原值','证据状态'])header.append(el('th',t));thead.append(header);table.append(thead,body);wrap.append(table);sectionBox.append(wrap);
            let displayed=0;
            function appendRows(){
              const until=Math.min(displayed+40,section.rows.length);
              for(const row of section.rows.slice(displayed,until)){const tr=el('tr'),metric=el('td',row.metric||'—'),task=Viz.publicLabel(row.row_key);if(task&&task!==row.metric&&!/^(?:cell|row|column):|^\d+(?::\d+)*$/.test(task))metric.append(el('span',task,'subtext'));const status=el('td'),label=el('span',ready(row)?'可比来源':row.extraction_in_progress?'提取中':'待核验',ready(row)?'source-state verified':'source-state');status.append(label);tr.append(metric,el('td',row.value_raw??row.value_numeric??'—','numeric'),status);body.append(tr);}
              displayed=until;more.hidden=displayed>=section.rows.length;more.textContent=`继续显示 · 还有 ${section.rows.length-displayed} 条`;
            }
            const more=el('button',null,'model-source-more');more.type='button';more.onclick=appendRows;sectionBox.append(more);appendRows();inner.append(sectionBox);
          }
          entry.append(inner);content.append(entry);
        }
        if(grouped.length>limit){const more=el('button',`继续显示 · 还有 ${grouped.length-limit} 组 Benchmark`,'model-groups-more');more.type='button';more.onclick=()=>{limit+=12;draw();};content.append(more);}
      }
      if(!scored)scoreContent.append(el('p','当前实验设置尚未发布综合分。可切换设置，或查看已有评测成绩。','model-catalog-note'));
      activateTab(activeTab);
      auditBody.textContent=`来源名称：${data.aliases.join('、')}。原始数值来自论文，未独立复现；版本、规模和设置不混合。${data.identityStatus!=='SOURCE_LABEL'?'此名称的具体型号尚待核验，不参与比较排名。':''}`;
    }
    select.onchange=()=>{setting=select.value;limit=12;openGroups.clear();draw();};dialog.refresh=draw;dialog.addEventListener('close',()=>{dialog.remove();if(modelDialog===dialog)modelDialog=null;});dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}});document.body.append(dialog);modelDialog=dialog;draw();dialog.showModal();
    if(section==='score')tabButtons.get('score').focus({preventScroll:true});
  }
  const TASK_DEFAULTS = {"taxonomy":{"version":"task-taxonomy-v2","domains":[{"id":"general","label":"通用","description":"不依赖特定专业领域的任务。"},{"id":"medicine","label":"医学与健康","description":"医学文献、临床信息、健康知识。"},{"id":"law","label":"法律","description":"法律知识、合同和司法材料。"},{"id":"finance","label":"金融与商业","description":"金融、会计、经营分析。"},{"id":"software","label":"软件开发","description":"程序、软件工程和计算系统。"},{"id":"science","label":"自然科学与工程","description":"科学研究和工程专业问题。"},{"id":"education","label":"教育","description":"教学、学习与教育评估。"},{"id":"humanities","label":"人文与社会","description":"历史、文化、社会与人文专业问题。"}],"tasks":[{"id":"knowledge_qa","label":"知识问答","description":"回答有事实或专业知识依据的问题。"},{"id":"literature_review","label":"文献综述","description":"整合多篇研究、比较结论并归纳证据。"},{"id":"document_qa","label":"文档问答","description":"基于给定文档回答问题。"},{"id":"structured_extraction","label":"结构化信息提取","description":"从来源材料提取字段、实体、关系或结构化记录。"},{"id":"summarization","label":"内容摘要","description":"保持事实一致地压缩来源内容。"},{"id":"contract_review","label":"合同审查","description":"检查合同条款、识别风险和不一致。"},{"id":"code_development","label":"代码开发","description":"编写、修改、调试或测试代码。"},{"id":"data_analysis","label":"数据分析","description":"分析数据、选择统计方法并解释结果。"},{"id":"mathematical_problem_solving","label":"数学解题","description":"完成数学推导与计算。"},{"id":"visual_document_understanding","label":"图文文档理解","description":"读取图像、图表、版面或混合文档。"},{"id":"translation","label":"翻译","description":"在不同自然语言之间转换内容。"},{"id":"tool_workflow","label":"工具任务执行","description":"通过检索、软件工具或多步操作完成任务。"},{"id":"reading_comprehension","label":"阅读理解","description":"理解篇章内容、关系、指代与隐含信息。"},{"id":"writing","label":"写作","description":"生成、改写或编辑有目的的文本。"},{"id":"dialogue","label":"对话","description":"通过单轮或多轮交流回答、协作或完成任务。"},{"id":"information_retrieval","label":"信息检索","description":"从文档库或搜索环境中寻找、排序相关信息。"},{"id":"planning","label":"任务规划","description":"制定符合目标与约束的多步计划。"},{"id":"interactive_execution","label":"交互执行","description":"依据环境反馈执行、调整并完成多步任务。"}],"capabilities":[{"id":"domain_knowledge","label":"知识运用（通用/专业）","description":"测量事实或专业知识的正确性。","group":"knowledge"},{"id":"long_context","label":"长文本理解","description":"直接测量长输入中信息定位、理解或利用；长度本身不足以证明。","group":"information_context"},{"id":"cross_document_synthesis","label":"跨文档整合","description":"测量多个文档的比较、整合或冲突识别。","group":"information_context"},{"id":"citation_reliability","label":"引用可靠性","description":"直接测量引用存在性、准确性、完整性或证据支持。","group":"grounding"},{"id":"information_extraction","label":"信息抽取","description":"测量字段、实体或关系抽取的正确性。","group":"information_context"},{"id":"instruction_following","label":"指令与格式遵循","description":"直接测量指令约束或输出格式符合程度。","group":"language"},{"id":"reasoning","label":"综合推理（未细分）","description":"测量推导、多步推理或问题求解正确性。","group":"reasoning_math"},{"id":"code_correctness","label":"代码正确性","description":"通过测试、执行或明确规格测量代码功能正确性。","group":"code_data"},{"id":"statistical_reasoning","label":"统计推理","description":"测量统计方法选择、数据分析和统计结论解释。","group":"code_data"},{"id":"grounded_faithfulness","label":"来源忠实性","description":"直接测量回答或摘要与给定来源的一致性。","group":"grounding"},{"id":"multimodal_understanding","label":"多模态理解","description":"测量对图像、图表、视听或混合模态内容的理解。","group":"perception"},{"id":"multilingual_communication","label":"跨语言理解与表达","description":"直接测量跨语言理解、翻译或表达质量。","group":"cross_language"},{"id":"tool_use","label":"工具使用","description":"测量工具选择、调用和任务执行成功率。","group":"agency"},{"id":"reading_comprehension","label":"阅读理解","description":"测量篇章理解、指代、关系或隐含信息理解的正确性。","group":"language"},{"id":"summarization","label":"摘要能力","description":"测量内容压缩、要点覆盖和摘要质量；忠实性需单独证据。","group":"language"},{"id":"writing","label":"写作与生成","description":"测量文本组织、表达、改写或创作质量。","group":"language"},{"id":"dialogue","label":"对话能力","description":"测量对话响应质量、上下文衔接或交流目标完成。","group":"language"},{"id":"common_sense","label":"常识理解","description":"直接测量日常情境、物理或社会常识的运用。","group":"knowledge"},{"id":"logical_reasoning","label":"逻辑推理","description":"直接测量演绎、归纳、因果或约束推理。","group":"reasoning_math"},{"id":"mathematical_reasoning","label":"数学推理","description":"直接测量数学建模、推导、证明或问题求解。","group":"reasoning_math"},{"id":"information_retrieval","label":"信息检索","description":"测量查找、排序相关信息的质量；不等同于工具调用。","group":"information_context"},{"id":"factual_accuracy","label":"事实正确性","description":"直接测量事实陈述正确性或幻觉，而非仅与给定来源一致。","group":"grounding"},{"id":"code_debugging","label":"代码调试与修复","description":"测量定位、修复软件缺陷和通过验证的能力。","group":"code_data"},{"id":"visual_perception","label":"视觉感知","description":"直接测量对图像对象、属性及空间关系的识别。","group":"perception"},{"id":"document_chart_understanding","label":"文档与图表理解","description":"测量OCR、版面、图表或文档图像内容理解。","group":"perception"},{"id":"audio_understanding","label":"音频理解","description":"测量语音或其他音频的识别与理解。","group":"perception"},{"id":"video_understanding","label":"视频理解","description":"测量视频事件、时序及动态关系理解。","group":"perception"},{"id":"planning","label":"规划能力","description":"测量目标分解、步骤安排与约束满足；不要求调用工具。","group":"agency"},{"id":"interactive_execution","label":"多步交互执行","description":"测量依据反馈调整行动并完成任务；不能由计划文本推断。","group":"agency"},{"id":"safety","label":"安全性","description":"直接测量有害输出、危险行为或攻击防护。","group":"safety_privacy"},{"id":"privacy","label":"隐私保护","description":"直接测量敏感信息泄漏、记忆泄露或隐私侵犯。","group":"safety_privacy"},{"id":"bias","label":"偏见","description":"直接测量刻板印象、偏向或歧视性输出。","group":"fairness"},{"id":"fairness","label":"公平性","description":"直接比较群体间待遇、错误率或机会差异。","group":"fairness"},{"id":"robustness","label":"鲁棒性","description":"测量噪声、扰动、攻击或环境变化下的稳定性。","group":"robustness"},{"id":"generalization","label":"泛化能力","description":"直接测量新分布、新领域或新任务上的表现；多领域本身不足以证明。","group":"robustness"}],"modalities":[{"id":"text","label":"文本","description":"任务直接处理或生成文本。"},{"id":"image","label":"图像","description":"任务直接处理或生成静态图像，包括图表和文档图像。"},{"id":"audio","label":"音频","description":"任务直接处理或生成语音、音乐等音频。"},{"id":"video","label":"视频","description":"任务直接处理或生成视频序列。"},{"id":"structured_data","label":"结构化数据","description":"任务直接处理表格、图结构等结构化输入或输出。"}],"capability_groups":[{"id":"language","label":"语言理解与生成","description":"阅读、摘要、写作、对话及指令遵循。","kind":"ability"},{"id":"knowledge","label":"知识与常识","description":"事实知识、专业知识与日常常识。","kind":"ability"},{"id":"reasoning_math","label":"推理与数学","description":"逻辑推导和数学求解；保留未细分的旧推理标签。","kind":"ability"},{"id":"information_context","label":"检索与信息整合","description":"检索、抽取、长上下文和跨文档整合。","kind":"ability"},{"id":"grounding","label":"事实与证据可靠性","description":"事实正确、来源忠实和引用可靠性。","kind":"dimension"},{"id":"code_data","label":"代码与数据分析","description":"代码实现、修复与统计推理。","kind":"ability"},{"id":"perception","label":"感知与多模态","description":"视觉、图表、音频、视频与跨模态理解。","kind":"ability"},{"id":"cross_language","label":"多语言与跨语言","description":"跨语言理解、翻译与表达。","kind":"ability"},{"id":"agency","label":"规划与交互执行","description":"规划、工具调用和依据反馈持续执行。","kind":"ability"},{"id":"safety_privacy","label":"安全与隐私","description":"有害行为防护与隐私保护。","kind":"dimension"},{"id":"fairness","label":"偏见与公平","description":"刻板偏见及不同群体的差异与公平性。","kind":"dimension"},{"id":"robustness","label":"鲁棒性与泛化","description":"扰动、分布变化及新任务上的稳定性。","kind":"dimension"}]},"templates":{"medical-literature-review":{"schema_version":"task-profile-v1","taxonomy_version":"task-taxonomy-v2","description":"整理医学文献，比较不同研究结论，并提供可核实的引用。","domains":["medicine"],"tasks":["literature_review"],"capabilities":[{"id":"domain_knowledge","weight":0.3,"rationale":"初始模板建议，需按实际任务调整"},{"id":"long_context","weight":0.3,"rationale":"初始模板建议，需按实际任务调整"},{"id":"cross_document_synthesis","weight":0.25,"rationale":"初始模板建议，需按实际任务调整"},{"id":"citation_reliability","weight":0.15,"rationale":"初始模板建议，需按实际任务调整"}],"constraints":{"language":"any","modality":"any","knowledge_access":"any","min_context_tokens":null},"weight_basis":"user_specified","assumptions":["这是可编辑的模板权重，未经实际用户任务验证；未假定语言、工具或上下文要求。"]},"code-development":{"schema_version":"task-profile-v1","taxonomy_version":"task-taxonomy-v2","description":"编写和修改代码，通过测试验证功能，并遵循给定规格。","domains":["software"],"tasks":["code_development"],"capabilities":[{"id":"code_correctness","weight":0.6,"rationale":"初始模板建议，需按实际任务调整"},{"id":"reasoning","weight":0.25,"rationale":"初始模板建议，需按实际任务调整"},{"id":"instruction_following","weight":0.15,"rationale":"初始模板建议，需按实际任务调整"}],"constraints":{"language":"any","modality":"any","knowledge_access":"any","min_context_tokens":null},"weight_basis":"user_specified","assumptions":["这是可编辑的模板权重，未经实际用户任务验证；未假定语言、工具或上下文要求。"]},"structured-extraction":{"schema_version":"task-profile-v1","taxonomy_version":"task-taxonomy-v2","description":"从来源文档中提取信息，按指定结构输出，保留来源含义。","domains":["general"],"tasks":["structured_extraction"],"capabilities":[{"id":"information_extraction","weight":0.6,"rationale":"初始模板建议，需按实际任务调整"},{"id":"instruction_following","weight":0.2,"rationale":"初始模板建议，需按实际任务调整"},{"id":"grounded_faithfulness","weight":0.2,"rationale":"初始模板建议，需按实际任务调整"}],"constraints":{"language":"any","modality":"any","knowledge_access":"any","min_context_tokens":null},"weight_basis":"user_specified","assumptions":["这是可编辑的模板权重，未经实际用户任务验证；未假定语言、工具或上下文要求。"]}}};
  const taskState = {profile:null,revision:0,result:null,panel:'',refs:new Set(),refsInitialized:false,confirmed:null,request:null,busy:false,profileRequest:null,showAll:false};
  let taskTaxonomy = TASK_DEFAULTS.taxonomy;
  const titleFor = id => Object.values(taskTaxonomy).flatMap(x=>Array.isArray(x)?x:[]).find(x=>x.id===id)?.label||id;
  const selectedValues = id => [...$(id).selectedOptions].map(o=>o.value);
  const annotationItems = () => state.snapshot?.capability_annotations?.items||[];
  function benchTags(b,layer) {
    const labels=b.enrichment?.labels,values=labels?.supported?.[layer]||(labels?.status==='SUPPORTED'?labels[layer]:[]);
    const ids=new Set((Array.isArray(values)?values:[]).map(x=>typeof x==='string'?x:x.id).filter(Boolean));
    for(const id of b.catalog_labels?.[layer]||[])ids.add(id);
    for(const a of annotationItems().filter(x=>identity(x)===identity(b)&&x.status==='SUPPORTED'))for(const id of a[layer]||[])ids.add(id);
    return [...ids];
  }
  function taskMessage(id,message,kind='') {const n=$(id);n.textContent=message;if(id==='task-score-message')n.className='connection '+kind;}
  function dirtyTask() {
    if(taskState.profileRequest)taskMessage('profile-message','任务要求已修改，已停止等待旧分析；可直接调整能力与权重。');
    taskState.revision++;taskState.request?.abort();taskState.profileRequest?.abort();taskState.result=null;taskState.confirmed=null;
    $('task-results').hidden=true;taskMessage('task-score-message','任务画像已修改，请重新计算，避免沿用旧任务分。');
    scheduleCandidatePreview();
  }
  function editorProfile(allowEmptyDescription=false) {
    const description=$('task-description').value.trim();if(!description&&!allowEmptyDescription)throw Error('请先描述任务。');
    const items=[...$('capability-weights').querySelectorAll('.weight-row')].filter(n=>n.querySelector('[type=checkbox]').checked).map(n=>({id:n.dataset.capability,points:Number(n.querySelector('[type=range]').value),rationale:n.querySelector('small').textContent||'用户确认的任务能力要求'}));
    const sum=items.reduce((n,x)=>n+x.points,0);if(!sum||items.some(x=>x.points<=0))throw Error('至少选一项能力，并设置大于 0 的权重。');
    let used=0;const capabilities=items.map((x,i)=>{const weight=i===items.length-1?1-used:x.points/sum;used+=weight;return {id:x.id,weight,rationale:x.rationale};});
    const context=$('constraint-context').value; if(context&&(!Number.isInteger(Number(context))||Number(context)<1))throw Error('上下文要求应为正整数。');
    return {schema_version:'task-profile-v1',taxonomy_version:taskTaxonomy.version,description,domains:selectedValues('task-domains'),tasks:selectedValues('task-types'),capabilities,
      constraints:{language:$('constraint-language').value,modality:$('constraint-modality').value,knowledge_access:$('constraint-access').value,min_context_tokens:context?Number(context):null},
      weight_basis:'user_specified',assumptions:taskState.profile?.assumptions||['权重由用户确认，尚未通过实际任务验证。']};
  }
  function updateWeights() {
    const rows=[...$('capability-weights').children],sum=rows.filter(n=>n.querySelector('[type=checkbox]').checked).reduce((v,n)=>v+Number(n.querySelector('[type=range]').value),0);
    let active=0;for(const row of rows){const checked=row.querySelector('[type=checkbox]').checked,range=row.querySelector('[type=range]');active+=checked?1:0;row.hidden=!checked&&!taskState.showAll;row.classList.toggle('active',checked);range.disabled=!checked;range.style.setProperty('--weight-fill',((Number(range.value)-1)/99*100)+'%');const percent=checked&&sum?fmt(Number(range.value)/sum*100)+'%':'—';row.querySelector('output').textContent=percent;range.setAttribute('aria-valuetext',checked?'归一化权重 '+percent:'未选择');}
    $('toggle-capabilities').textContent=taskState.showAll?'收起未选能力 −':`添加其他能力 + · ${rows.length-active} 项`;$('toggle-capabilities').setAttribute('aria-expanded',String(taskState.showAll));
    $('capability-weights').classList.toggle('show-all',taskState.showAll);
    $('weight-count').textContent=`${active} 项已选`;
    $('weight-summary').textContent=active?'权重合计 100%':'请选择至少一项能力';
  }
  function syncProfilePickers() {
    for(const id of ['task-domains','task-types']){
      const select=$(id),picker=$(id+'-picker'),options=picker.querySelector('.picker-options');
      if(!options.children.length)for(const option of select.options){
        const label=el('label',null,'picker-option'),check=el('input');check.type='checkbox';check.value=option.value;
        label.append(check,el('span',option.textContent));options.append(label);
        check.addEventListener('change',()=>{option.selected=check.checked;dirtyTask();syncProfilePickers();});
      }
      for(const check of options.querySelectorAll('input'))check.checked=[...select.selectedOptions].some(o=>o.value===check.value);
      const names=[...select.selectedOptions].map(o=>o.textContent),values=picker.querySelector('.picker-values');
      values.textContent=names.length?names.join('、'):'请选择，可多选';values.classList.toggle('is-empty',!names.length);values.title=names.join('、');
    }
  }
  function applyProfile(p) {
    if(!p||p.schema_version!=='task-profile-v1'||p.taxonomy_version!==taskTaxonomy.version||!Array.isArray(p.capabilities)||!p.capabilities.length)throw Error('方案格式或标签版本不匹配。');
    taskState.profile=structuredClone(p);dirtyTask();$('task-description').value=p.description;
    for(const [id,key] of [['task-domains','domains'],['task-types','tasks']]){for(const opt of $(id).options)opt.selected=(p[key]||[]).includes(opt.value);$(id).scrollTop=0;}syncProfilePickers();
    for(const key of ['language','modality']){const select=$('constraint-'+key);if(![...select.options].some(o=>o.value===p.constraints[key])){const o=el('option',p.constraints[key]);o.value=p.constraints[key];select.append(o);}select.value=p.constraints[key];}
    $('constraint-access').value=p.constraints.knowledge_access;$('constraint-context').value=p.constraints.min_context_tokens??'';
    const box=$('capability-weights');box.replaceChildren();
    for(const cap of taskTaxonomy.capabilities){
      const matched=p.capabilities.find(c=>c.id===cap.id),row=el('div',null,'weight-row');row.dataset.capability=cap.id;
      const heading=el('div',null,'weight-heading'),check=el('input'),label=el('label',cap.label),output=el('output');
      check.type='checkbox';check.id='cap-'+cap.id;check.checked=!!matched;label.htmlFor=check.id;
      const info=el('details',null,'weight-info'),infoToggle=el('summary','i');infoToggle.setAttribute('aria-label',cap.label+'说明');info.append(infoToggle,el('small',matched?.rationale||cap.description));heading.append(check,label,info);
      const range=el('input');range.type='range';range.min='1';range.max='100';range.value=String(Math.max(1,Math.round((matched?.weight||.1)*100)));range.setAttribute('aria-label',cap.label+'权重');
      const adjust=el('div',null,'weight-adjust');output.htmlFor=range.id='weight-'+cap.id;adjust.append(range,output);row.append(heading,adjust);
      for(const n of [check,range])n.addEventListener('input',()=>{dirtyTask();updateWeights();});box.append(row);
    }
    $('profile-assumptions').textContent=(p.assumptions||[]).join(' ');updateWeights();
    taskMessage('profile-message',p.weight_basis==='llm_proposed'?'模型已建议能力标签与权重，请确认并调整后计算。':['user_specified','user_confirmed'].includes(p.weight_basis)?'已载入任务方案；能力与权重可继续调整。':'已载入可编辑任务模板；按实际工作调整能力与权重。');
  }
  const jobStorageKey = kind => 'model-evaluation-pending:'+radarBase.href+':'+kind;
  const jobMessages={task_profile_auth_failed:'模型接口鉴权失败，请检查服务端密钥；也可以手动调整能力与权重。',task_profile_quota_exceeded:'模型接口额度不足；可以先手动配置任务并计算。',task_profile_rate_limited:'模型接口正在限流，请稍后重试，或直接手动配置。',task_profile_request_rejected:'模型接口不接受当前模型或请求参数，请检查服务端配置；可先手动配置任务。',task_profile_invalid_response:'模型返回的能力建议未通过格式或约束核验；可重试分析或直接手动配置。',task_profile_unavailable:'模型接口暂不可用；当前任务描述已保留，可以手动配置后计算。',result_capacity_exceeded:'本次结果过大，请减少候选模型或能力范围后重试。',snapshot_refreshing:'评分证据已更新，请重新计算。',snapshot_initializing:'后台证据尚未就绪，请稍后计算。',task_profile_timeout:'模型分析超时；可以手动调整能力与权重。',task_score_busy:'相同评分正在计算，请稍后重试。',interactive_queue_full:'当前计算队列已满，请稍后提交。',job_expired_or_unknown:'后台任务已过期或服务已重启，请重新提交。'};
  const backgroundStatus={profile:null,score:null};
  const readPending=kind=>{try{const p=JSON.parse(sessionStorage.getItem(jobStorageKey(kind)));if(!p||!p.payload||typeof p.payload!=='object'||Array.isArray(p.payload))return null;const hasId=typeof p.id==='string'&&/^[A-Za-z0-9_-]{43}$/.test(p.id),hasRequest=typeof p.request_id==='string'&&/^[A-Za-z0-9_-]{32,64}$/.test(p.request_id)&&Number.isFinite(p.created_at)&&Date.now()-p.created_at>=0&&Date.now()-p.created_at<900000;return hasId||hasRequest?p:null;}catch{return null;}};
  const forgetPending=kind=>{try{sessionStorage.removeItem(jobStorageKey(kind));}catch{}};
  async function jobFetch(path,options={},parent=null) {
    const ctrl=new AbortController(),abort=()=>ctrl.abort();if(parent?.aborted)ctrl.abort();else parent?.addEventListener('abort',abort,{once:true});
    const timer=setTimeout(abort,15000);
    try{const response=await fetch(new URL(path,radarBase),{...options,signal:ctrl.signal,cache:'no-store'});let d;try{d=await response.json();}catch{throw Error('任务接口返回格式不正确。');}if(!response.ok){const error=Error(jobMessages[d.error]||'后台任务暂不可用，请稍后重试。');error.code=d.error;throw error;}return d;}
    finally{clearTimeout(timer);parent?.removeEventListener('abort',abort);}
  }
  const pauseJob=signal=>new Promise((resolve,reject)=>{const abort=()=>{clearTimeout(t);signal.removeEventListener('abort',abort);reject(new DOMException('Cancelled','AbortError'));};const t=setTimeout(()=>{signal.removeEventListener('abort',abort);resolve();},1500);if(signal.aborted)abort();else signal.addEventListener('abort',abort,{once:true});});
  async function taskPost(route,payload,ctrl) {
    const kind=route==='api/task-profile'?'profile':'score';let saved=readPending(kind),id=null;
    if(saved&&JSON.stringify(saved.payload)!==JSON.stringify(payload)){if(saved.id)jobFetch('api/interactive-jobs/'+saved.id,{method:'DELETE'}).catch(()=>{});forgetPending(kind);saved=null;}
    const cancel=()=>{if(id)jobFetch('api/interactive-jobs/'+id,{method:'DELETE'}).catch(()=>{});forgetPending(kind);backgroundStatus[kind]=null;};
    ctrl.signal.addEventListener('abort',cancel,{once:true});
    try{
      const intent=saved||{request_id:crypto.randomUUID(),created_at:Date.now(),payload};let recoverable=false;
      try{sessionStorage.setItem(jobStorageKey(kind),JSON.stringify(intent));recoverable=true;}catch{}
      let job=intent.id?await jobFetch('api/interactive-jobs/'+intent.id,{},ctrl.signal):await jobFetch('api/interactive-jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,payload,request_id:intent.request_id})},ctrl.signal);
      id=job.id;if(ctrl.signal.aborted){cancel();throw new DOMException('Cancelled','AbortError');}
      try{sessionStorage.setItem(jobStorageKey(kind),JSON.stringify({...intent,id}));}catch{recoverable=false;}
      for(;;){
        if(job.state==='COMPLETE'){forgetPending(kind);backgroundStatus[kind]=null;return job.result;}
        if(['FAILED','CANCELLED'].includes(job.state)){forgetPending(kind);throw Error(jobMessages[job.error]||'任务未完成；请检查要求或稍后重试。');}
        const message=job.state==='QUEUED'?`已排队 · 前方 ${Math.max(0,(job.position||1)-1)} 个任务`:`${kind==='profile'?'正在分析能力需求':'正在匹配证据并计算'} · 已运行 ${job.elapsed_seconds||0} 秒`;
        const status=message+(recoverable?' · 刷新页面可继续查看':' · 浏览器无法保存恢复记录，请保持页面打开');backgroundStatus[kind]=status;taskMessage(kind==='profile'?'profile-message':'task-score-message',status);
        await pauseJob(ctrl.signal);job=await jobFetch('api/interactive-jobs/'+id,{},ctrl.signal);
      }
    }catch(e){if(e.code==='job_expired_or_unknown')forgetPending(kind);throw e;}finally{ctrl.signal.removeEventListener('abort',cancel);backgroundStatus[kind]=null;}
  }
  let resumedInteractive=false;
  function resumeInteractive() {
    if(resumedInteractive||!taskEvidenceSnapshot())return;resumedInteractive=true;if(taskState.revision>1)return;
    const profile=readPending('profile'),score=readPending('score');
    if(profile){$('task-description').value=profile.payload.description;setView('tasks');analyseTask();}
    else if(score){applyProfile(score.payload.profile);taskState.refs=new Set(score.payload.candidate_models||[]);taskState.candidateMode=Array.isArray(score.payload.candidate_models)?'custom':'all';taskState.refsInitialized=true;renderReferences();setView('tasks');scoreTask(false,score.payload);}
  }
  function taskEvidenceSnapshot(){
    return state.snapshot&&state.snapshot.detail_loaded!==false?state.snapshot:taskState.evidenceSnapshot||null;
  }
  let taskEvidenceInFlight;
  function loadTaskEvidenceForPreview(){
    if(taskEvidenceSnapshot())return Promise.resolve(taskEvidenceSnapshot());
    if(taskEvidenceInFlight)return taskEvidenceInFlight;
    taskEvidenceInFlight=(async()=>{
      if(window.RadarLoadTaskEvidence){
        const data=await window.RadarLoadTaskEvidence();
        taskState.evidenceSnapshot=data.snapshot;
        window.RadarTaskMeasurements=data.measurements;Viz.setTaskMeasurements(data.measurements);
        if(state.snapshot?.detail_loaded===false)Viz.setModelRegistry(data.snapshot.model_registry);
      }else await refresh({details:true});
      if(!taskEvidenceSnapshot())throw Error('候选模型尚未加载，请重新读取。');
      renderReferences();resumeInteractive();return taskEvidenceSnapshot();
    })().finally(()=>{taskEvidenceInFlight=null;});
    return taskEvidenceInFlight;
  }
  async function ensureTaskEvidence(){
    await loadTaskEvidenceForPreview();await ensureTaskMeasurements();
  }
  async function ensureTaskMeasurements(){
    if(window.RadarTaskConnection){await window.RadarTaskConnection.connect();Viz.setTaskMeasurements(window.RadarTaskMeasurements||null);return;}
    if(window.RadarTaskMeasurements&&window.RadarTaskMeasurements.snapshot_id===state.snapshot?.snapshot_id)return;
    const ctrl=new AbortController(),timer=setTimeout(()=>ctrl.abort(),15000);
    try{
      const response=await fetch(new URL('api/task-measurements',radarBase),{cache:'no-store',signal:ctrl.signal});
      if(!response.ok)throw Error('任务指标核验数据暂不可用，请更新服务后重试。');
      const metadata=await response.json();
      if(!['source-scoped-task-measurements-v2','source-scoped-task-measurements-v3'].includes(metadata.schema_version)||metadata.snapshot_id!==state.snapshot.snapshot_id)throw Error('任务指标核验与当前数据版本不同，请重新读取。');
      window.RadarTaskMeasurements=metadata;Viz.setTaskMeasurements(metadata);
    }finally{clearTimeout(timer);}
  }
  async function analyseTask() {
    const description=$('task-description').value.trim();if(!description){taskMessage('profile-message','请先填写具体任务。');return;}
    loadTaskEvidenceForPreview().catch(error=>taskMessage('task-score-message',error.message,'warning'));
    dirtyTask();const rev=taskState.revision,ctrl=new AbortController(),started=performance.now();taskState.profileRequest=ctrl;$('analyse-task').disabled=true;$('cancel-task-analysis').hidden=false;
    const progress=()=>{if(rev!==taskState.revision)return;if(backgroundStatus.profile){taskMessage('profile-message',backgroundStatus.profile);return;}const seconds=Math.floor((performance.now()-started)/1000);taskMessage('profile-message',seconds<15?`正在分析能力需求 · 已等待 ${seconds} 秒`:`模型回复较慢 · 已等待 ${seconds} 秒。可以取消等待，直接调整右侧能力与权重。`);};progress();const ticker=setInterval(progress,1000);
    try{const d=await taskPost('api/task-profile',{description},ctrl,65000);if(rev!==taskState.revision)return;applyProfile(d.profile);taskMessage('profile-message',`能力建议已就绪 · 请求耗时 ${((performance.now()-started)/1000).toFixed(1)} 秒。请确认能力与权重后计算。`);}
    catch(e){if(rev===taskState.revision)taskMessage('profile-message',e.name==='AbortError'?'模型响应超时，尚未生成建议。可直接编辑能力与权重，或稍后重试。':e.message);}
    finally{clearInterval(ticker);if(taskState.profileRequest===ctrl)taskState.profileRequest=null;$('analyse-task').disabled=false;$('cancel-task-analysis').hidden=true;}
  }
  function setCandidateSelection(mode,names=[]) {
    dirtyTask();taskState.candidateMode=mode;taskState.refs=new Set(names);taskState.refsInitialized=true;
    renderReferences();taskMessage('task-score-message','对比清单已更新，点击计算查看当前任务的相关评测。');
  }
  let candidatePreviewTimer;
  function scheduleCandidatePreview(){clearTimeout(candidatePreviewTimer);candidatePreviewTimer=setTimeout(()=>{if(state.snapshot)renderReferences();},180);}
  function candidateContext(){let profile;try{profile=editorProfile(true);}catch{profile=null;}return Viz.taskMatchPreview(taskEvidenceSnapshot(),profile);}
  function filteredCandidates(preview=candidateContext()){
    const scope=$('reference-scope').value,vendor=$('reference-vendor').value,query=$('reference-search').value.trim(),order=$('reference-model-order').value;
    const rows=preview.rows.filter(r=>(scope!=='task'||r.nTaskBenchmarks>0)&&(scope!=='selected'||taskState.candidateMode==='all'||taskState.refs.has(r.name))&&(!vendor||Viz.modelInfo(r.name).vendor===vendor)&&Viz.matchesModelQuery(r,query));
    return order==='task'?Viz.sortTaskCandidates(rows):Viz.sortModelChoices(rows,order);
  }
  function revealTaskRequirements(target='task-domains-picker') {
    const node=$(target);for(let parent=node.parentElement;parent;parent=parent.parentElement)if(parent.tagName==='DETAILS')parent.open=true;
    if(node.tagName==='DETAILS')node.open=true;node.scrollIntoView({block:'center',behavior:'smooth'});(node.querySelector('summary')||node).focus({preventScroll:true});
  }
  function showAllCandidateModels(){
    $('reference-search').value='';$('reference-vendor').value='';$('reference-scope').value='all';
    $('reference-scope').dispatchEvent(new Event('change',{bubbles:true}));
  }
  const candidateEmptyReasons={
    DOMAIN_FILTER:'当前领域没有匹配的已标注成绩；其他领域存在相关能力评测。可检查第二步的领域选择。',
    MODALITY_FILTER:'当前输入模态没有匹配的已核验成绩。可检查第二步的实验条件。',
    UNVERIFIED_PROTOCOL:'现有来源无法核实你要求的语言、知识访问或上下文条件，因此暂不纳入任务评分。',
    NO_CAPABILITY_EVIDENCE:'当前来源暂无可用于所选能力计分的指标。可检查能力选择，或浏览全部有成绩的模型。',
    NO_COMPARABLE_MODELS:'完整评测数据尚未就绪，请等待加载完成后重试。'
  };
  function renderReferences() {
    if(!taskEvidenceSnapshot()){
      $('candidate-context').replaceChildren(el('strong','正在加载评测与候选模型'),el('small','正在读取任务所需的评测与候选模型。'));
      const retry=el('button','重新读取候选模型');retry.type='button';retry.disabled=Boolean(taskEvidenceInFlight);retry.addEventListener('click',()=>loadTaskEvidenceForPreview().catch(error=>taskMessage('task-score-message',error.message,'warning')));
      $('reference-models').replaceChildren(el('p','正在读取真实评测数据…','candidate-empty'),retry);
      $('reference-visible-count').textContent='加载中';$('reference-count').textContent='候选模型加载中';
      $('reference-top').disabled=true;$('reference-all').disabled=true;$('score-task').disabled=true;return;
    }
    const previousScroll=$('reference-models').scrollTop,selectedScroll=$('reference-selected').scrollTop;
    const activeName=$('reference-models').contains(document.activeElement)?document.activeElement?.value:null;
    const preview=candidateContext(),rows=preview.rows,allNames=rows.map(r=>r.name),known=new Set(allNames);
    const suggested=rows.filter(r=>r.nTaskBenchmarks);if(!taskState.refsInitialized&&suggested.length){taskState.refs=new Set(Viz.sortTaskCandidates(suggested).slice(0,6).map(r=>r.name));taskState.candidateMode='custom';taskState.refsInitialized=true;}
    taskState.candidateMode=taskState.candidateMode||'custom';taskState.refs=new Set([...taskState.refs].filter(n=>known.has(n)));
    const context=$('candidate-context');context.replaceChildren();
    context.append(el('strong',!preview.configured?'先选择任务能力，查看相关模型':!preview.benchmarks?'当前条件未匹配到相关评测':`${preview.matchScope==='RELATED_CAPABILITIES_ONLY'?'相近能力参考':'当前任务已匹配'} ${preview.benchmarks} 项 Benchmark`));
    if(preview.configured&&!preview.benchmarks){context.append(el('small',candidateEmptyReasons[preview.emptyReason]||candidateEmptyReasons.NO_CAPABILITY_EVIDENCE));}
    else if(preview.matchScope==='RELATED_CAPABILITIES_ONLY')context.append(el('small','暂无同类型任务成绩，当前展示相关领域与能力的参考；计算结果会保留此标记。'));
    const caps=el('div',null,'candidate-capability-hints');
    for(const c of preview.capabilities){const tag=el('span',`${titleFor(c.id)} · ${c.nBenchmarks} 项`,c.nBenchmarks?'candidate-cap-found':'candidate-cap-gap');tag.title=`任务权重 ${fmt(c.weight*100)}%`;caps.append(tag);}context.append(caps);
    if(preview.protocolUnknown&&preview.benchmarks)context.append(el('small','实验条件仍需来源核验。'));
    const vendorSelect=$('reference-vendor'),vendor=vendorSelect.value,vendors=new Map(),scope=$('reference-scope').value;
    const scoped=rows.filter(r=>(scope!=='task'||r.nTaskBenchmarks)&&(scope!=='selected'||taskState.candidateMode==='all'||taskState.refs.has(r.name)));
    for(const r of scoped){const v=Viz.modelInfo(r.name).vendor;vendors.set(v,(vendors.get(v)||0)+1);}
    vendorSelect.replaceChildren();const all=el('option','全部厂商');all.value='';vendorSelect.append(all);
    for(const [v,n] of [...vendors].sort((a,b)=>a[0].localeCompare(b[0]))){const o=el('option',v+' · '+n);o.value=v;vendorSelect.append(o);}vendorSelect.value=vendors.has(vendor)?vendor:'';
    const filtered=filteredCandidates(preview),limit=taskState.candidateLimit||48,box=$('reference-models');box.replaceChildren();
    for(const r of filtered.slice(0,limit)){
      const info=Viz.modelInfo(r.name),label=el('label',null,'candidate-option'),input=el('input');input.type='checkbox';input.value=r.name;input.checked=taskState.candidateMode==='all'||taskState.refs.has(r.name);
      input.addEventListener('change',()=>{const selected=taskState.candidateMode==='all'?new Set(allNames):new Set(taskState.refs);if(input.checked)selected.add(r.name);else selected.delete(r.name);setCandidateSelection('custom',selected);});
      const body=el('span',null,'candidate-option-body'),dot=el('i',null,'candidate-vendor-dot');dot.style.background=Viz.modelColor(r.name);const heading=el('span',null,'candidate-model-name');heading.append(dot,el('strong',r.name));
      body.append(heading,el('small',info.vendor),el('span',r.nTaskBenchmarks?`当前任务 ${r.nTaskBenchmarks} 项 · 覆盖 ${r.taskCapabilities.length} 项能力`:'当前任务暂无匹配成绩',r.nTaskBenchmarks?'candidate-task-count':'candidate-no-task'),el('small',`全部可比评测 ${r.nBenchmarks} 项`));label.append(input,body);box.append(label);
    }
    if(!filtered.length){
      box.append(el('p',scope==='task'?(candidateEmptyReasons[preview.emptyReason]||'当前搜索或厂商筛选下没有相关模型。'):'当前搜索或厂商筛选下没有模型。','candidate-empty'));
      const actions=el('div',null,'candidate-empty-actions'),browse=el('button','查看全部有成绩的模型');browse.type='button';browse.addEventListener('click',showAllCandidateModels);actions.append(browse);
      if(!preview.benchmarks){const adjust=el('button','调整任务条件');adjust.type='button';adjust.addEventListener('click',()=>revealTaskRequirements(preview.emptyReason==='DOMAIN_FILTER'?'task-domains-picker':preview.emptyReason==='NO_CAPABILITY_EVIDENCE'?'capability-weights':'constraint-language'));actions.append(adjust);}box.append(actions);
    }
    $('reference-top').disabled=!filtered.some(r=>r.nTaskBenchmarks);$('reference-all').disabled=!filtered.length;
    if(!taskState.busy)$('score-task').disabled=preview.configured&&!preview.benchmarks;
    const noTaskEvidence=preview.configured&&!preview.benchmarks,emptyMessage='当前条件没有相关评测，暂不能计算任务参考分。浏览全部模型不会自动放宽任务条件。';
    if(noTaskEvidence&&!taskState.busy)taskMessage('task-score-message',emptyMessage,'warning');
    else if(taskState.candidateWasEmpty&&$('task-score-message').textContent===emptyMessage)taskMessage('task-score-message','已找到相关成绩，请选择模型后计算任务参考分。');
    taskState.candidateWasEmpty=noTaskEvidence;
    box.scrollTop=previousScroll;if(activeName)for(const input of box.querySelectorAll('input'))if(input.value===activeName)input.focus({preventScroll:true});
    $('reference-visible-count').textContent=`${Math.min(filtered.length,limit)} / ${filtered.length}`;$('reference-more').hidden=filtered.length<=limit;
    const chosen=taskState.candidateMode==='all'?rows:rows.filter(r=>taskState.refs.has(r.name));
    $('reference-count').textContent=`已选 ${chosen.length} 个 · ${chosen.filter(r=>r.nTaskBenchmarks>0).length} 个有相关成绩`;
    $('reference-selected-count').textContent=chosen.length;$('reference-all').setAttribute('aria-pressed',String(filtered.length>0&&filtered.every(r=>taskState.candidateMode==='all'||taskState.refs.has(r.name))));
    const selectedBox=$('reference-selected');selectedBox.replaceChildren();
    if(taskState.candidateMode==='all')selectedBox.append(el('p','当前比较全部可比模型。点击“清空选择”后，可自行添加。','candidate-empty'));
    const visibleChosen=taskState.candidateMode==='all'?[]:chosen.slice(0,taskState.showSelectedAll?chosen.length:12);
    for(const r of visibleChosen){const item=el('div',null,'candidate-selected-item'),body=el('div');body.append(el('strong',r.name),el('small',r.nTaskBenchmarks?`当前任务 ${r.nTaskBenchmarks} 项 · 能力权重覆盖 ${fmt(r.capabilityWeightCoverage*100)}%`:'该模型暂无当前任务相关成绩',r.nTaskBenchmarks?'':'candidate-no-task'));const remove=el('button','×','candidate-remove');remove.type='button';remove.setAttribute('aria-label','移除 '+r.name);remove.addEventListener('click',()=>{const next=new Set(taskState.refs);next.delete(r.name);setCandidateSelection('custom',next);});item.append(body,remove);selectedBox.append(item);}
    if(taskState.candidateMode!=='all'&&!chosen.length)selectedBox.append(el('p','点击左侧模型添加，也可以按当前任务覆盖选取最多 6 个模型。','candidate-empty'));
    if(taskState.candidateMode!=='all'&&chosen.length>12){const more=el('button',taskState.showSelectedAll?'收起清单':`展开其余 ${chosen.length-12} 个`,'candidate-more');more.type='button';more.addEventListener('click',()=>{taskState.showSelectedAll=!taskState.showSelectedAll;renderReferences();});selectedBox.append(more);}selectedBox.scrollTop=selectedScroll;
  }
  async function scoreTask(auto=false,resumePayload=null) {
    if(taskState.busy)return;if(!state.snapshot){taskMessage('task-score-message','数据尚未连接，暂时无法计算任务评分。','warning');return;}
    try{await ensureTaskEvidence();}catch(error){taskMessage('task-score-message',error.message,'warning');return;}
    let profile;try{profile=auto?taskState.confirmed.profile:editorProfile();}catch(e){taskMessage('task-score-message',e.message,'warning');return;}
    if(!resumePayload&&taskState.candidateMode!=='all'&&!taskState.refs.size){taskMessage('task-score-message','请先选择至少一个模型，或点击“选择筛选结果”。','warning');return;}
    const payload=resumePayload||{profile,reference_models:[],...(taskState.candidateMode!=='all'?{candidate_models:[...taskState.refs].sort()}:{})},rev=taskState.revision,ctrl=new AbortController();taskState.request=ctrl;taskState.busy=true;$('cancel-task-score').hidden=false;taskState.result=null;$('task-results').hidden=true;$('score-task').disabled=true;taskMessage('task-score-message',auto?'窗口更新，正在重新匹配任务证据…':'正在匹配来源能力标签并计算任务分… 此步骤不调用模型。');
    try{const d=await taskPost('api/task-score',payload,ctrl,22000);if(rev!==taskState.revision)return;if(!d.task_index||!d.window||!Array.isArray(d.task_index.models))throw Error('任务评分响应不完整。');taskState.result=d;taskState.confirmed=payload;taskState.evidenceRevision=taskEvidenceSnapshot()?.status?.task_evidence_revision;renderTaskResults();if(!auto)$('task-score-message').scrollIntoView({block:'start',behavior:'smooth'});}
    catch(e){if(rev===taskState.revision){taskState.result=null;$('task-results').hidden=true;taskMessage('task-score-message',e.name==='AbortError'?'计算超时，当前未展示旧分数，请重试。':e.message,'error');}}
    finally{taskState.busy=false;$('cancel-task-score').hidden=true;if(taskState.request===ctrl)taskState.request=null;$('score-task').disabled=false;}
  }
  const gapNames={source_caption_reports_annotation_agreement:'来源说明为标注一致性，不能作为模型成绩',source_value_outside_declared_percentage:'原始值超出来源声明的百分制范围',model_size_not_established_by_source_label:'来源型号未明确该参数规模',ambiguous_source_model_identity:'来源型号指代不明确',source_subset_not_established:'来源子领域尚未明确',auxiliary_or_diagnostic_measurement:'辅助或诊断指标，保留原始记录',mixed_descriptive_or_missingness_diagnostic:'混合描述指标或缺测诊断',insufficient_source_valid_models:'当前组可核验的型号不足以比较',summarizer_or_compaction_not_coding_agent:'摘要或压缩表现，另列辅助结果',metric_meaning_not_established_by_source_caption:'指标含义尚未明确，保留原始结果',other_domain_or_mixed_domain_result:'其他领域或跨领域总分',verifier_component_not_overall_coding_outcome:'验证器分项统计，保留来源详情',no_metric_level_task_binding:'指标与当前任务分项尚无明确对应',missing_verified_score_scale:'指标量程尚未核验',unapproved_score_scale:'指标量程尚未审核通过',value_outside_verified_scale:'原始值超出核验量程',conflicting_score_scales:'指标量程证据冲突',score_scale_source_mismatch:'量程证据与当前来源不符',score_scale_direction_mismatch:'指标方向与量程不符',unverified_score_scale_quote:'量程引句未通过来源核验',unannotated_source_groups:'部分来源能力标签缺失或无效，总分暂不发布',incomplete_direct_task_panel:'直接任务证据不完整',insufficient_independent_benchmarks:'独立来源 Benchmark 不足',missing_target_observation:'候选模型缺测',missing_reference_observation:'参考模型缺测',no_capability_evidence:'该能力无匹配证据',unknown_direction:'指标方向不明',protocol_mismatch:'实验条件不匹配',domain_mismatch:'领域不匹配',capability_not_requested:'任务未要求该能力'};
  function renderTaskResults() {
    const response=taskState.result;if(!response)return;const report=response.task_index,catalog=report.method?.name==='catalog_task_pairwise_reference',calibrated=catalog&&report.method.version>=3&&report.method.version<5;
    if(!report.method){$('task-results').hidden=true;taskMessage('task-score-message',report.note||'当前任务配置或证据不足，暂无法计算。','warning');return;}
    if(!catalog&&(report.method?.name!=='task_source_fixed_scale_weighted'||report.method.version<3)){$('task-results').hidden=true;taskMessage('task-score-message','服务端评分方法尚未更新，请更新后端后重新计算。','warning');return;}
    taskMessage('task-score-message',report.available?(calibrated?(report.match_scope==='RELATED_CAPABILITIES_ONLY'?'没有同类型任务成绩，以下仅为相近能力参考。':'已匹配来源证据并校准对手；待测能力的估计比例单列。'):(catalog?'已按有来源的 Benchmark 标签匹配任务，参考分与证据覆盖已列出。':'已按当前窗口计算。只有证据覆盖与独立来源要求均满足时发布任务总分。')):report.note||'当前没有足够的任务证据。',report.available?'':'warning');
    $('task-results').hidden=false;$('task-result-meta').textContent=`窗口 ${response.window.days} 天 · 快照截止 ${date(response.generated_at)} · 计算时间 ${date(report.computed_at||response.generated_at)} · 评分方法：${catalog?(calibrated?'任务参考 · 对手校准与完整权重':'任务相关评测 · 已覆盖能力加权参考分'):'原始成绩固定量程加权'}${report.annotation_scope==='AUDITED_SUBSET_ONLY'?' · 能力图仅代表已标注证据子集，来源标签仍有缺口':''}${response.evidence_stale?' · 后台证据更新较慢，请结合来源核验时间查看':''}${response.evidence_generated_at?' · 来源核验 '+date(response.evidence_generated_at):''}${state.snapshot?.status?.preview_note?' · '+state.snapshot.status.preview_note:''}`;
    $('broaden-task-evidence').hidden=!calibrated||report.match_scope!=='SAME_TASK';
    const panels=[...new Set(report.models.map(m=>m.panel_id))].sort((a,b)=>{const am=report.models.filter(m=>m.panel_id===a),bm=report.models.filter(m=>m.panel_id===b),x=am[0]?.model_setting||'',y=bm[0]?.model_setting||'';const ar=am[0]?.measurement_facets?.[0]?.startsWith('related_reference:')||false,br=bm[0]?.measurement_facets?.[0]?.startsWith('related_reference:')||false;return Number(ar)-Number(br)||Number(Boolean(x))-Number(Boolean(y))||x.localeCompare(y)||bm.length-am.length||a.localeCompare(b);}),select=$('task-panel');select.replaceChildren();const settingCounts=new Map(),settingOrdinal=new Map();for(const id of panels){const setting=report.models.find(m=>m.panel_id===id).model_setting;settingCounts.set(setting,(settingCounts.get(setting)||0)+1);}for(const id of panels){const members=report.models.filter(m=>m.panel_id===id),m=members[0],ordinal=(settingOrdinal.get(m.model_setting)||0)+1;settingOrdinal.set(m.model_setting,ordinal);const op=el('option',report.method.version>=6?[(m.measurement_facets||[]).map(f=>report.method.measurement_facets?.[f]||f).join('、'),m.model_setting,`${members.length} 个模型`].filter(Boolean).join(' · '):(m.model_setting||'未另列实验设置')+(report.method.version>=6?' · '+(m.measurement_facets||[]).map(f=>report.method.measurement_facets?.[f]||f).join('、'):'')+(report.method.version>=5?' · '+(m.measured_capability_ids||[]).map(c=>report.method.capability_display_labels?.[c]||titleFor(c)).join('、'):'')+(settingCounts.get(m.model_setting)>1?` · 可比来源组 ${ordinal}（${members.length} 个模型）`:''));op.value=id;select.append(op);}if(!panels.includes(taskState.panel))taskState.panel=panels[0]||'';select.value=taskState.panel;select.hidden=panels.length<2;
    const panelModels=report.models.filter(m=>m.panel_id===taskState.panel),published=panelModels.filter(m=>m.publication_eligible);
    const models=(catalog?(published.length?published:panelModels.filter(m=>m.n_groups).slice(0,12)):panelModels).sort((a,b)=>(b.publication_score??-1)-(a.publication_score??-1)||(b.coverage||0)-(a.coverage||0));
    taskVisuals.update(Viz.taskData(report,taskState.panel,Object.fromEntries(taskTaxonomy.capabilities.map(c=>[c.id,c.label]))));
    const allPanel=report.panel||[],entries=allPanel.filter(g=>g.panel_id===taskState.panel||g.model_setting===models[0]?.model_setting&&g.score_scope==='INDIRECT_REFERENCE');
    const stats=$('task-result-stats');stats.replaceChildren();for(const [n,label] of [[new Set(entries.map(g=>identity(g))).size,'匹配 Benchmark'],[new Set(entries.filter(g=>g.score_scope===(catalog?'BENCHMARK_TASK_REFERENCE':'DIRECT_TASK')).map(g=>g.group_id)).size,catalog?'相关来源评测组':'直接任务评测组'],[catalog?(report.candidate_audit||[]).length:models.length,catalog?'所选模型':'候选模型'],[models.filter(m=>m.publication_eligible).length,catalog?'当前组有参考分':'可发布任务总分']]){const card=el('div');card.append(el('strong',n),el('span',label));stats.append(card);}
    const box=$('task-models');box.replaceChildren();
    if(taskState.modelCardPanel!==taskState.panel){taskState.modelCardPanel=taskState.panel;taskState.modelCardLimit=12;}const cardLimit=taskState.modelCardLimit||12;
    for(const m of models.slice(0,cardLimit)){const card=el('article',null,'task-model-card'),top=el('div',null,'task-model-top'),name=el('div');const heading=el('h3');heading.append(modelLink(m.model_canonical,m.model_setting));name.append(heading,el('small',m.model_setting||'未另列实验设置'));top.append(name,el('strong',m.publication_eligible?fmt(m.publication_score):(catalog?'—':'待补证'),'task-score'));card.append(top,el('p',m.publication_eligible?(catalog?(calibrated?`已测能力覆盖 ${fmt((m.capability_weight_coverage||0)*100)}% · 待测中性估计 ${fmt((m.estimated_weight||0)*100)}%`:`相关评测参考分 · 能力权重覆盖 ${fmt((m.capability_weight_coverage||0)*100)}%`):'任务总分 · 0–100'):`可评分证据覆盖 ${fmt((m.coverage||0)*100)}% · 尚不发布总分`,'method-note'));const track=el('div',null,'coverage-track'),fill=el('div',null,'coverage-fill');fill.style.width=Math.max(0,Math.min(100,(m.coverage||0)*100))+'%';track.append(fill);card.append(track);
      for(const ability of m.ability_scores||[]){const row=el('div',null,'bar-row'),t=el('div',null,'bar-track'),f=el('div',null,'bar-fill');const value=catalog?ability.reference_score:ability.score;f.style.width=(number(value)??0)+'%';t.append(f);row.append(el('span',(report.method.capability_display_labels?.[ability.capability_id]||titleFor(ability.capability_id)),'bar-label'),t,el('span',fmt(value),'bar-value'));row.title=`权重 ${fmt(ability.weight*100)}% · ${ability.n_benchmarks} 个 Benchmark · 覆盖 ${fmt((ability.coverage||0)*100)}%`;card.append(row);}
      const details=el('details'),summary=el('summary','覆盖缺口与评分依据'),list=el('ul',null,'evidence-list');for(const ability of m.ability_scores||[])list.append(el('li',`${(report.method.capability_display_labels?.[ability.capability_id]||titleFor(ability.capability_id))} · 权重 ${fmt(ability.weight*100)}% · ${ability.n_independent_benchmarks||0} 个独立来源 · ${ability.n_groups||0}/${ability.required_groups||0} 组；已观测分 ${fmt(ability.observed_score)}${catalog?(report.method.version>=6?'（来源任务成果）':'（Benchmark 标签相关表现）'):ability.status==='COMPLETE'?'':'（局部证据，不代表完整能力分）'}`));for(const gap of [...(m.publication_reasons||[]),...(m.missing_reasons||[])] .slice(0,20))list.append(el('li',(gapNames[gap.reason]||gap.reason||'证据缺口')+(gap.capability_id?' · '+titleFor(gap.capability_id):'')+(gap.required?' · '+(gap.observed||0)+'/'+gap.required:'')));
      if(m.indirect_reference?.n_groups)list.append(el('li',`另有 ${m.indirect_reference.n_groups} 组能力迁移参考，不计入直接任务总分。`));details.append(summary,list);card.append(details);box.append(card);}
    if(models.length>cardLimit){const more=el('button',`已显示 ${cardLimit} / ${models.length} 个模型详情 · 继续显示`,'candidate-more');more.type='button';more.addEventListener('click',()=>{taskState.modelCardLimit=cardLimit+12;renderTaskResults();});box.append(more);}
    if(!models.length)empty(box,'当前没有可发布的任务模型比较',report.available?'尚无足够的任务相关成绩。可以查看已匹配评测，或按实际任务调整能力与领域。':report.note||'来源能力标签仍需审核；不会用通用指数替代。');
    if(catalog){renderTaskEvidence(report);renderMatchedBenchmarks(report);}else{
      $('task-coverage').hidden=true;$('task-comparison').hidden=true;$('task-candidate-gaps').hidden=true;
    const matches=$('task-matches');matches.replaceChildren();const matched=new Map();for(const g of entries){const key=identity(g);if(!matched.has(key))matched.set(key,[]);matched.get(key).push(g);}
    for(const [key,gs] of matched){const b=taskEvidenceSnapshot()?.benchmarks.find(b=>identity(b)===key),card=el('article',null,'bench-card match-card'),direct=gs.some(g=>g.score_scope==='DIRECT_TASK');card.append(el('span',catalog?'任务相关 Benchmark':direct?'直接任务证据':'能力迁移参考','badge '+(catalog||direct?'good':'warning')),el('h3',b?.benchmark_name||gs[0].benchmark_id),el('p',`${gs.length} 个评测组 · ${[...new Set(gs.map(g=>titleFor(g.capability_id)))].join('、')}`,'method-note'));
      for(const g of gs.slice(0,2)){card.append(el('small',[g.metric,Viz.publicLabel(g.row_key),g.blocked_reasons?.length?'存在覆盖缺口':'已匹配实验条件'].filter(Boolean).join(' · ')));const quote=g.evidence?.find(e=>e.quote)?.quote;if(quote)card.append(el('blockquote',quote));}
      if(b){const btn=el('button','查看来源成绩与标签证据');btn.addEventListener('click',()=>selectBenchmark(b));card.append(btn);}matches.append(card);}
    if(!matched.size)empty(matches,'没有匹配的评测组','能力地图可查看当前窗口实际覆盖哪些能力。');

    }
    const excluded=$('task-exclusions');excluded.replaceChildren();excluded.append(el('p',report.validation?.note||'当前分数未经真实专业任务校准。'));if(report.annotation_audit){const details=el('details');details.append(el('summary',`任务范围核查：${report.irrelevant_groups||0} 组已确认无关，${report.unresolved_scope_groups||0} 组关系待核`));for(const g of report.annotation_audit){const b=taskEvidenceSnapshot()?.benchmarks.find(b=>identity(b)===identity(g));details.append(el('p',`${b?.benchmark_name||'来源 Benchmark'} · ${sourceLabel(g.paper_id,g.table_id)} · ${{OUT_OF_SCOPE:'已确认领域不符',UNKNOWN:'关系待核',REVIEWED:'已审核'}[g.state]||g.state}`));}excluded.append(details);}const reasons=new Map();for(const e of report.exclusions||[]){const key=e.reason||'其他';reasons.set(key,(reasons.get(key)||0)+1);}for(const [reason,count] of reasons)excluded.append(el('p',`${gapNames[reason]||reason} · ${count} 组`));if(!reasons.size)excluded.append(el('p',report.note||'没有额外的排除记录。'));
  }
  function candidateGapText(a){
    if(a.status==='NO_TASK_EVIDENCE')return '本快照暂无该模型符合当前任务计分范围的成绩；可继续查看原始来源。';
    return '有相关成绩，可在对应实验设置内查看参考分。';
  }
  function renderTaskEvidence(report){
    const calibrated=report.method?.version>=3&&report.method.version<5,related=report.match_scope==='RELATED_CAPABILITIES_ONLY';
    const capTitle=id=>report.method?.capability_display_labels?.[id]||titleFor(id);
    const coverage=$('task-coverage');coverage.hidden=false;coverage.replaceChildren();
    const caps=report.capability_coverage||[],found=caps.filter(c=>c.n_benchmarks>0),head=el('div',null,'task-evidence-heading');
    head.append(el('h3',related?'相近能力证据':'能力证据概览'),el('span',`${found.length} / ${caps.length} 项能力有相关评测`,'badge'));coverage.append(head);
    coverage.append(el('p',calibrated?'至少一项真实成绩即可参与。已测能力先校准对手；未测分项留空，汇总时按 50 分中性假设估计，并单列比例。':'至少一项相关成绩即可计算参考分。缺失能力留空，参考分按已覆盖能力的权重比例汇总。','method-note'));
    if(related)coverage.append(el('p','当前没有同类型任务成绩；这里展示相近能力参考，不代表完成该任务的表现。','method-note'));
    const grid=el('div',null,'task-capability-evidence-grid');
    for(const cap of caps){const card=el('button',null,'task-capability-evidence'+(!cap.n_benchmarks?' is-gap':''));card.type='button';card.append(el('strong',capTitle(cap.capability_id)),el('small',`任务权重 ${fmt(cap.weight*100)}%`),el('b',cap.n_benchmarks?String(cap.n_benchmarks):'暂无'),el('span',cap.n_benchmarks?'项相关 Benchmark':'匹配评测'));card.addEventListener('click',()=>{$('task-match-capability').value=cap.capability_id;taskState.matchLimit=8;renderMatchedBenchmarks(report);$('task-match-search').scrollIntoView({block:'nearest'});});grid.append(card);}coverage.append(grid);
    const all=report.models.filter(m=>m.panel_id===taskState.panel),audit=report.candidate_audit||[],byName=new Map(all.map(m=>[m.model_canonical,m]));
    const ordered=all.slice().sort((a,b)=>(b.publication_score??-1)-(a.publication_score??-1)||b.n_benchmarks-a.n_benchmarks);
    const comparison=$('task-comparison');comparison.hidden=false;comparison.replaceChildren();
    const currentFacet=all[0]?.measurement_facets?.[0],facetLabel=report.method?.measurement_facets?.[currentFacet];
    comparison.append(el('h3',facetLabel?facetLabel+' · 模型比较':related?'所选模型 · 相近能力参考':'所选模型 · 并排比较'),el('p',calibrated?'完整权重参考分包含待测能力的中性估计；已测能力参考分只描述有成绩的部分。不同可比来源组分开显示。':'按具体任务类型、已测能力和来源条件分组；缺测留空。每项参考分可查阅对应成绩，不同组不混排。','method-note'));
    const wrap=el('div',null,'task-comparison-wrap'),table=el('table',null,'task-comparison-table'),thead=el('thead'),tr=el('tr');
    const headings=['模型',calibrated?'完整权重参考分':'参考分',...(calibrated?['已测能力参考分']:[]),'相关评测','已测能力权重',...caps.map(c=>capTitle(c.capability_id))];
    for(const label of headings)tr.append(el('th',label));thead.append(tr);table.append(thead);
    const tbody=el('tbody'),limit=taskState.comparisonLimit||12;
    for(const m of ordered.slice(0,limit)){
      const line=el('tr'),name=el('td');name.append(modelLink(m.model_canonical,m.model_setting));line.append(name);
      const score=el('td',m.publication_eligible?fmt(m.publication_score):'—','task-comparison-score');
      if(calibrated&&m.estimated_weight>1e-8)score.append(el('small',`含 ${fmt(m.estimated_weight*100)}% 待测估计`));line.append(score);
      if(calibrated)line.append(el('td',fmt(m.observed_reference_score)));
      line.append(el('td',`${m.n_benchmarks} 项`),el('td',`${fmt((m.capability_weight_coverage||0)*100)}%`));
      for(const cap of caps){const ability=m.ability_scores.find(a=>a.capability_id===cap.capability_id),cell=el('td');cell.append(el('strong',fmt(ability?.reference_score)),el('small',ability?.n_benchmarks?`${ability.n_benchmarks} 项评测`:calibrated?'未测 · 汇总按中性估计':'暂无相关成绩'));line.append(cell);}tbody.append(line);
    }
    for(const a of audit.filter(a=>!byName.has(a.model_canonical)).slice(0,Math.max(0,limit-ordered.length))){
      const line=el('tr'),cell=el('td'),elsewhere=report.models.some(m=>m.model_canonical===a.model_canonical);cell.append(modelLink(a.model_canonical,''));line.append(cell,el('td',elsewhere?'其他来源组':'—'));
      if(calibrated)line.append(el('td','—'));line.append(el('td',`${a.task_benchmarks} 项`),el('td',`${fmt(a.covered_capability_weight*100)}%`));for(const c of caps)line.append(el('td','—'));
      line.title=elsewhere?'该型号在其他实验设置或可比来源组有成绩，可切换上方选项。':candidateGapText(a);tbody.append(line);
    }
    table.append(tbody);wrap.append(table);comparison.append(wrap);
    if(ordered.length>limit){const more=el('button',`继续显示其余 ${ordered.length-limit} 个模型`,'candidate-more');more.type='button';more.addEventListener('click',()=>{taskState.comparisonLimit=limit+12;renderTaskEvidence(report);});comparison.append(more);}
    const gaps=audit.filter(a=>a.status!=='SCORABLE'),gapBox=$('task-candidate-gaps');gapBox.hidden=!gaps.length;gapBox.replaceChildren();
    if(gaps.length){const details=el('details',null,'panel task-gap-details');details.append(el('summary',`${gaps.length} 个候选模型暂未获得参考分 · 查看原因`));for(const a of gaps.slice(0,24)){const row=el('div',null,'task-gap-row');row.append(el('strong',a.model_canonical),el('span',candidateGapText(a)));details.append(row);}if(gaps.length>24)details.append(el('p',`另有 ${gaps.length-24} 个模型，可在候选区按“有当前任务相关成绩”筛选。`,'method-note'));gapBox.append(details);}
  }
  function renderMatchedBenchmarks(report=taskState.result?.task_index){
    if(report?.method?.name!=='catalog_task_pairwise_reference')return;
    const select=$('task-match-capability'),selectedCap=select.value;select.replaceChildren();let option=el('option','全部任务能力');option.value='';select.append(option);
    for(const c of report.capability_coverage||[]){option=el('option',`${titleFor(c.capability_id)} · ${c.n_benchmarks} 项`);option.value=c.capability_id;select.append(option);}select.value=(report.profile.capabilities||[]).some(c=>c.id===selectedCap)?selectedCap:'';
    const query=$('task-match-search').value.trim().toLocaleLowerCase(),caps=new Map(report.profile.capabilities.map(c=>[c.id,c.weight]));
    const filtered=(report.benchmark_matches||[]).filter(b=>!taskEvidenceSnapshot()?.visitor_catalog_filtered||taskEvidenceSnapshot().benchmarks.some(ref=>identity(ref)===identity(b))).filter(b=>(!select.value||b.matched_capabilities.includes(select.value))&&(!query||[b.benchmark_name,...b.metrics,...b.tasks.map(titleFor)].join(' ').toLocaleLowerCase().includes(query))).sort((a,b)=>Number(b.exact_task_match)-Number(a.exact_task_match)||b.relevance_weight-a.relevance_weight||a.benchmark_name.localeCompare(b.benchmark_name));
    const matches=$('task-matches');matches.replaceChildren();const limit=taskState.matchLimit||8;
    for(const match of filtered.slice(0,limit)){
      const b=taskEvidenceSnapshot().benchmarks.find(b=>identity(b)===identity(match)),card=el('article',null,'bench-card task-match-card');
      const top=el('div',null,'task-match-heading');top.append(el('span',match.exact_task_match?'同类型任务':'相近能力参考','badge'+(match.exact_task_match?' good':'')),el('span',`${match.groups} 组成绩`,'task-match-count'));card.append(top,el('h3',match.benchmark_name));
      const tags=el('div',null,'tags');for(const cap of match.matched_capabilities)tags.append(el('span',`${titleFor(cap)} · 权重 ${fmt((caps.get(cap)||0)*100)}%`,'tag'));card.append(tags,el('p',`${match.domains.map(titleFor).join('、')} · ${match.tasks.map(titleFor).join('、')}`,'method-note'));
      const selected=taskState.candidateMode==='all'?match.model_names:match.model_names.filter(n=>taskState.refs.has(n));card.append(el('p',`涉及 ${match.model_names.length} 个模型 · 当前所选 ${selected.length} 个有成绩`,'task-match-model-count'));
      if(selected.length)card.append(el('p',selected.slice(0,4).join('、')+(selected.length>4?` 等 ${selected.length} 个`:''),'task-match-model-names'));
      if(match.evidence?.length){const why=el('details',null,'task-match-proof');why.append(el('summary','评测匹配依据'));for(const e of match.evidence.slice(0,2)){why.append(el('strong',titleFor(e.id)),el('blockquote',e.quote));}card.append(why);}
      const actions=el('div',null,'task-match-actions'),detailURL=new URL('benchmark/?'+new URLSearchParams({paper_id:match.paper_id,benchmark_id:match.benchmark_id,...(taskEvidenceSnapshot()?.visitor_catalog_filtered?{}:{edition:'admin'})}),radarBase).href;if(b&&state.snapshot?.detail_loaded!==false){const btn=el('button','查看来源成绩');btn.type='button';btn.addEventListener('click',()=>selectBenchmark(b));actions.append(btn,link(detailURL,'新页查看'));}else actions.append(link(detailURL,'查看来源成绩'));card.append(actions);matches.append(card);
    }
    if(!filtered.length)empty(matches,'没有匹配的评测',select.value?'这项能力在当前来源中暂无匹配 Benchmark，其他能力的证据仍可查看。':'请调整检索关键词，或根据任务要求修改领域与能力配置。');
    $('task-match-count').textContent=`已显示 ${Math.min(filtered.length,limit)} / ${filtered.length} 项来源评测`;
    $('task-match-more').hidden=filtered.length<=limit;
  }
  function renderCapabilityMap() {
    const ann=state.snapshot?.capability_annotations,items=annotationItems(),atlas=state.snapshot?.capability_atlas,box=$('capability-map');box.replaceChildren();
    const counts=new Map((atlas?.capabilities||[]).map(c=>[c.id,c]));
    $('annotation-coverage').textContent=atlas?`${atlas.coverage.catalog_labelled_records} 个 Benchmark 已有目录能力标签 · ${atlas.coverage.supported_groups} 组指标已核验`:ann?`${items.filter(a=>a.status==='SUPPORTED').length}/${ann.total_groups} 组指标已核验`:'来源能力标注尚未接入';
    for(const cap of taskTaxonomy.capabilities){
      const rows=items.filter(a=>a.status==='SUPPORTED'&&(a.capabilities||[]).includes(cap.id)),stat=counts.get(cap.id),count=stat?.benchmark_records??new Set(rows.map(identity)).size,groupCount=stat?.supported_groups??rows.length,domains=stat?.domains||[...new Set(rows.flatMap(a=>a.domains||[]))],card=el('article',null,'capability-card'+(count?'':' zero'));
      card.append(el('h3',cap.label),el('p',cap.description),el('strong',count|| (state.snapshot?.detail_loaded===false?'加载中':'待补证'),'cap-count'),el('small',`个 Benchmark · ${groupCount} 个已核验指标组`));
      const tags=el('div',null,'tags');for(const domain of domains)tags.append(el('span',titleFor(domain),'tag'));
      if(count&&!groupCount)tags.append(el('small','已标注评测能力；能力评分需要额外的可比指标证据'));
      else if(!count)tags.append(el('small','尚无足够来源证据，不代表模型不具备该能力'));
      card.append(tags);const btn=el('button','浏览这项能力的 Benchmark');btn.addEventListener('click',()=>{state.capability=cap.id;state.benchmarkLimit=40;$('cap-filter').value=cap.id;setView('benchmarks');});card.append(btn);box.append(card);
    }
  }
  function renderTaskWorkspace() {renderReferences();if(!state.snapshot){taskState.result=null;$('task-results').hidden=true;taskMessage('task-score-message','等待评测数据源。','warning');}else if(taskState.result)renderTaskResults();else if($('task-score-message').textContent.startsWith('等待'))taskMessage('task-score-message','确认任务需求后计算；按任务类型查看参考分与来源成绩。');}
  function loadSavedProfiles() {let profiles={};try{profiles=JSON.parse(localStorage.getItem('radar-task-plans-v1')||'{}');if(!profiles||Array.isArray(profiles)||typeof profiles!=='object')profiles={};}catch{}return Object.assign(Object.create(null),profiles);}
  function refreshSavedSelect() {const select=$('saved-profiles');select.replaceChildren(el('option','打开已保存方案…'));select.firstChild.value='';for(const name of Object.keys(loadSavedProfiles()).slice(0,12)){const opt=el('option',name);opt.value=name;select.append(opt);}}
  function initTaskWorkspace() {
    for(const [id,layer] of [['task-domains','domains'],['task-types','tasks'],['domain-filter','domains'],['task-filter','tasks'],['cap-filter','capabilities']])for(const item of taskTaxonomy[layer]){const opt=el('option',item.label);opt.value=item.id;$(id).append(opt);}
    for(const id of ['task-description','task-domains','task-types','constraint-language','constraint-modality','constraint-access','constraint-context'])$(id).addEventListener(id==='task-description'?'input':'change',dirtyTask);
    for(const id of ['task-domains','task-types'])$(id).addEventListener('change',syncProfilePickers);
    document.addEventListener('click',event=>{for(const picker of document.querySelectorAll('.profile-picker[open]'))if(!picker.contains(event.target))picker.open=false;});
    for(const picker of document.querySelectorAll('.profile-picker'))picker.addEventListener('keydown',event=>{if(event.key==='Escape'){picker.open=false;picker.querySelector('summary').focus();}});
    for(const [id,key] of [['domain-filter','domain'],['task-filter','taskType'],['cap-filter','capability']])$(id).addEventListener('change',e=>{state[key]=e.target.value;state.benchmarkLimit=40;renderBenchmarks();});
    $('toggle-capabilities').addEventListener('click',()=>{taskState.showAll=!taskState.showAll;updateWeights();});
    $('cancel-task-analysis').addEventListener('click',()=>{dirtyTask();taskMessage('profile-message','已取消等待；可直接编辑能力与权重。');});
    $('analyse-task').addEventListener('click',analyseTask);$('cancel-task-score').addEventListener('click',()=>{dirtyTask();taskMessage('task-score-message','已取消等待；可以调整要求后重新计算。');});$('score-task').addEventListener('click',()=>scoreTask());$('reference-search').addEventListener('input',()=>{taskState.candidateLimit=48;renderReferences();});$('reference-model-order').addEventListener('change',renderReferences);$('reference-vendor').addEventListener('change',()=>{taskState.candidateLimit=48;renderReferences();});$('reference-top').addEventListener('click',()=>setCandidateSelection('custom',Viz.sortTaskCandidates(filteredCandidates().filter(r=>r.nTaskBenchmarks)).slice(0,6).map(r=>r.name)));$('reference-all').addEventListener('click',()=>setCandidateSelection('custom',new Set([...taskState.refs,...filteredCandidates().map(r=>r.name)])));$('reference-scope').addEventListener('change',()=>{taskState.candidateLimit=48;renderReferences();});$('reference-clear').addEventListener('click',()=>setCandidateSelection('custom'));$('reference-more').addEventListener('click',()=>{taskState.candidateLimit=(taskState.candidateLimit||48)+48;renderReferences();});$('task-panel').addEventListener('change',e=>{taskState.panel=e.target.value;renderTaskResults();});
    $('save-profile').addEventListener('click',()=>{try{const name=$('profile-name').value.trim();if(!name)throw Error('请填写方案名称。');const profile=editorProfile(),saved=loadSavedProfiles();if(!Object.hasOwn(saved,name)&&Object.keys(saved).length>=12)throw Error('最多保存 12 个方案；请用已有名称覆盖。');saved[name]={profile,candidate_models:[...taskState.refs],candidate_mode:taskState.candidateMode};localStorage.setItem('radar-task-plans-v1',JSON.stringify(saved));refreshSavedSelect();taskMessage('profile-message','已保存到本浏览器，可随时切换任务方案。');}catch(e){taskMessage('profile-message',e.message||'本浏览器无法保存方案。');}});
    $('broaden-task-evidence').addEventListener('click',()=>{for(const opt of $('task-types').options)opt.selected=false;syncProfilePickers();dirtyTask();renderReferences();scoreTask();});
    $('saved-profiles').addEventListener('change',e=>{try{const saved=loadSavedProfiles()[e.target.value];if(saved){applyProfile(saved.profile);taskState.refs=new Set(saved.candidate_models||[]);taskState.candidateMode=saved.candidate_mode||(taskState.refs.size?'custom':'all');taskState.refsInitialized=true;renderReferences();}}catch{taskMessage('profile-message','已保存方案版本不兼容，请重新选择能力。');}finally{e.target.value='';}});
    $('task-match-search').addEventListener('input',()=>{taskState.matchLimit=8;renderMatchedBenchmarks();});$('task-match-capability').addEventListener('change',()=>{taskState.matchLimit=8;renderMatchedBenchmarks();});$('task-match-more').addEventListener('click',()=>{taskState.matchLimit=(taskState.matchLimit||8)+8;renderMatchedBenchmarks();});
    refreshSavedSelect();applyProfile(TASK_DEFAULTS.templates['medical-literature-review']);$('task-description').value='';
  }

  function visibleBenchmarks() {const seen=new Set();return (state.snapshot?.benchmarks||[]).filter(b=>
    (!state.domain||benchTags(b,'domains').includes(state.domain)) &&
    (!state.taskType||benchTags(b,'tasks').includes(state.taskType)) &&
    (!state.capability||benchTags(b,'capabilities').includes(state.capability)) &&
    (state.eligibility==='all'||state.eligibility===b.eligibility||(state.eligibility==='review'&&b.eligibility?.includes('REVIEW'))) &&
    (!state.query||[b.benchmark_name,b.source_benchmark_name,b.paper_title,b.arxiv_id,...(b.benchmark_aliases||[]),...(b.catalog_aliases||[]),...(b.directory_aliases||[]),...(b.directory_sources||[]).map(r=>r.paper_title)].some(v=>String(v||'').toLocaleLowerCase().includes(state.query.toLocaleLowerCase())))
  ).sort((a,b)=>(Date.parse(b.release_date)||0)-(Date.parse(a.release_date)||0)).filter(b=>{const key=Viz.directoryKey(b);if(seen.has(key))return false;seen.add(key);return true;});}
  let uiReady=false;
  function setView(view) {if(!['benchmarks','tasks','capabilities','models',...(visitorEdition?['home']:[])].includes(view))throw Error('视图无效');const changed=state.view!==view;state.view=view;history.replaceState(null,'','#'+view+'-view');for(const b of document.querySelectorAll('[data-view]'))b.setAttribute('aria-pressed',String(b.dataset.view===view));for(const v of ['benchmarks','tasks','capabilities','models',...(visitorEdition?['home']:[])])$(`view-${v}`).hidden=v!==view;$('detail').hidden=view!=='benchmarks'||!state.selected;$('visual-highlights').hidden=view!=='benchmarks';if(uiReady&&changed){render();if(window.RadarHomeSnapshot&&(view!=='home'&&view!=='tasks')&&state.snapshot?.detail_loaded===false)refresh({details:true});if(view==='tasks')loadTaskEvidenceForPreview().catch(error=>taskMessage('task-score-message',error.message,'warning'));if(visitorEdition)window.scrollTo({top:0,behavior:'instant'});}}
  function sourceLabel(paper,table) {return Viz.publicLabel(table,'论文来源');}
  function renderCounts() {
    const d=state.snapshot;
    $('window-days').textContent=d?`论文近${text(d.window.paper?.days??d.window.days)}天 · Benchmark近${text(d.window.benchmark?.months??d.window.benchmark_months??5)}个月`:'论文近14天 · Benchmark近5个月';
    $('last-updated').textContent=`证据更新时间 ${d?date(d.status.evidence_generated_at||d.generated_at):'—'}`;
    $('window-range').textContent=d?`论文首次公开窗口 [${d.window.paper?.start??d.window.start}, ${d.window.paper?.end??d.window.end}) · Benchmark首次发布窗口 [${d.window.benchmark?.start??d.window.benchmark_start??'待核'}, ${d.window.benchmark?.end??d.window.end})`:'当前时间窗口尚未读取';
  }
  function progressText(p,hasCapabilities=false) {const label=hasCapabilities||p?.catalog_capability_state==='SUPPORTED'?'能力已标注':'暂未识别能力';return `${label} · ${p?.paper_extraction_complete===true?'论文提取已完成':p?.observations?'已有成绩':labels[p?.paper_status]||'等待处理'}`;}
  function renderBenchmarkProgress(root,p,hasCapabilities=false) {
    if(!p)return;const box=el('div',null,'benchmark-progress');box.append(el('h3','评测数据处理状态'),el('p',progressText(p,hasCapabilities)));
    box.append(el('p',`来源评测组：${p.total_groups||0} · 可用于能力评分的指标组：${p.supported_annotations||0}`));
    if(p.paper_reason)box.append(el('p','来源论文处理说明：'+p.paper_reason));
    if(p.paper_gaps?.length)box.append(el('p','论文级证据缺口：'+p.paper_gaps.map(g=>g.code+' / '+g.stage).join('；')));root.append(box);
  }
  function renderBenchmarks() {
    const list=visibleBenchmarks(), box=$('benchmarks'),shown=Math.min(state.benchmarkLimit,list.length),more=$('more-benchmarks');box.replaceChildren();more.hidden=shown>=list.length;$('result-count').textContent=state.snapshot?`显示 ${shown} / ${list.length} 项匹配 · 当前窗口共 ${state.snapshot.visitor_catalog_count??state.snapshot.status?.counts?.unique_benchmarks??state.snapshot.benchmarks.length} 项`:'尚未读取评测数据';
    const previousKeys=box.radarBenchmarkKeys||new Set();box.radarBenchmarkKeys=new Set();let entering=0;
    if(!list.length){empty(box,state.snapshot?'当前条件没有 Benchmark':'等待评测数据',state.snapshot?'可调整搜索或资格筛选。':'连接后显示当前窗口内的评测条目。');return;}
    const table=el('table',null,'benchmark-directory-table'),caption=el('caption','当前窗口 Benchmark 目录，点击名称查看成绩与来源详情。','sr-only'),head=el('thead'),header=el('tr'),body=el('tbody');
    for(const title of ['Benchmark 与论文来源','状态','能力','模型','核验成绩','详情']){const th=el('th',title);th.scope='col';header.append(th);}head.append(header);table.append(caption,head,body);
    for(const b of list.slice(0,shown)){
      const members=Viz.directorySources(b),obs=members.flatMap(ref=>observations(ref)),progress=b.progress||{},partial=state.snapshot.detail_loaded===false;
      const nScores=partial?(members.length>1?null:progress.observations??null):obs.length;
      const nModels=partial?(members.length>1?null:progress.models??null):new Set(obs.map(o=>o.model_canonical).filter(Boolean)).size;
      const nTables=partial?(members.length>1?null:progress.tables??null):new Set(obs.filter(o=>o.table_id!=null).map(o=>JSON.stringify([o.paper_id,o.table_id]))).size;
      const href=new URL('benchmark/?'+new URLSearchParams({paper_id:b.paper_id,benchmark_id:b.benchmark_id,...(state.snapshot?.visitor_catalog_filtered?{}:{edition:'admin'})}),radarBase).href;
      const row=el('tr',null,'benchmark-directory-row'),nameCell=el('td',null,'benchmark-directory-name'),title=el('a',b.benchmark_name,'benchmark-directory-title');title.href=href;
      const motionKey=JSON.stringify([b.paper_id,b.benchmark_id]);box.radarBenchmarkKeys.add(motionKey);row.setAttribute('data-enter',previousKeys.has(motionKey)?'none':String(Math.min(entering++,6)));
      const excluded=b.eligibility==='EXCLUDED'||(!nScores&&progress.paper_status==='EXCLUDED');
      const review=b.name_audit?.status==='REVIEW_REQUIRED',status=el('span',excluded?'已排除':review?'名称待核验':nScores>0?'有成绩':nScores===null?'读取中':'暂无成绩','benchmark-directory-status'+(excluded?' is-excluded':review?' is-review':nScores>0?' has-scores':''));
      const statusCell=el('td',null,'benchmark-directory-state');statusCell.setAttribute('data-label','状态');statusCell.append(status);
      const intro=el('div',null,'benchmark-directory-heading');intro.append(title);
      const paper=el('p',b.paper_title,'benchmark-directory-paper');paper.title=b.paper_title||'';
      const meta=el('div',null,'benchmark-directory-meta'),released=el('span',date(b.release_date));meta.append(released);
      if(b.name_audit?.status==='REPAIRED')meta.append(el('span','名称已按原文修正'));
      if(b.name_audit?.status==='REVIEW_REQUIRED')meta.append(el('span','原始片段见详情'));
      if(nTables>0)meta.append(el('span',`${nTables} 张来源表`));
      if(members.length>1)meta.append(el('span',`${members.length} 条来源记录`));nameCell.append(intro,paper,meta);
      const abilityCell=el('td',null,'benchmark-directory-abilities'),domains=benchTags(b,'domains'),capabilities=benchTags(b,'capabilities');
      if(domains.length)abilityCell.append(el('span',domains.map(titleFor).join(' · '),'benchmark-directory-domain'));
      const tags=el('div',null,'benchmark-directory-tags');
      for(const cap of capabilities.slice(0,3))tags.append(el('span',titleFor(cap),'benchmark-directory-tag'));
      if(capabilities.length>3){
        const count=capabilities.length-3,rest=el('span',null,'benchmark-directory-extra-tags'),toggle=el('button',`更多 ${count} 项`,'benchmark-directory-more');
        rest.id='benchmark-tags-'+encodeURIComponent(JSON.stringify([b.paper_id,b.benchmark_id]));rest.hidden=true;toggle.type='button';toggle.setAttribute('aria-controls',rest.id);toggle.setAttribute('aria-expanded','false');toggle.setAttribute('aria-label',`展开其余 ${count} 项能力标签`);
        for(const cap of capabilities.slice(3))rest.append(el('span',titleFor(cap),'benchmark-directory-tag'));
        toggle.addEventListener('click',()=>{rest.hidden=!rest.hidden;toggle.textContent=rest.hidden?`更多 ${count} 项`:'收起';toggle.setAttribute('aria-expanded',String(!rest.hidden));toggle.setAttribute('aria-label',rest.hidden?`展开其余 ${count} 项能力标签`:'收起其余能力标签');});tags.append(rest,toggle);
      }
      if(!capabilities.length)tags.append(el('span','暂无能力标签','benchmark-directory-no-tags'));abilityCell.append(tags);
      const modelCell=el('td',null,'benchmark-directory-count'),scoreCell=el('td',null,'benchmark-directory-count benchmark-directory-scores');modelCell.setAttribute('data-label','模型');scoreCell.setAttribute('data-label','核验成绩');
      modelCell.append(el('span',nModels===null?'读取中':nModels>0?fmt(nModels):'—'));scoreCell.append(el('span',nScores===null?'读取中':nScores>0?fmt(nScores):'暂无'));
      const actionCell=el('td',null,'benchmark-directory-action'),detail=el('a',null,'benchmark-directory-open'),arrow=el('span','查看','benchmark-directory-action-label');detail.href=href;detail.setAttribute('aria-label','查看 '+b.benchmark_name+' 的成绩与来源详情');detail.title='查看详情';arrow.setAttribute('aria-hidden','true');detail.append(arrow);actionCell.append(detail);
      row.append(nameCell,statusCell,abilityCell,modelCell,scoreCell,actionCell);
      row.addEventListener('click',e=>{if(e.target.closest('a,button,details,input,select')||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey||window.getSelection()?.toString())return;title.click();});
      body.append(row);
    }
    box.append(table);
  }
  function renderModels() {
    const rows=scopedModels().filter(m=>state.snapshot?.index?.method?.score_unit!=='z_score'||m.model_setting===visualSetting);rows.sort((a,b)=>state.sort==='vendor'?Viz.compareModelVendor(a,b):state.sort==='name'?a.model_canonical.localeCompare(b.model_canonical):state.sort==='coverage'?(b.n_benchmarks||0)-(a.n_benchmarks||0):(Viz.publicationScore(b,state.snapshot?.index?.method?.min_benchmarks||3)??-Infinity)-(Viz.publicationScore(a,state.snapshot?.index?.method?.min_benchmarks||3)??-Infinity));const box=$('models');box.replaceChildren();
    for(const m of rows.slice(0,state.modelLimit)){const tr=el('tr'),name=el('td');name.append(modelLink(m.model_canonical,m.model_setting),el('span',m.model_setting||'未另列实验设置','subtext'));tr.append(name,el('td',(m.score_unit==='z_score'?statFmt:fmt)(Viz.publicationScore(m,state.snapshot?.index?.method?.min_benchmarks||3)),'numeric emphasis'),el('td',fmt(m.n_benchmarks),'numeric'),el('td',fmt(m.n_groups),'numeric'),el('td',number(m.coverage_pct)===null?'—':`${fmt(m.coverage_pct)}%`,'numeric'));const status=el('td');status.append(badge(Viz.publicationLabel(m,state.snapshot?.index?.method?.min_benchmarks||3),false));tr.append(status);box.append(tr);}
    $('more-models').hidden=rows.length<=state.modelLimit;
    if(!rows.length){const tr=el('tr'),td=el('td','当前没有可发布的模型指数；有原始成绩的 benchmark 仍可在雷达页查看。');td.colSpan=6;tr.append(td);box.append(tr);}
  }
  function selectBenchmark(b,scroll=true) {state.selected=identity(b);state.scoreLimit=80;state.group='';setView('benchmarks');renderDetail();if(scroll)$('detail').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});}
  function renderDetail() {
    const b=state.snapshot?.benchmarks.find(b=>identity(b)===state.selected);if(!b){state.selected=null;$('detail').hidden=true;return;}
    $('detail').hidden=state.view!=='benchmarks';$('detail-title').textContent=b.benchmark_name;$('detail-paper').textContent=b.paper_title;const meta=$('detail-meta');meta.replaceChildren(badge(b.eligibility,b.eligibility==='ELIGIBLE'),el('span',`发布日期 ${date(b.release_date)}`,'badge'),el('span',`arXiv ${text(b.arxiv_id)}`,'badge'));
    const evidence=$('detail-evidence');evidence.replaceChildren(el('p',b.reason||'资格结果以评测服务的证据核验为准。'));renderBenchmarkProgress(evidence,b.progress,benchTags(b,'capabilities').length>0);
    if(b.catalog_sources?.length>1){const sources=el('details');sources.append(el('summary',`同一 Benchmark 的 ${b.catalog_sources.length} 条来源记录`),el('p','统一名称：'+b.benchmark_name),el('p','原始名称：'+(b.catalog_aliases||[]).join('、')));for(const ref of b.catalog_sources){const source=state.snapshot.benchmarks.find(x=>identity(x)===identity(ref));if(source){const button=el('button',source.paper_title||source.source_benchmark_name||source.benchmark_name);button.onclick=()=>selectBenchmark(source);sources.append(button);}}evidence.append(sources);}
    if(b.directory_sources?.length>1&&b.directory_grouping_basis==='SAME_NAME_SEPARATE_SOURCES'){
      const sources=el('details');sources.open=true;sources.append(el('summary',`同名评测 · ${b.directory_sources.length} 条论文来源`),el('p','目录集中展示同名来源；各论文的评测条件、版本和原始成绩分别保留。'));
      for(const ref of b.directory_sources){const source=state.snapshot.benchmarks.find(x=>identity(x)===identity(ref));if(source){const button=el('button',source.paper_title||source.benchmark_name);button.type='button';button.onclick=()=>selectBenchmark(source);sources.append(button);}}evidence.append(sources);
    }
    if(b.date_basis)evidence.append(el('p',b.date_basis==='PAPER_V1_PROXY'?'日期依据：论文 v1 首次公开时间代理，保留来源日期证据。':`日期依据：${b.date_basis}`));if(b.evidence_quote)evidence.append(el('blockquote',b.evidence_quote));evidence.append(link(b.source_url,'打开来源论文'));
    const annotations=annotationItems().filter(a=>identity(a)===identity(b));
    const capabilities=benchTags(b,'capabilities');evidence.append(el('h3','评测能力'),el('p',capabilities.length?capabilities.map(titleFor).join('、'):'暂未识别能力'));
    const proofs=(b.enrichment?.labels?.evidence||[]).filter(p=>p.layer==='capabilities'&&capabilities.includes(p.id)&&p.bound_to_benchmark===true);
    if(proofs.length){const details=el('details');details.append(el('summary','查看能力标签的原文依据'));for(const p of proofs)details.append(el('blockquote',p.quote));evidence.append(details);}
    const scoring=annotations.filter(a=>a.status==='SUPPORTED');if(scoring.length){const details=el('details');details.append(el('summary','指标与评分依据'));for(const a of scoring){details.append(el('p',`${a.metric||''} · ${(a.capabilities||[]).map(titleFor).join('、')}`));for(const p of a.evidence||[])if(p.quote)details.append(el('blockquote',p.quote));}evidence.append(details);}
    for(const asset of b.enrichment?.assets?.items||[]){const p=el('p');p.append(link(asset.url,asset.kind||'公开资源'));evidence.append(p);}
    const gs=groups(b),select=$('metric-group');select.replaceChildren();for(const g of gs){const op=el('option',`${g.metric}${Viz.measurementLabel(g)?"（"+Viz.measurementLabel(g)+"）":""} · ${g.benchmark_labels?.map(x=>Viz.publicLabel(x)).filter(Boolean).join(' / ')||Viz.publicLabel(g.row_key,'综合指标')} · ${g.model_setting||'默认设置'}`);op.value=g.group_id;select.append(op);}if(!gs.some(g=>g.group_id===state.group))state.group=gs.find(g=>!(g.blocked_reasons||[]).length)?.group_id||gs[0]?.group_id||'';select.value=state.group;select.disabled=!gs.length;renderBars(b);
    const obs=observations(b),body=$('source-scores');body.replaceChildren();for(const o of obs.slice(0,state.scoreLimit)){const tr=el('tr');const metric=el('td',o.metric);if(Viz.publicLabel(o.benchmark))metric.append(el('span',Viz.publicLabel(o.benchmark),'subtext'));const coord=el('td',sourceLabel(o.paper_id,o.table_id));const task=Viz.publicLabel(o.row_key);if(task)coord.append(el('span',task,'subtext'));const model=el('td');model.append(modelLink(o.model_canonical,o.model_setting));tr.append(model,el('td',o.model_setting||'—'),metric,el('td',o.value_raw,'numeric emphasis'),coord);body.append(tr);}
    Viz.renderModelRoster($('detail-models'),obs,gs,name=>openModel(name));
    if(!obs.length){const tr=el('tr'),td=el('td','尚无通过核验的基础模型成绩。资格记录和证据已保留。');td.colSpan=5;tr.append(td);body.append(tr);}$('score-count').textContent=`显示 ${Math.min(obs.length,state.scoreLimit)} / ${obs.length} 条来源成绩`;$('more-scores').hidden=obs.length<=state.scoreLimit;renderDetailVisuals();
  }
  function renderBars(b) {const g=groups(b).find(g=>g.group_id===state.group),box=$('bars');box.replaceChildren();if(!g){$('group-note').textContent='尚无方向已明确、至少包含两个模型的可比评测组。下方保留所有已核验原始成绩。';return;}if(g.blocked_reasons?.length){$('group-note').textContent='本组存在证据冲突，暂不发布模型对比图。下方仍保留来源成绩。';return;}$('group-note').textContent=`${Viz.directionLabel(g.direction)} · 图中为论文原值，从零起画；条形长短保留原始分差 · 实验设置：${g.model_setting||'未另列'}`;
    const values=(g.scores||[]).map(s=>s.value_numeric).filter(x=>typeof x==='number'&&Number.isFinite(x)),[lo,hi]=Viz.valueDomain(values,true),zero=100*(0-lo)/(hi-lo);for(const s of [...(g.scores||[])].sort((a,b)=>(g.direction==='lower'?1:-1)*(a.value_numeric-b.value_numeric))){const row=el('div',null,'bar-row'),track=el('div',null,'bar-track'),fill=el('div',null,'bar-fill');const x=100*((number(s.value_numeric)??0)-lo)/(hi-lo);track.style.position='relative';fill.style.position='absolute';fill.style.left=`${Math.min(x,zero)}%`;fill.style.width=`${Math.abs(x-zero)}%`;fill.style.background=Viz.modelColor(s.model_canonical);track.append(fill);const label=el('span',null,'bar-label');label.append(modelLink(s.model_canonical,g.model_setting));row.append(label,track,el('span',new Intl.NumberFormat('zh-CN',{maximumFractionDigits:6}).format(s.value_numeric),'bar-value'));box.append(row);}}
  function renderVisuals() {
    if(!state.snapshot||state.snapshot.detail_loaded===false){for(const v of state.view==='models'?[modelVisuals,modelCoverage]:[overviewRanking,overviewCoverage])v.clear();return;}
    const choices=Viz.settings(state.snapshot),select=$('visual-setting');
    if(!choices.includes(visualSetting))visualSetting=[...choices].sort((a,b)=>state.snapshot.index.models.filter(m=>m.model_setting===b).length-state.snapshot.index.models.filter(m=>m.model_setting===a).length)[0]??'';
    select.replaceChildren();for(const x of choices)select.append(new Option(x||'未另列实验设置',x));select.value=visualSetting;select.disabled=!choices.length;
    const d=rankingData(),coverage=Viz.coverageData(d);
    if(state.view==='benchmarks'){overviewRanking.update(d);overviewCoverage.update(coverage);}
    else {renderRanking(d);modelCoverage.update(coverage);renderPairedSources(d);}
  }
  let rankingMode=null,rankingModeChosen=false,rankingBenchmark='',rankingGroup='';
  function renderRanking(data) {
    const snap=state.snapshot,available=(snap.index.groups||[]).filter(g=>g.model_setting===visualSetting&&!g.extraction_in_progress&&!g.blocked_reasons?.length),benches=new Map(snap.benchmarks.map(b=>[identity(b),b]));
    if(!rankingModeChosen)rankingMode=(visitorEdition&&snap.index.method?.global_composite)||snap.index.method?.panel_status==='CONFIGURED'?'panel':'source';
    $('ranking-mode').querySelector('[value=panel]').textContent=snap.index.method?.global_composite?'综合评分 · 0–100':snap.index.method?.score_unit==='z_score'?'共同评测相对指数':'固定评测综合分';
    $('ranking-mode').value=rankingMode;$('source-ranking-controls').hidden=rankingMode!=='source';
    if(snap.index.method?.global_composite&&rankingMode==='panel'){
      $('relative-panel-controls').hidden=true;$('ranking-panel').replaceChildren();
      const ready=available.filter(g=>g.relative_status==='READY'),benchmarks=new Set(ready.map(g=>g.benchmark_identity||g.benchmark_id));
      const published=data.rows.filter(r=>r.score!==null).length;
      $('scoring-readiness').textContent=`统一综合评分（估计顺序）· ${published} 个模型已发布 · ${benchmarks.size} 项${visitorEdition?'可展示':'可计分'} Benchmark。模型筛选仅改变展示，不改变分数；${visitorEdition?'可展开下方评测覆盖查看各模型的测试量。':'每个模型的测试覆盖量见右图。'}`;
      $('scoring-scope').hidden=false;const body=$('scoring-scope-body');body.replaceChildren();
      if(visitorEdition){
        $('scoring-readiness').textContent=`${published} 个模型已有综合评分 · ${benchmarks.size} 项评测。可查看各模型的评测覆盖和原始成绩。`;
        $('scoring-scope').querySelector('summary').textContent='评分与数据说明';
        body.append(el('p','综合评分汇总当前版本中的已测表现，范围为 0–100。筛选模型仅改变展示范围。'),el('p','细线表示参考区间。评测覆盖和实验设置可能不同，请结合共同参测项目比较；成绩来源可在模型详情中查询。'));
        modelVisuals.update(data);return;
      }
      if(snap.index.method.version>=8&&snap.index.method.version!==9)body.append(el('p','综合分使用跨任务共享强度，而不是将全部任务都视为同一种能力。同场来源成绩用于拟合对应任务的表现，任务专项强度与自身共享强度通过对称的部分共享正则项联合估计；这些正则项不算真实比较、不建立跨模型证据连接，也不增加 Benchmark 数。'),el('p',`基础共享强度正则 ${snap.index.method.prior_strength}；任务共享系数 ${snap.index.method.task_coupling_strength}，按同一来源任务预算比例缩放。系数用隐藏整类任务的预测损失选择，不按预期型号顺序选择。未观测任务不增加来源记录，模型详情可查看已有任务的专项修正。`,'method-note'));
      if(snap.index.method.version===11)body.append(el('p','仅将最终任务表现纳入综合分；来源明确定义的提示或干预增益、统计诊断量保留原值另列。中性收缩参数经来源家族留出验证保留为0.3，型号新旧及厂商不参与拟合。'));
      if(snap.index.method.version>=14)body.append(el('p','综合分由同条件原始成绩、任务分类和共同对手拟合；不按厂商或版本施加顺序。指标按来源限权，明确的干预增益及诊断量另列。'),el('p','实验设置明确不同的任务成绩分开计算，缺失成绩不补零，筛选只改变展示。','method-note'));
      else if(snap.index.method.version===13)body.append(el('p','同条件成绩按论文与评测来源限权，分任务拟合。至少两篇独立论文的共同评测持续支持同厂商模型间的同一方向时，对综合强度作最小一致性校正；型号新旧不参与判断，循环冲突不强行归并。'),el('p','区间对当前来源规则和观测分差条件化，保留基础拟合误差下限；不能视为无条件的能力名次保证。','method-note'));
      else if(snap.index.method.version>=10)body.append(el('p','同条件成绩按模型对分摊论文及评测来源预算；任务类别内采用温和时间衰减，联合拟合任务表现与综合强度。取消硬排序校正，任务之间可以互有胜负。'),el('p',`评分基准日期 ${snap.index.method.temporal_scoring?.as_of||'未指定'}；半衰期 ${snap.index.method.temporal_scoring?.half_life_days??'停用'} 天，权重下限0.5。论文首次提交日期代理单独记录；筛选模型不改变得分。区间由当前拟合重新计算，尚不能消除选择性报告偏差。`,'method-note'));
      if(snap.index.method.version===9)body.append(el('p','先按模型对分摊同一来源的多指标预算，避免表内模型数量稀释双方的共同证据；再对至少两篇独立论文持续支持、且无相反共同来源的比较方向在尽量保留原有分差的前提下校正。约束对所有厂商一致，循环冲突可能形成同分，不添加新胜负记录。'),el('p','综合分和基础拟合分可在模型详情中核对，并查看每条校正约束的来源。校正分未估计置信区间；旧基础拟合区间不用于校正分误差线。','method-note'));
      if(snap.index.method.version>=7)body.append(el('p','按来源任务标签平衡六类任务及未分类来源的贡献，多标签分摊同一来源预算；不凭名称猜标签。排名稳定性、调整后显著性等统计不计能力分。双模型组无核验量程或同源参考尺度时只作低权重胜负比较。'),el('p','任务组内仍可能存在选择性报告和覆盖差异；本榜反映已观测证据，不是完整任务集合上的复现评测。','method-note'));
      if(snap.index.method.opponent_adjusted&&snap.index.method.version>=5)body.append(el('p','同场连续分差 → 论文/Benchmark 权重分摊 → 利用共同对手联合拟合 → 以覆盖合格参考模型为中心映射至0–100。'),el('p',`综合榜要求在合格参考网络内至少 ${snap.index.method.min_benchmarks} 项 Benchmark${snap.index.method.min_source_papers>1?'、'+snap.index.method.min_source_papers+' 篇来源论文':'，不另设论文篇数门槛'}；型号不完整和专用安全分类模型不参与通用综合计分。未达到覆盖门槛的模型保留单项成绩与实际对手信息。`),el('p',`${snap.index.method.version>=9?'每个模型对在每篇论文、每项 Benchmark 的来源预算分别封顶，再统一缩放以保留整体正则比例；':'每个模型在每篇论文、每项 Benchmark 的总比较权重分别不超过1；'}同一来源的多指标及多对手分摊权重。基础正则强度 ${snap.index.method.prior_strength}${snap.index.method.version>=7?'，随各设置的平均任务权重同比缩放':''}，缺测不补零。分数反映当前已测证据，不是正确率；筛选模型不改变分数。${snap.index.method.version===9?'校正分不复用基础拟合区间，同分不确立严格名次。':'近似区间按来源论文聚类，不能证明通用能力的绝对名次。'}`,'method-note'));
      else if(snap.index.method.opponent_adjusted)body.append(el('p',snap.index.method.version>=4?'同场分差 → 除以同组参考标准差 → sigmoid 软比较 → 分摊指标与对手权重 → 共同对手联合拟合 → 统一0–100展示。':'同场原值 → 胜负平 → Benchmark 内指标分摊权重 → 共同对手联合拟合 → 统一0–100展示。'),el('p',snap.index.method.version>=4?'分数是连续分差拟合出的相对强度映射，不是正确率或校准的胜出概率。正则强度0.3采用论文/共享评测发布批次留出校准，兼顾预测与收缩。模型选择不改变公式和分数。':'分数表示相对于本版本参考群体中心强度的拟合胜率，不是正确率。细线为约95%模型区间；模型筛选不改变分数，未连接到主比较网络的模型保留原始成绩而不混排。','method-note'),el('p','至少3项 Benchmark 才发布总分。区间重叠时，不宜认定小数点上的名次差异有意义；少量覆盖、领域不均和选择性报告仍是局限。点击模型名查看真实对手、原值、区间与权重。','method-note'));
      else body.append(el('p','此快照使用旧版按各自已测项目平均的Z分数；请更新服务器并重新发布以启用对手校正。','method-note'));
      if(snap.index.publication_quality_audit){const q=snap.index.publication_quality_audit;body.append(el('p',`模型名称统一后比较；论文内占位符、未解析身份及不可比较来源有 ${q.identity_excluded_records} 条未纳入排名。标准差、效率和非能力指标有 ${q.non_capability_groups} 组保留在原始证据中，未计入能力综合分。`,'method-note'));}
      modelVisuals.update(data);return;
    }
    const relative=snap.index.method?.score_unit==='z_score',panels=(snap.index.score_panels||[]).filter(p=>p.model_setting===visualSetting),panel=selectedRankingPanel(visualSetting)||((snap.index.score_panel?.model_setting===visualSetting)?snap.index.score_panel:null),preparation=snap.index.scoring_preparation;
    const picker=$('ranking-panel');$('relative-panel-controls').hidden=rankingMode!=='panel'||!relative;picker.replaceChildren();
    for(const [i,p]of panels.entries())picker.append(new Option(`${i+1}. ${p.independent_benchmarks} 项测试 · ${p.published_models} 个模型 · ${(p.member_names||[]).join(' / ')}`,p.panel_id));
    if(panel?.panel_id){rankingPanels.set(visualSetting,panel.panel_id);picker.value=panel.panel_id;}picker.disabled=!panels.length;
    const verified=available.filter(g=>relative?g.relative_status==='READY':g.normalization_status==='APPROVED').length;
    const readiness=panel?`${panel.published_models??data.rows.filter(r=>r.score!==null).length} 个模型覆盖全部 ${panel.independent_benchmarks??new Set(panel.items.map(i=>available.find(g=>g.group_id===i.group_id)?.benchmark_identity||available.find(g=>g.group_id===i.group_id)?.benchmark_id)).size} 项测试。`:!relative&&preparation?.status==='PREPARING'?'服务器正在核验原表，稍后可刷新数据。':(snap.index.automatic_scoring?.reason||'尚未配置固定评测集合。');
    $('scoring-readiness').textContent=rankingMode==='source'?'展示同一来源、指标和实验设置的原始成绩；不合成跨测试总分。':`${verified} / ${available.length} 个评测组${relative?'可计算参考标准化分数':'已有核验量程'} · ${readiness}${relative?'0 为参考均值；正负值表示相对参考的表现。':''}点击模型名查看计算明细。`;
    const scope=$('scoring-scope');scope.hidden=rankingMode!=='panel';const scopeBody=$('scoring-scope-body');scopeBody.replaceChildren();
    if(panel){
      scopeBody.append(el('p',panel.name),el('p',panel.selection_note||'使用指定的固定评测集合。','method-note'),el('p',panel.interpretation,'method-note'));
      const byBench=new Map();for(const item of panel.items){const group=available.find(g=>g.group_id===item.group_id);if(!group)continue;const key=identity(group);if(!byBench.has(key))byBench.set(key,[]);byBench.get(key).push({item,group});}
      for(const [key,entries]of byBench){const bench=benches.get(key),section=el('details',null,'scoring-benchmark-section'),weight=entries.reduce((sum,x)=>sum+x.item.weight,0),name=bench?.benchmark_name||'来源 Benchmark';section.append(el('summary',`${name} · ${entries.length} 个指标 · 权重 ${fmt(weight*100)}%`));const source=el('a','查看来源成绩');source.href=new URL('benchmark/?'+new URLSearchParams({paper_id:entries[0].group.paper_id,benchmark_id:entries[0].group.benchmark_id,...(state.snapshot?.visitor_catalog_filtered?{}:{edition:'admin'})}),radarBase).href;section.append(source);
        for(const {item,group}of entries){const p=el('p',`${group.metric} · 权重 ${fmt(item.weight*100)}% · ${Viz.directionLabel(group.direction)}`);if(relative){const ref=group.reference_profile;p.append(el('small',`参考 ${ref.reference_count} 个模型 · 均值 ${statFmt(ref.mean)} · 标准差 ${statFmt(ref.standard_deviation)}`,'subtext'));}section.append(p);}scopeBody.append(section);}
    }
    else scopeBody.append(el('p',readiness));
    const reasons=relative?snap.index.relative_reference_audit?.counts||{}:preparation?.reason_counts||{},reasonNames={insufficient_reference_models:'参考模型少于 3 个',constant_reference_group:'同组数值全部相同，无区分度',nonfinite_reference_statistics:'统计数值异常',original_source_table_missing:'缺少原始表格',explicit_metric_bounds_missing:'原表未声明指标量程',source_cell_mismatch:'原始单元格不一致',source_numeric_mismatch:'原始数值不一致',blocked_or_incomplete_source_group:'来源冲突或提取未完成',conflicting_source_bounds:'原表量程声明冲突',metric_definition_missing:'缺少指标定义',value_outside_verified_scale:'数值超出量程'};
    const excluded=Object.entries(reasons).filter(([reason])=>!['APPROVED','READY'].includes(reason));if(excluded.length)scopeBody.append(el('p','未纳入的评测组：'+excluded.map(([reason,count])=>`${reasonNames[reason]||'其他核验未通过'} ${count} 组`).join('；'),'method-note'));
    if(rankingMode==='panel'){modelVisuals.update(data);return;}
    const ids=[...new Set(available.map(identity))].sort((a,b)=>(benches.get(a)?.benchmark_name||a).localeCompare(benches.get(b)?.benchmark_name||b)),select=$('ranking-benchmark');
    if(!ids.includes(rankingBenchmark))rankingBenchmark=ids[0]||'';
    select.replaceChildren();for(const id of ids){const b=benches.get(id);select.append(new Option((b?.benchmark_name||'未命名 Benchmark')+' · '+(b?.arxiv_id||date(b?.release_date)),id));}select.value=rankingBenchmark;
    const groups=available.filter(g=>identity(g)===rankingBenchmark),metrics=$('ranking-group');
    if(!groups.some(g=>g.group_id===rankingGroup))rankingGroup=groups[0]?.group_id||'';
    metrics.replaceChildren();for(const [i,g] of groups.entries())metrics.append(new Option(g.metric+(Viz.measurementLabel(g)?'（'+Viz.measurementLabel(g)+'）':'')+' · '+Viz.directionLabel(g.direction)+' · 来源 '+(i+1),g.group_id));metrics.value=rankingGroup;
    const group=groups.find(g=>g.group_id===rankingGroup),bench=benches.get(rankingBenchmark);
    if(!group||!bench){modelVisuals.clear();return;}
    modelVisuals.update(Viz.sourceGroupData(snap,bench,group));
  }
  $('ranking-mode').addEventListener('change',e=>{rankingMode=e.target.value;rankingModeChosen=true;renderRanking(rankingData());});
  $('ranking-panel').addEventListener('change',e=>{rankingPanels.set(visualSetting,e.target.value);renderRanking(rankingData());renderModels();modelDialog?.refresh();});
  $('ranking-benchmark').addEventListener('change',e=>{rankingBenchmark=e.target.value;rankingGroup='';renderRanking(rankingData());});
  $('ranking-group').addEventListener('change',e=>{rankingGroup=e.target.value;renderRanking(rankingData());});
  const pairModelPickers=new WeakMap();
  function pairModelPicker(select,label){
    if(pairModelPickers.has(select))return pairModelPickers.get(select);
    const root=el('div',null,'pair-picker'),trigger=el('button',null,'pair-picker-trigger'),caption=el('span'),chevron=el('span',null,'pair-picker-chevron');
    const panel=el('div',null,'pair-picker-panel'),heading=el('div',null,'pair-picker-heading'),closeButton=el('button','×','pair-picker-close'),search=el('input',null,'pair-picker-search'),list=el('div',null,'pair-picker-list'),footer=el('div',null,'pair-picker-footer'),count=el('span'),more=el('button','显示更多','pair-picker-more');
    trigger.type=closeButton.type=more.type='button';trigger.setAttribute('aria-haspopup','dialog');trigger.setAttribute('aria-expanded','false');trigger.setAttribute('aria-controls',select.id+'-picker');chevron.setAttribute('aria-hidden','true');trigger.append(caption,chevron);
    panel.id=select.id+'-picker';panel.hidden=true;panel.setAttribute('role','dialog');panel.setAttribute('aria-label','选择'+label);
    closeButton.setAttribute('aria-label','关闭'+label+'选择');heading.append(el('strong','选择'+label),closeButton);
    search.type='search';search.placeholder='搜索模型、别名或厂商';search.autocomplete='off';search.setAttribute('aria-label','搜索'+label);search.setAttribute('role','combobox');search.setAttribute('aria-autocomplete','list');search.setAttribute('aria-controls',select.id+'-options');search.setAttribute('aria-expanded','false');
    list.id=select.id+'-options';list.setAttribute('role','listbox');list.setAttribute('aria-label',label+'型号');footer.append(count,more);panel.append(heading,search,list,footer);root.append(trigger,panel);select.after(root);select.classList.add('pair-native-select');
    let rows=[],filtered=[],buttons=[],active=-1,limit=60;
    const card=select.closest('.pair-model-card');
    function sync(){caption.textContent=select.value||'选择模型';trigger.title=select.value;trigger.disabled=!select.options.length;trigger.setAttribute('aria-label',label+'：'+(select.value||'未选择'));}
    function close(restore=false){panel.hidden=true;trigger.setAttribute('aria-expanded','false');search.setAttribute('aria-expanded','false');search.removeAttribute('aria-activedescendant');card?.classList.remove('pair-picker-open');if(restore)trigger.focus({preventScroll:true});}
    function highlight(index,scroll=false){active=index;buttons.forEach((b,i)=>b.classList.toggle('is-active',i===index));if(buttons[index]){search.setAttribute('aria-activedescendant',buttons[index].id);if(scroll)buttons[index].scrollIntoView({block:'nearest'});}else search.removeAttribute('aria-activedescendant');}
    function render(){
      filtered=rows.filter(r=>Viz.matchesModelQuery(r,search.value.trim()));list.replaceChildren();buttons=[];active=-1;search.removeAttribute('aria-activedescendant');let previousVendor='';
      for(const [i,row]of filtered.slice(0,limit).entries()){
        const info=Viz.modelInfo(row);if(info.vendor!==previousVendor){const group=el('div',info.vendor,'pair-picker-group');group.setAttribute('role','presentation');list.append(group);previousVendor=info.vendor;}
        const option=el('button',null,'pair-picker-option'),dot=el('span',null,'pair-picker-dot'),body=el('span',null,'pair-picker-option-body'),check=el('span',null,'pair-picker-check');
        option.type='button';option.id=select.id+'-option-'+i;option.tabIndex=-1;option.setAttribute('role','option');option.setAttribute('aria-selected',String(row.name===select.value));dot.style.background=Viz.vendorColor(info.vendor);dot.setAttribute('aria-hidden','true');check.setAttribute('aria-hidden','true');body.append(el('strong',row.name),el('small',`${row.nBenchmarks||0} 项可比 Benchmark`));option.append(dot,body,check);option.title=row.name;
        option.onclick=()=>{select.value=row.name;sync();close(true);select.dispatchEvent(new Event('change',{bubbles:true}));};option.onpointermove=()=>highlight(i);buttons.push(option);list.append(option);
      }
      if(!filtered.length)list.append(el('p','未检索到匹配型号，请调整检索关键词或筛选条件。','pair-picker-empty'));
      count.textContent=`${filtered.length} 个型号${filtered.length>limit?' · 已显示 '+limit+' 个':''}`;more.hidden=filtered.length<=limit;
    }
    function open(){document.dispatchEvent(new Event('radar-pair-picker-open'));search.value='';limit=60;render();panel.hidden=false;trigger.setAttribute('aria-expanded','true');search.setAttribute('aria-expanded','true');card?.classList.add('pair-picker-open');search.focus({preventScroll:true});}
    trigger.onclick=()=>panel.hidden?open():close(true);closeButton.onclick=()=>close(true);
    search.oninput=()=>{limit=60;render();list.scrollTop=0;};more.onclick=()=>{limit+=60;render();search.focus({preventScroll:true});};
    panel.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close(true);}else if(e.target===search&&['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();highlight(Math.max(0,Math.min(buttons.length-1,active+(e.key==='ArrowDown'?1:-1))),true);}else if(e.target===search&&e.key==='Enter'&&buttons[active]){e.preventDefault();buttons[active].click();}};
    root.addEventListener('focusout',e=>{if(!root.contains(e.relatedTarget))close();});
    document.addEventListener('pointerdown',e=>{if(!root.contains(e.target))close();});document.addEventListener('radar-pair-picker-open',()=>close());
    const api={sync,close,update(next){rows=next;close();sync();}};pairModelPickers.set(select,api);sync();return api;
  }
  const pairPreferences=new Map();
  let pairView='benchmark';
  function renderPairedSources(data) {
    const left=$('pair-left'),right=$('pair-right'),body=$('pair-rows');
    const leftPicker=pairModelPicker(left,'模型 A'),rightPicker=pairModelPicker(right,'模型 B');
    const names=[...data.rows].sort((a,b)=>b.nBenchmarks-a.nBenchmarks||a.name.localeCompare(b.name)).map(r=>r.name);
    const oldLeft=left.value,oldRight=right.value;
    const order=$('pair-model-order'),vendorFilter=$('pair-vendor-filter'),search=$('pair-model-search');
    const priorVendor=vendorFilter.value;vendorFilter.replaceChildren(new Option('全部厂商',''));for(const vendor of [...new Set(data.rows.map(r=>Viz.modelInfo(r).vendor))].sort((a,b)=>Number(a==='其他 / 厂商待确认')-Number(b==='其他 / 厂商待确认')||a.localeCompare(b)))vendorFilter.append(new Option(vendor,vendor));vendorFilter.value=priorVendor;
    function fillChoices(){
      const filtered=Viz.sortModelChoices(data.rows,order.value).filter(r=>(!vendorFilter.value||Viz.modelInfo(r).vendor===vendorFilter.value)&&Viz.matchesModelQuery(r,search.value.trim()));
      $('pair-choice-count').textContent=`${filtered.length} 个匹配型号`;
      for(const select of [left,right]){const current=select.value;select.replaceChildren();let group=null,previousVendor='';
        if(current&&!filtered.some(r=>r.name===current)){const kept=el('optgroup');kept.label='当前选择';kept.append(new Option(current,current));select.append(kept);}
        for(const row of filtered){const info=Viz.modelInfo(row);if(order.value==='vendor'){if(info.vendor!==previousVendor){group=el('optgroup');group.label=info.vendor;select.append(group);previousVendor=info.vendor;}group.append(new Option(row.name,row.name));}else select.append(new Option(row.name,row.name));}
        if(names.includes(current))select.value=current;
        (select===left?leftPicker:rightPicker).update(filtered);
      }
    }
    fillChoices();order.onchange=fillChoices;vendorFilter.onchange=fillChoices;search.oninput=fillChoices;
    const defaults=Viz.defaultPairedModels(state.snapshot,visualSetting,names);
    left.value=names.includes(oldLeft)?oldLeft:(defaults[0]||names[0]||'');right.value=names.includes(oldRight)&&oldRight!==left.value?oldRight:(defaults[1]||names.find(n=>n!==left.value)||'');
    let chosen=new Set(),sourceChoices=new Map(),previousPair='';
    function draw(){
      $('pair-benchmark-view').hidden=pairView!=='benchmark';$('pair-capability-view').hidden=pairView!=='capability';
      $('pair-view-benchmark').setAttribute('aria-pressed',String(pairView==='benchmark'));$('pair-view-capability').setAttribute('aria-pressed',String(pairView==='capability'));
      if(pairView==='capability')Viz.drawCapabilityRadar($('pair-capability-view'),Viz.capabilityRadarData(state.snapshot,visualSetting,left.value,right.value,taskTaxonomy.capabilities),left.value,right.value,name=>openModel(name,visualSetting),r=>new URL('benchmark/?'+new URLSearchParams({paper_id:r.paper,benchmark_id:r.benchmark,...(state.snapshot?.visitor_catalog_filtered?{}:{edition:'admin'})}),radarBase).href);
      const rows=Viz.pairedSources(state.snapshot,visualSetting,left.value,right.value),axes=Viz.pairedBenchmarkAxes(state.snapshot,visualSetting,left.value,right.value);body.replaceChildren();
      const pair=JSON.stringify([visualSetting,left.value,right.value]);if(pair!==previousPair){const pref=pairPreferences.get(pair);chosen=new Set(pref?pref.selected.filter(id=>axes.some(a=>a.id===id)):axes.slice(0,6).map(a=>a.id));sourceChoices=new Map(pref?.sources||[]);previousPair=pair;}
      $('pair-summary').textContent=rows.length?`${axes.length} 个共同 Benchmark · ${rows.length} 个同组来源；当前雷达选择 ${chosen.size} 个 Benchmark。`:'这两个模型没有同组可核验成绩；不使用间接推断补出分数。';
      const list=$('pair-benchmarks');list.replaceChildren();
      const raw=x=>new Intl.NumberFormat('zh-CN',{maximumFractionDigits:8}).format(x);
      for(const axis of axes){
        const item=el('div',null,'pair-benchmark-option'),choice=el('label'),check=el('input');check.type='checkbox';check.checked=chosen.has(axis.id);check.disabled=!check.checked&&chosen.size>=8;choice.append(check,document.createTextNode(axis.name));
        const remember=()=>pairPreferences.set(pair,{selected:[...chosen],sources:[...sourceChoices]});
        check.onchange=()=>{if(check.checked)chosen.add(axis.id);else chosen.delete(axis.id);remember();draw();};
        const select=el('select');select.setAttribute('aria-label',axis.name+' 来源指标');axis.groups.forEach((r,i)=>{const option=new Option(`${r.metric} · 来源 ${i+1} · ${r.sourceModels} 个模型`,r.group);option.title=[sourceLabel(r.paper,r.table),Viz.publicLabel(r.row)].filter(Boolean).join(' · ');select.append(option);});
        select.value=sourceChoices.get(axis.id)||axis.groups[0].group;select.onchange=()=>{sourceChoices.set(axis.id,select.value);remember();draw();};
        axis.source=axis.groups.find(r=>r.group===select.value)||axis.groups[0];
        item.append(choice,select);list.append(item);
      }
      const selected=axes.filter(a=>chosen.has(a.id));Viz.drawPairedRadar($('pair-radar'),selected,left.value,right.value,name=>openModel(name,visualSetting));
      for(const axis of selected){const r=axis.source,tr=el('tr'),source=el('td'),a=el('a',r.benchmarkName);a.href=new URL('benchmark/?'+new URLSearchParams({paper_id:r.paper,benchmark_id:r.benchmark,...(state.snapshot?.visitor_catalog_filtered?{}:{edition:'admin'})}),radarBase).href;source.append(a,el('span',sourceLabel(r.paper,r.table),'subtext'));tr.append(source,el('td',r.metric+' · '+Viz.directionLabel(r.direction)),el('td',raw(r.left),'numeric'),el('td',raw(r.right),'numeric'),el('td',(r.delta>0?'+':'')+raw(r.delta),'numeric'),el('td',r.winner==='TIE'?'同值':r.winner));body.append(tr);}
      $('pair-left-heading').textContent=left.value||'模型 A';$('pair-right-heading').textContent=right.value||'模型 B';
      $('pair-left-vendor').textContent=Viz.modelInfo(left.value).vendor;$('pair-right-vendor').textContent=Viz.modelInfo(right.value).vendor;
      left.title=left.value;right.title=right.value;$('pair-swap').disabled=!left.value||!right.value||left.value===right.value;
      leftPicker.sync();rightPicker.sync();
      for(const [id,select] of [['pair-left-details',left],['pair-right-details',right]]){const b=$(id);b.disabled=!select.value;b.onclick=()=>openModel(select.value,visualSetting);}
      const registry=state.snapshot?.model_registry?.models||[];
      const aliases=[left.value,right.value].map(name=>{const entry=registry.find(m=>m.comparison_names?.includes(name));return entry&&entry.source_names.length>1?name+'：'+entry.source_names.join('、'):null;}).filter(Boolean);
      $('pair-name-audit').textContent=aliases.length?'名称归一 · '+aliases.join('；')+'。版本、规模与实验设置保留，原始名称可在来源中追溯。':'名称由后端统一；版本、规模、训练变体与实验设置保留，缺少型号的品牌名称不参与排名。';

    }
    $('pair-view-benchmark').onclick=()=>{pairView='benchmark';draw();};$('pair-view-capability').onclick=()=>{pairView='capability';draw();};
    left.onchange=draw;right.onchange=draw;$('pair-swap').onclick=()=>{const previous=left.value,next=right.value;for(const [select,value] of [[left,next],[right,previous]]){if(![...select.options].some(o=>o.value===value)){const kept=el('optgroup');kept.label='当前选择';kept.append(new Option(value,value));select.prepend(kept);}select.value=value;}draw();};draw();
  }
  function renderDetailVisuals() {
    const b=state.snapshot?.benchmarks.find(b=>identity(b)===state.selected);if(!b){detailVisuals.clear();return;}
    const gs=groups(b),choices=[...new Set(gs.map(g=>g.model_setting))].sort(),select=$('detail-visual-setting');
    if(!choices.includes(detailVisualSetting))detailVisualSetting=choices[0]??'';select.replaceChildren();for(const x of choices)select.append(new Option(x||'未另列实验设置',x));select.value=detailVisualSetting;
    const metrics=[...new Set(gs.filter(g=>g.model_setting===detailVisualSetting).map(g=>g.metric))].sort(),metric=$('detail-visual-metric');
    if(!metrics.includes(detailVisualMetric))detailVisualMetric=metrics[0]||'';metric.replaceChildren();for(const x of metrics)metric.append(new Option(x,x));metric.value=detailVisualMetric;
    detailVisuals.update(Viz.benchmarkData(state.snapshot,b,detailVisualSetting,detailVisualMetric));
  }
  $('visual-setting').addEventListener('change',e=>{visualSetting=e.target.value;renderVisuals();renderModels();});
  $('detail-visual-setting').addEventListener('change',e=>{detailVisualSetting=e.target.value;renderDetailVisuals();});
  $('detail-visual-metric').addEventListener('change',e=>{detailVisualMetric=e.target.value;renderDetailVisuals();});
  function render() {
    renderCounts();
    if(state.view==='benchmarks'){renderVisuals();renderBenchmarks();renderDetail();}
    else if(state.view==='models'){renderVisuals();renderModels();}
    else if(state.view==='tasks')renderTaskWorkspace();
    else if(state.view==='capabilities')renderCapabilityMap();
    modelDialog?.refresh();
    if(visitorEdition)window.dispatchEvent(new CustomEvent('radar:render',{detail:{snapshot:state.snapshot,view:state.view}}));
    if(requestedModel&&state.snapshot&&state.snapshot.detail_loaded!==false){const name=requestedModel;requestedModel=null;if(state.snapshot.observations.some(row=>row.model_canonical===name))openModel(name);}
  }
  function validate(d) {if(!d||typeof d!=='object'||!Array.isArray(d.benchmarks)||!Array.isArray(d.observations)||!Array.isArray(d.status?.jobs)||!d.index||!Array.isArray(d.index.models)||!d.window||!Number.isFinite(d.window.days)||d.window.days<=0||!Number.isFinite(Date.parse(d.generated_at)))throw Error('INVALID_RADAR_DATA');return visitorEdition?Viz.visitorSnapshot(d):d;}
  const REFRESH_INTERVAL_MS=10*60*1000;let lastRefreshAt=0;
  function decodeSnapshot(d){
    if(!d?.wire_format)return d;
    const payload=d.payload;
    if(d.wire_format!=='radar-shared-json-v1'||!Array.isArray(payload?.nodes)||!Array.isArray(payload.schemas))throw Error('INVALID_RADAR_DATA');
    if(payload.schemas.some(keys=>!Array.isArray(keys)||keys.some(k=>typeof k!=='string')))throw Error('INVALID_RADAR_DATA');
    const values=[];
    function decode(node){
      if(typeof node==='string'&&node.startsWith('\0')){
        if(node.startsWith('\0:'))return node.slice(2);
        const ref=node.slice(1);if(!/^(?:0|[1-9][0-9]*)$/.test(ref)||Number(ref)>=values.length)throw Error('INVALID_RADAR_DATA');
        return values[Number(ref)];
      }
      if(!Array.isArray(node))return node;
      const [kind,...children]=node;if(!Number.isInteger(kind))throw Error('INVALID_RADAR_DATA');
      if(kind===0)return children.map(decode);
      const keys=payload.schemas[kind-1];if(!keys||keys.length!==children.length)throw Error('INVALID_RADAR_DATA');
      const obj={};for(let i=0;i<keys.length;i++)Object.defineProperty(obj,keys[i],{value:decode(children[i]),enumerable:true,writable:true,configurable:true});return obj;
    }
    for(const node of payload.nodes)values.push(decode(node));
    const data=decode(payload.root);if(!data?.snapshot||!data.status_arrays)throw Error('INVALID_RADAR_DATA');
    return {...data.snapshot,snapshot_id:d.snapshot_id,generated_at:d.generated_at,window:d.window,status:{...d.status,...data.status_arrays}};
  }
  async function fetchSnapshotJSON(path,timeoutMs,waitForPublication=false) {
    const ctrl=new AbortController(),timer=setTimeout(()=>ctrl.abort(),timeoutMs);
    try {
      if(window.RadarSnapshotMode&&window.RadarLoadWorkspace&&['api/workspace','api/snapshot'].includes(path)){
        const data=await window.RadarLoadWorkspace({signal:ctrl.signal,onProgress:text=>{$('connection').textContent=text;}});
        return validate(decodeSnapshot(data));
      }
      for(let attempt=0;;attempt++){
        ctrl.signal.throwIfAborted();
        const res=await fetch(new URL(path,radarBase),{cache:'no-store',signal:ctrl.signal});
        if(res.ok)return validate(decodeSnapshot(await res.json()));
        if(res.status===404&&path==='api/workspace'){path='api/snapshot';continue;}
        let code='RADAR_UNAVAILABLE';try{code=(await res.json()).error||code;}catch{}
        if(!waitForPublication||res.status!==503||!['snapshot_initializing','snapshot_refreshing'].includes(code)||attempt>=7)throw Error(code);
        $('connection').textContent=state.snapshot?.detail_loaded!==false&&state.snapshot?'后台正在发布当前窗口 · 保留当前图表':'后台正在发布当前窗口 · 就绪后继续加载…';
        await new Promise((resolve,reject)=>{
          const abort=()=>{clearTimeout(pause);reject(ctrl.signal.reason);};
          const pause=setTimeout(()=>{ctrl.signal.removeEventListener('abort',abort);resolve();},Math.min(2000*(attempt+1),8000));
          ctrl.signal.addEventListener('abort',abort,{once:true});
          if(ctrl.signal.aborted)abort();
        });
      }
    } finally {clearTimeout(timer);}
  }
  function setLoadingUI(loading) {
    document.body.dataset.loading=String(loading);
    document.body.dataset.detailReady=String(Boolean(state.snapshot&&state.snapshot.detail_loaded!==false));
    for(const root of document.querySelectorAll('.viz-card,.paired-values'))root.setAttribute('aria-busy',String(loading&&(!state.snapshot||state.snapshot.detail_loaded===false)));
  }
  let refreshInFlight=null,refreshHasDetails=false;
  function refresh(options={}) {
    if(refreshInFlight){
      if(options.details&&!refreshHasDetails)return refreshInFlight.then(()=>!state.snapshot||state.snapshot.detail_loaded===false?refresh(options):undefined);
      return refreshInFlight;
    }
    refreshHasDetails=Boolean(options.details);
    refreshInFlight=refreshData(options).finally(()=>{refreshInFlight=null;refreshHasDetails=false;});
    return refreshInFlight;
  }
  async function refreshData({details=false}={}) {
    if(state.loading)return;
    lastRefreshAt=Date.now();state.loading=true;$('refresh').disabled=true;let overviewLoaded=false;const previous=state.snapshot;setLoadingUI(true);
    const node=$('connection');node.className='connection';node.textContent=previous?'正在更新 · 保留当前内容':'正在加载目录与图表…';
    try {
      if(window.RadarHomeSnapshot&&!details&&!requestedModel&&(state.view==='home'||state.view==='tasks')){
        if(!previous||previous.detail_loaded===false)state.snapshot=validate(window.RadarHomeSnapshot);
        render();resumeInteractive();node.textContent='固定快照 · 数据截至 '+date(state.snapshot.generated_at);if(state.view==='tasks')await loadTaskEvidenceForPreview();return;
      }
      if(window.RadarHomeSnapshot){
        if(!previous){state.snapshot=validate(window.RadarHomeSnapshot);render();resumeInteractive();}
        overviewLoaded=true;
      }else try {
        const overview=await fetchSnapshotJSON('api/overview',15000);
        if(taskState.result&&taskState.evidenceRevision!==overview.status.task_evidence_revision){taskState.result=null;$('task-results').hidden=true;}
        overviewLoaded=true;if(!previous||previous.detail_loaded===false){state.snapshot=overview;render();resumeInteractive();setLoadingUI(true);}
        node.textContent=previous?.detail_loaded!==false&&previous?'正在更新 · 保留当前图表':'目录已就绪 · 正在加载图表…';
      } catch {}
      const d=await fetchSnapshotJSON('api/workspace',120000,true);
      state.snapshot=d;Viz.setModelRegistry(d.model_registry);if(state.view==='tasks'&&!window.RadarSnapshotMode)try{await ensureTaskMeasurements();}catch(error){taskMessage('task-score-message',error.message,'warning');}render();resumeInteractive();
      if(taskState.confirmed&&!taskState.busy&&taskState.evidenceRevision!==d.status.task_evidence_revision)scoreTask(true);
      const preview=d.status.preview_note,stale=d.status.stale;
      node.className=`connection ${preview||stale?'warning':''}`;
      node.textContent=window.RadarSnapshotMode?'固定快照 · 数据截至 '+date(d.generated_at):d.status.window_refreshing?`日期窗口更新中 · 显示 ${date(d.window.end)} 截至的核验快照`:preview?'本地数据预览':stale?'数据已连接 · 后台更新较慢':'已连接 · 已核验来源数据';node.title=d.status.window_refreshing?d.status.reason:preview||'成绩来自公开论文，未独立复现。';
    } catch(err) {
      if(!overviewLoaded&&!previous){state.snapshot=null;taskState.result=null;state.selected=null;render();}
      node.className='connection '+(overviewLoaded||previous?'warning':'error');
      const retry='页面按 10 分钟间隔自动刷新，也可点击“刷新数据”。';
      node.textContent=err.name==='AbortError'?(overviewLoaded?'首页可用；完整图表和来源成绩读取超时。':'完整快照读取超时。')+retry:
        err.message==='snapshot_initializing'?'后台正在生成首批快照。'+retry:
        err.message==='snapshot_refreshing'?'当前日期窗口的榜单正在更新。'+retry:
        err.message==='snapshot_unavailable'?'完整快照生成失败，请检查服务日志。'+retry:
        err.message==='INVALID_RADAR_DATA'?'快照字段不符合页面要求。'+retry:
        err.message==='RADAR_NOT_CONFIGURED'?'尚未配置可用的评测服务地址。':
        (overviewLoaded?'目录可用，图表和来源成绩暂未加载。':'暂时无法读取评测数据，请检查服务连接。')+retry;
      if(previous)node.textContent='更新未完成，显示上次已加载内容。'+node.textContent;
    } finally {state.loading=false;$('refresh').disabled=false;setLoadingUI(false);renderReferences();}
  }
  for(const btn of document.querySelectorAll('[data-view]'))btn.addEventListener('click',()=>setView(btn.dataset.view));$('refresh').addEventListener('click',refresh);$('search').addEventListener('input',e=>{state.query=e.target.value;state.benchmarkLimit=40;renderBenchmarks();});$('eligibility').addEventListener('change',e=>{state.eligibility=e.target.value;state.benchmarkLimit=40;renderBenchmarks();});$('more-benchmarks').addEventListener('click',()=>{state.benchmarkLimit+=40;renderBenchmarks();});$('model-sort').addEventListener('change',e=>{state.sort=e.target.value;state.modelLimit=100;renderModels();});$('more-models').addEventListener('click',()=>{state.modelLimit+=100;renderModels();});$('close-detail').addEventListener('click',()=>{state.selected=null;$('detail').hidden=true;});$('metric-group').addEventListener('change',e=>{state.group=e.target.value;const b=state.snapshot?.benchmarks.find(b=>identity(b)===state.selected);if(b)renderBars(b);});$('more-scores').addEventListener('click',()=>{state.scoreLimit+=80;renderDetail();});
  window.addEventListener('radar:task-connected',()=>{if(state.view==='tasks')loadTaskEvidenceForPreview().catch(error=>taskMessage('task-score-message',error.message,'warning'));});
  const lifecycle=new AbortController();window.addEventListener('pagehide',()=>lifecycle.abort(),{once:true});
  if(document.modelContext?.registerTool){
    const register=t=>Promise.resolve(document.modelContext.registerTool(t,{signal:lifecycle.signal})).catch(()=>{});
    register({name:'get_radar_catalog',title:'读取当前窗口评测目录',description:'读取已加载的评测目录与窗口，不运行检索或评测。',inputSchema:{type:'object',properties:{},additionalProperties:false},annotations:{readOnlyHint:true,untrustedContentHint:true},execute(input){if(!input||Array.isArray(input)||typeof input!=='object'||Object.keys(input).length)throw Error('输入必须为空对象');if(!state.snapshot)throw Error('评测数据源未连接');return {generated_at:state.snapshot.generated_at,window:state.snapshot.window,source_note:state.snapshot.status.preview_note||'评测 API',benchmarks:state.snapshot.benchmarks.map(b=>({paper_id:b.paper_id,benchmark_id:b.benchmark_id,name:b.benchmark_name,eligibility:b.eligibility,observations:observations(b).length}))};}});
    register({name:'set_radar_view',title:'切换评测数据视图',description:'切换当前页面视图与 benchmark 筛选，只改变显示，不修改队列。',inputSchema:{type:'object',properties:{view:{enum:['benchmarks','tasks','capabilities','models']},query:{type:'string',maxLength:200},eligibility:{enum:['all','ELIGIBLE','review']}},required:['view','query','eligibility'],additionalProperties:false},annotations:{readOnlyHint:false,untrustedContentHint:true},execute(input){if(!input||typeof input!=='object'||Array.isArray(input)||Object.keys(input).some(k=>!['view','query','eligibility'].includes(k))||!['benchmarks','tasks','capabilities','models'].includes(input.view)||typeof input.query!=='string'||input.query.length>200||!['all','ELIGIBLE','review'].includes(input.eligibility))throw Error('视图或筛选输入无效');state.query=input.query;state.eligibility=input.eligibility;state.benchmarkLimit=40;$('search').value=state.query;$('eligibility').value=state.eligibility;setView(input.view);if(input.view==='benchmarks')renderBenchmarks();return {view:state.view,visible_benchmarks:visibleBenchmarks().length,connected:!!state.snapshot};}});
  }
  if(visitorEdition)window.RadarApp=Object.freeze({
    navigate(view){setView(view);window.scrollTo({top:0,behavior:'instant'});},
    async openModel(name,setting){if(!state.snapshot||state.snapshot.detail_loaded===false)await refresh({details:true});openModel(name,setting);},
    openBenchmark(paperId,benchmarkId){const benchmark=state.snapshot?.benchmarks.find(b=>b.paper_id===paperId&&b.benchmark_id===benchmarkId);if(benchmark&&state.snapshot.detail_loaded!==false){selectBenchmark(benchmark);return true;}return false;},
    useTemplate(id){const template=TASK_DEFAULTS.templates[id];if(!template)return;applyProfile(template);taskState.refsInitialized=false;setView('tasks');renderReferences();window.scrollTo({top:0,behavior:'instant'});}
  });
  const hashView=()=>{const requested=location.hash.slice(1).replace(/-view$/,'');const view=requested==='pipeline'?'benchmarks':requested;if(['benchmarks','tasks','capabilities','models',...(visitorEdition?['home']:[])].includes(view))setView(view);};
  hashView();window.addEventListener('hashchange',hashView);
  initTaskWorkspace();if(visitorEdition)setView(state.view);uiReady=true;render();refresh();if(!window.RadarSnapshotMode)setInterval(()=>{if(!document.hidden&&Date.now()-lastRefreshAt>=REFRESH_INTERVAL_MS)refresh();},REFRESH_INTERVAL_MS);document.addEventListener('visibilitychange',()=>{if(!window.RadarSnapshotMode&&!document.hidden&&Date.now()-lastRefreshAt>=REFRESH_INTERVAL_MS)refresh();});
})();
