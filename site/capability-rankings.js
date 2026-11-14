(() => {
  'use strict';
  const charts = document.querySelector('#view-models #model-visuals')?.parentElement;
  if (!charts) return;
  const en = document.documentElement.lang === 'en';
  const txt = (zh, english) => en ? english : zh;
  function element(tag, text, cls) {
    const node = document.createElement(tag);
    if (text != null) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  }
  const section = element('section', null, 'ability-boards');
  const heading = element('h3', txt('能力分榜', 'Capability rankings'));
  const grid = element('div', null, 'ability-board-grid');
  section.append(heading, grid);
  charts.after(section);
  const dialog = element('dialog', null, 'ability-board-dialog');
  document.body.append(dialog);
  let opener, inMotion, closing = false;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  function animate(opening) {
    inMotion?.cancel();
    if (reduced.matches || !opener || !dialog.animate) return Promise.resolve();
    const from = opener.getBoundingClientRect(), to = dialog.getBoundingClientRect();
    const collapsed = { transform: 'translate(' + (from.left + from.width/2 - to.left - to.width/2) + 'px,' +
      (from.top + from.height/2 - to.top - to.height/2) + 'px) scale(' + from.width/to.width + ',' + from.height/to.height + ')', opacity: .18 };
    const full = {transform:'none',opacity:1};
    inMotion = dialog.animate(opening ? [collapsed, full] : [full, collapsed],
      {duration:opening ? 280 : 190, easing:'cubic-bezier(.2,.75,.25,1)', fill:'none'});
    return inMotion.finished.catch(() => {});
  }
  async function dismiss() {
    if (closing || !dialog.open) return;
    closing = true;
    await animate(false);
    dialog.close();
    document.body.classList.remove('ability-board-modal-open');
    opener?.setAttribute('aria-expanded','false');
    opener?.focus({preventScroll:true});
    closing = false;
  }
  dialog.addEventListener('cancel', e => {e.preventDefault();dismiss();});
  dialog.addEventListener('click', e => {if (e.target === dialog) {
    const r = dialog.getBoundingClientRect();
    if(e.clientX<r.left || e.clientX>r.right || e.clientY<r.top || e.clientY>r.bottom) dismiss();
  }});
  const modelName = row => row.model + (row.setting ? ' · ' + row.setting : '');
  function showBoard(category, rows, sources, status, trigger) {
    opener = trigger;
    dialog.replaceChildren();
    const head = element('header', null, 'ability-board-head');
    const title = element('h2', category + txt(' 能力榜',' rankings'));
    title.id = 'ability-board-title'; dialog.setAttribute('aria-labelledby',title.id);
    const close = element('button', '×','ability-board-close');
    close.type='button'; close.autofocus=true; close.setAttribute('aria-label',txt('收起榜单','Close rankings'));
    close.onclick=dismiss; head.append(title,close);
    const content = element('div',null,'ability-board-body');
    const n = new Set(rows.flatMap(r => r.sources)).size;
    content.append(element('p',en ? rows.length+' entries · '+n+' benchmarks' : rows.length+' 个模型及配置 · '+n+' 项计分评测','ability-board-meta'));
    const method=element('details',null,'ability-method');
    const minimum = status.min_papers ?? 5;
    method.append(element('summary',txt('评分方法','Scoring method')),element('p',txt(
      `本榜采用本领域同条件比较的加权 Bradley–Terry 拟合，直接展示 Elo。至少 ${minimum} 篇来源论文的模型才展示。`,
      `Weighted Bradley–Terry ratings from matched comparisons in this field, displayed as Elo. Entries need ${minimum} source papers for display.`)));
    method.append(element('p',txt('总榜与四个分榜采用同一组固定参照模型及权重，将参照组的加权平均 Elo 设为 1000；保留原有 Elo 分差。各榜反映对应领域内相对参照组的表现，不代表相同的绝对能力。','All five rankings use the same fixed reference models and weights, centering their weighted mean Elo at 1000 while preserving Elo differences. Ratings express performance relative to that panel within each domain, not identical absolute ability across domains.')));
    method.append(element('p',txt('对局采用分差软胜负：题目数与准确率口径经核验时使用二项近似，其余指标使用同评测、同指标的表内分差尺度；原始 Elo 指标使用 Elo 胜率公式。','Comparisons use soft outcomes from score differences: a binomial approximation for reviewed accuracy and sample counts, an empirical within-table difference scale for other metrics, and the Elo expected-score formula for Elo metrics.')));
    method.append(element('p',txt(
      '分榜优先采用来源表中具体指标所测的任务。指标只有通用标签时，结合评测的领域和任务归类。同一评测的不同指标可以进入不同分榜。',
      'Categories use the task measured by each source-table metric. For broadly labelled metrics, the benchmark subject and tasks provide context. Different metrics from one benchmark can enter different rankings.')));
    content.append(method);
    method.append(element('p',txt(
      '论文数量门槛仅控制榜单展示。低于门槛的模型仍作为比较对象参与拟合，其来源成绩保留；隐藏模型不会触发重新拟合。',
      'The paper threshold only controls ranking visibility. Models below it remain comparison opponents in the fit, and their source results are retained. Hiding entries does not refit the model.')));
    const basket = status.basket;
    if (basket.status === 'INSUFFICIENT_REFERENCE_PAPERS') {
      const counts = Object.entries(basket.observed_papers).map(([name,n]) => name+' ('+n+'/'+basket.minimum_independent_papers_per_board+')');
      content.append(element('p',txt('参照模型的独立论文数未达门槛：','Reference models below the independent-paper minimum: ')+counts.join(', ')));
    } else if (!rows.length) content.append(element('p', en
      ? `No entry currently meets the display threshold of ${minimum} source papers.`
      : `当前没有达到至少 ${minimum} 篇来源论文展示门槛的模型。`));
    const table=element('table',null,'ability-rank-table'), header=table.createTHead().insertRow(), body=table.createTBody();
    for(const name of [txt('名次','Rank'),txt('模型','Model'),'Elo',txt('来源论文','Papers'),txt('参评评测','Benchmarks')]){
      const th=element('th',name);th.scope='col';header.append(th);
    }
    rows.forEach((row,i)=>{
      const tr=body.insertRow();tr.insertCell().textContent=i+1;
      const name=tr.insertCell(), toggle=element('button',modelName(row),'ability-rank-model');toggle.type='button';toggle.setAttribute('aria-expanded','false');name.append(toggle);
      tr.insertCell().textContent=row.score.toFixed(1);
      tr.insertCell().textContent=row.papers;
      tr.insertCell().textContent=row.sources.length;
      toggle.onclick=()=>{
        const open=toggle.getAttribute('aria-expanded')==='true';
        toggle.setAttribute('aria-expanded',String(!open));
        if(open){tr.nextElementSibling.remove();return;}
        const more=body.insertRow(tr.sectionRowIndex+1),cell=more.insertCell();cell.colSpan=header.cells.length;
        const links=element('div',null,'ability-source-links');
        for(const idx of row.sources){
          const [label,paper,benchmark,sourceUrl]=sources[idx],a=element('a',label);
          a.href=sourceUrl && /^https:\/\/arxiv\.org\//.test(sourceUrl) ? sourceUrl : 'benchmark/?'+new URLSearchParams({paper_id:paper,benchmark_id:benchmark});links.append(a);
        }
        cell.append(element('strong',txt('计分来源','Scoring sources')),links);
      };
    });
    if (rows.length) content.append(table);
    dialog.append(head,content);
    trigger.setAttribute('aria-expanded','true');dialog.showModal();document.body.classList.add('ability-board-modal-open');
    close.focus({preventScroll:true});animate(true);
  }
  async function load() {
    grid.replaceChildren();
    try {
      const response=await fetch(new URL('/snapshot/'+window.snapshotElo.snapshot_id+'/capability-rankings.json?scale=elo-v1&revision='+encodeURIComponent(window.snapshotElo.scoring_revision||'legacy'),location.origin));
      if (!response.ok) throw Error(response.status);
      const data=await response.json();
      const main=window.snapshotElo;
      if (data.method !== 'main-batch-elo' || data.score_method !== 'common-basket-centered-elo-v1' || data.snapshot!==main?.snapshot_id || data.scoring_revision!==main.scoring_revision || data.outcome_method!==main.outcome_method) throw Error('snapshot');
      const basket=main.basket;
      if (!basket?.panel_sha256 || basket.status!=='READY') throw Error('basket');
      for (const category of ['Science','Coding','General','Agent']) {
        const other=data.status[category]?.basket;
        if (!other || !(other.status==='READY' || (other.status==='INSUFFICIENT_REFERENCE_PAPERS' && data.boards[category]?.length===0)) || other.panel_sha256!==basket.panel_sha256 || other.baseline!==basket.baseline || JSON.stringify(other.references)!==JSON.stringify(basket.references)) throw Error('basket');
      }
      for(const category of ['Science','Coding','General','Agent']){
        const rows=data.boards[category].filter(r=>r.papers >= (data.display_min_papers ?? data.status[category].min_papers ?? 5) && Number.isFinite(r.score)),card=element('button',null,'ability-board-card');card.type='button';
        card.setAttribute('aria-haspopup','dialog');card.setAttribute('aria-expanded','false');
        const head=element('span',null,'ability-card-heading');
        const arrow=element('span','↗','ability-card-arrow');arrow.setAttribute('aria-hidden','true');head.append(element('strong',category),arrow);
        card.append(head);
        const status = data.status[category];
        const preview=element('span',null,'ability-card-preview');card.append(preview);
        if (status.basket.status==='INSUFFICIENT_REFERENCE_PAPERS') preview.append(element('span',txt('参照模型来源不足，暂缓发布','Reference evidence below threshold'),'ability-card-empty'));
        else if (!rows.length) preview.append(element('span',txt('暂无符合计分条件的模型','No models meet the ranking criteria'),'ability-card-empty'));
        for(const [i,row] of rows.slice(0,3).entries()){
          const line=element('span',null,'ability-card-row');
          const rating=element('b',row.score.toFixed(1));
          const name=element('span',modelName(row));
          name.append(element('small', en ? row.papers+' source papers' : row.papers+' 篇来源论文','ability-card-papers'));
          line.append(element('small',String(i+1).padStart(2,'0')),name,rating);preview.append(line);
        }
        card.append(element('span',rows.length ? (en?'View all '+rows.length+' entries':'查看全部 '+rows.length+' 项') : txt('查看计分条件','View eligibility criteria'),'ability-card-more'));
        card.onclick=()=>showBoard(category,rows,data.benchmarks,status,card);grid.append(card);
      }
    } catch {
      const retry=element('button',txt('分榜加载失败，重新加载','Retry loading rankings'));retry.onclick=load;grid.append(retry);
    }
  }
  load();
})();
