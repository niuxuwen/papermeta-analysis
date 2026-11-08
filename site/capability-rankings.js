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
      `本榜根据本领域相同实验条件下的胜负计算 Elo。每个上榜模型及配置在最终比较网络中至少有 ${minimum} 篇来源论文。来源、时间和重复比较沿用主榜权重。本榜平均 Elo 为 1000。四个固定参考模型均入榜时，另列对它们的平均预测胜率。`,
      `Elo uses results from matched experiments in this category. Each entry needs at least ${minimum} source papers in the final comparison network. Source, time and repeat-match weights follow the overall board. Elo averages 1000 within this board. A reference score is available when all four reference models qualify.`)));
    method.append(element('p',txt(
      '分榜优先采用来源表中具体指标所测的任务。指标只有通用标签时，结合评测的领域和任务归类。同一评测的不同指标可以进入不同分榜。',
      'Categories use the task measured by each source-table metric. For broadly labelled metrics, the benchmark subject and tasks provide context. Different metrics from one benchmark can enter different rankings.')));
    content.append(method);
    if (!rows.length) content.append(element('p', en
      ? `No comparison network currently meets the minimum of ${minimum} papers per entry.`
      : `当前没有满足每个模型至少 ${minimum} 篇来源论文的互通比较组。`));
    else if (status.missing.length) content.append(element('p',(en
      ? 'Reference score unavailable. Missing qualifying anchors: ' : '四参考模型胜率暂缺，本榜缺少达标的参考模型：')+status.missing.join('、'),'ability-board-meta'));
    const table=element('table',null,'ability-rank-table'), header=table.createTHead().insertRow(), body=table.createTBody();
    for(const name of [txt('名次','Rank'),txt('模型','Model'),'Elo', ...(status.missing.length ? [] : [txt('参考分','Reference score')]),txt('来源论文','Papers'),txt('参评评测','Benchmarks')]){
      const th=element('th',name);th.scope='col';header.append(th);
    }
    rows.forEach((row,i)=>{
      const tr=body.insertRow();tr.insertCell().textContent=i+1;
      const name=tr.insertCell(), toggle=element('button',modelName(row),'ability-rank-model');toggle.type='button';toggle.setAttribute('aria-expanded','false');name.append(toggle);
      tr.insertCell().textContent=row.elo.toFixed(1);
      if (!status.missing.length) tr.insertCell().textContent=row.score.toFixed(1);
      tr.insertCell().textContent=row.papers;
      tr.insertCell().textContent=row.sources.length;
      toggle.onclick=()=>{
        const open=toggle.getAttribute('aria-expanded')==='true';
        toggle.setAttribute('aria-expanded',String(!open));
        if(open){tr.nextElementSibling.remove();return;}
        const more=body.insertRow(tr.sectionRowIndex+1),cell=more.insertCell();cell.colSpan=header.cells.length;
        const links=element('div',null,'ability-source-links');
        for(const idx of row.sources){
          const [label,paper,benchmark]=sources[idx],a=element('a',label);
          a.href='benchmark/?'+new URLSearchParams({paper_id:paper,benchmark_id:benchmark});links.append(a);
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
      const response=await fetch(new URL('/snapshot/'+window.snapshotElo.snapshot_id+'/capability-rankings.json',location.origin));
      if (!response.ok) throw Error(response.status);
      const data=await response.json();
      if (data.method !== 'main-batch-elo' || data.snapshot!==window.snapshotElo?.snapshot_id) throw Error('snapshot');
      for(const category of ['Science','Coding','General','Agent']){
        const rows=data.boards[category],card=element('button',null,'ability-board-card');card.type='button';
        card.setAttribute('aria-haspopup','dialog');card.setAttribute('aria-expanded','false');
        const head=element('span',null,'ability-card-heading');
        const arrow=element('span','↗','ability-card-arrow');arrow.setAttribute('aria-hidden','true');head.append(element('strong',category),arrow);
        card.append(head);
        const status = data.status[category];
        const preview=element('span',null,'ability-card-preview');card.append(preview);
        if (!rows.length) preview.append(element('span',txt('暂无符合计分条件的模型','No models meet the ranking criteria'),'ability-card-empty'));
        for(const [i,row] of rows.slice(0,3).entries()){
          const line=element('span',null,'ability-card-row');
          const rating=element('b',row.elo.toFixed(0));rating.append(element('small',' Elo'));
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
