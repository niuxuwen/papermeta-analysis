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
      `本榜根据本领域相同实验条件下的胜负拟合模型强度，沿用主榜的来源、时间和重复比较权重。每个上榜模型及配置至少有 ${minimum} 篇来源论文。参考分为对本快照该分榜全部上榜模型及配置的平均预测胜率 × 100，每个配置等权，包含与自身的预测平局。参考集合随快照固定，页面筛选不改变分数。各分榜采用各自参考集合，分数用于榜内比较。`,
      `Strength is fitted from matched experiments using the overall board's source, time and repeat-match weights. Each entry needs at least ${minimum} source papers. The 0–100 score is its average predicted win probability against every qualifying entry in this category, with equal weight per configuration and a predicted tie against itself. This reference set is fixed for the snapshot; display filters do not change scores. Scores are for comparisons within each category.`)));
    method.append(element('p',txt(
      '换算公式：分数 = 100 × 平均值[1 / (1 + 10^((参考模型 Elo − 当前模型 Elo) / 400))]。原始 Elo 可点击模型名称查看。',
      'Score = 100 × mean[1 / (1 + 10^((reference Elo − model Elo) / 400))]. Select a model name to view its raw Elo.')));
    method.append(element('p',txt(
      '分榜优先采用来源表中具体指标所测的任务。指标只有通用标签时，结合评测的领域和任务归类。同一评测的不同指标可以进入不同分榜。',
      'Categories use the task measured by each source-table metric. For broadly labelled metrics, the benchmark subject and tasks provide context. Different metrics from one benchmark can enter different rankings.')));
    content.append(method);
    method.append(element('p',txt(
      '论文数量门槛仅控制榜单展示。低于门槛的模型仍作为比较对象参与拟合，其来源成绩保留；隐藏模型不会触发重新拟合。',
      'The paper threshold only controls ranking visibility. Models below it remain comparison opponents in the fit, and their source results are retained. Hiding entries does not refit the model.')));
    if (!rows.length) content.append(element('p', en
      ? `No entry currently meets the display threshold of ${minimum} source papers.`
      : `当前没有达到至少 ${minimum} 篇来源论文展示门槛的模型。`));
    const table=element('table',null,'ability-rank-table'), header=table.createTHead().insertRow(), body=table.createTBody();
    for(const name of [txt('名次','Rank'),txt('模型','Model'),txt('参考分（0–100）','Reference score (0–100)'),txt('来源论文','Papers'),txt('参评评测','Benchmarks')]){
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
        cell.append(element('p',txt('原始 Elo：','Raw Elo: ')+row.elo.toFixed(1)),element('strong',txt('计分来源','Scoring sources')),links);
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
      const response=await fetch(new URL('/snapshot/'+window.snapshotElo.snapshot_id+'/capability-rankings.json?scale=100-v1&revision='+encodeURIComponent(window.snapshotElo.scoring_revision||'legacy'),location.origin));
      if (!response.ok) throw Error(response.status);
      const data=await response.json();
      if (data.method !== 'main-batch-elo' || data.score_method !== 'fixed-category-basket-v1' || data.snapshot!==window.snapshotElo?.snapshot_id) throw Error('snapshot');
      for(const category of ['Science','Coding','General','Agent']){
        const rows=data.boards[category].filter(r=>r.papers >= (data.display_min_papers ?? data.status[category].min_papers ?? 5)),card=element('button',null,'ability-board-card');card.type='button';
        card.setAttribute('aria-haspopup','dialog');card.setAttribute('aria-expanded','false');
        const head=element('span',null,'ability-card-heading');
        const arrow=element('span','↗','ability-card-arrow');arrow.setAttribute('aria-hidden','true');head.append(element('strong',category),arrow);
        card.append(head);
        const status = data.status[category];
        const preview=element('span',null,'ability-card-preview');card.append(preview);
        if (!rows.length) preview.append(element('span',txt('暂无符合计分条件的模型','No models meet the ranking criteria'),'ability-card-empty'));
        for(const [i,row] of rows.slice(0,3).entries()){
          const line=element('span',null,'ability-card-row');
          const rating=element('b',row.score.toFixed(1));rating.append(element('small',' / 100'));
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
