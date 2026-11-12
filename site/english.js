'use strict';
(() => {
  const catalog = window.paperMateEnglish;
  Object.assign(catalog.labels,{
    '测试样本 n':'Test sample n', '综合评分 · Elo':'Model ratings · Elo',
    '加权 Bradley–Terry 拟合 · Elo 分数':'Weighted Bradley–Terry ratings on the Elo scale',
    '同条件比较采用加权 Bradley–Terry 拟合，直接展示 Elo 分数。Elo = 1000 + 400 × θ / ln(10)。':'Weighted Bradley–Terry fit on matched comparisons. Elo = 1000 + 400 × θ / ln(10).',

    '综合评分已加载，详细评测数据暂未加载。可点击“重新载入”重试。':'Model ratings are available. Reload to retry loading the detailed evidence.',
    '手动设置任务能力与权重后即可评分。任务评分在当前浏览器内完成。':'Set the capabilities and weights to score models in your browser.',
    '汇总该模型的参测项目、原始成绩与评分依据。':'Explore this model’s benchmarks, reported scores and scoring methods.',
    '评分说明':'Scoring methodology', '评测成绩':'Benchmark results',
    '查看共同测试':'Compare shared benchmarks', '可比评测':'Comparable benchmarks',
    '可比评测组数':'Comparable test groups', '全选当前结果':'Select all results',
    '清空选择':'Clear selection', '按当前排序选前':'Select the first',
    '按当前排序和筛选范围替换当前选择':'Select models using the current filters and sort order',
    '依据论文报告的原始成绩比较模型表现。':'Compare models using results reported in research papers.',
    '成绩摘录自公开论文，可查阅原始数值与来源。':'Scores are drawn from published papers. You can consult the original values and sources.',
    '模型榜单':'Model rankings',
    '筛选比较模型':'Filter models',
    '对固定参考组的平均预期得分（0–100）':'Expected score against the fixed reference panel (0–100)',
    '参考分 · 0–100':'Reference score · 0–100',
    '固定参考组暂不完整，本次暂不发布换算分数。':'The reference panel is incomplete; normalized scores are unavailable.',
    "代码理解与执行推理": "Code comprehension and execution reasoning",
    "根据源码推断程序行为、变量状态或跨文件依赖。": "Inferring program behavior, variable state, or cross-file dependencies from source code.",
    "软件测试与漏洞发现": "Software testing and vulnerability discovery",
    "评估测试用例生成、回归检测、漏洞发现或定位。": "Generating tests, detecting regressions, or finding and localizing vulnerabilities.",
    "代码质量与可维护性": "Code quality and maintainability",
    "评估代码规范、设计质量和长期维护条件。": "Evaluating coding standards, design quality, and maintainability.",
    "算法与性能优化": "Algorithm and performance optimization",
    "评估模型对算法或实现的改进，包括运行效率和固定预算下的任务表现。": "Improving algorithms or implementations, as measured by runtime efficiency or performance under a fixed budget.",
    "编程能力标注依据": "Source evidence for the coding label",
    "能力标签描述本项评测的任务范围。": "These capabilities describe the tasks covered by this benchmark.",
    '代码调试与修复':'Debugging and repair',
    '评测分类与能力':'Category and capabilities',
    '评测一级标签':'Benchmark categories',
    '参测项目的能力标签':'Capabilities covered by reported benchmarks',
    'Elo 综合评分':'Elo model ratings','Elo 参考分':'Elo reference score', '正在加载模型…':'Loading models…','来源论文':'Source papers',
    '同条件比较采用加权 Bradley–Terry 拟合。参考分为对固定参考组的平均预期得分，平局计半分；参考名单与权重不随展示门槛变化。':'Ratings use a weighted Bradley–Terry fit to matched comparisons. Reference scores are expected match scores against a fixed panel, with ties counting as one half. Panel membership and weights do not depend on display thresholds.'
  });
  const hasChinese = /[\u3400-\u9fff]/;
  const chinesePhrase = /[\u3400-\u9fff]+(?:[，、；：][\u3400-\u9fff]+)*/g;
  const protectedNames = new Set(catalog.names);
  const countLabel = (value, singular) => value + ' ' + singular + (Number(value.replaceAll(',', '')) === 1 ? '' : 's');
  const rules = [
    [/^([\d,]+) 条来源 · ([\d,]+) 种设置 · ([\d,]+) 条可比来源$/, (_, records, settings, comparable) =>
      [countLabel(records, 'source record'), countLabel(settings, 'setting'), countLabel(comparable, 'comparable record')].join(' · ')],
    [/^([\d,]+) 张来源表$/, (_, n) => countLabel(n, 'source table')],
    [/^(.+) 占优$/, '$1 ahead'],
    [/^另有 (\d+) 组增益、诊断或其他指标，(\d+) 组未纳入综合评分的条件，(\d+) 组重复单元；保留在原始记录中。$/, 'Additional source records include gains, diagnostics or other metrics ($1), conditions excluded from the composite score ($2), and duplicate entries ($3).'],
    [/^(\d+) 个共同 Benchmark · (\d+) 个同组来源；当前雷达选择 (\d+) 个 Benchmark。$/, '$1 shared benchmarks · $2 matched results · $3 benchmarks selected'],
    [/^(\d+) 篇来源论文 · (\d+) 项 Benchmark · (\d+) 组同条件指标$/, '$1 source papers · $2 benchmarks · $3 matched metric groups'],
    [/^(.+?) · (正向指标|负向指标)$/, (_, metric, direction) => metric + ' · ' + catalog.labels[direction]],
    [/^查看 (.+?) 的模型详情，综合分 ([\d.]+)$/, 'View $1, composite score $2'],
    [/^查看 (.+?) 的评测详情$/, 'View benchmark details for $1'],
    [/^查看 (.+?) 的成绩与来源详情$/, 'View results and sources for $1'],
    [/^查看 (.+?)参与的评测项目$/, 'View benchmarks for $1'],
    [/^(\d+) 个型号已有核验来源；汇总本 Benchmark 的全部指标与实验设置。$/, 'Verified results cover $1 models across all metrics and experimental settings.'],
    [/^(\d+) 个模型已有综合评分 · ([\d,]+) 项评测。.*$/, '$1 models with composite scores across $2 benchmarks.'],
    [/^综合榜 ([\d,]+) 个可计分模型 · 已显示 (\d+) 个 · 其余 ([\d,]+) 个保留单项成绩$/, 'Showing $2 of $1 scored models. Individual results are available for $3 additional models.'],
    [/^显示 (\d+) \/ ([\d,]+) 项匹配 · 当前可查 ([\d,]+) 个已归并 Benchmark、([\d,]+) 个版本\/子集 · ([\d,]+) 条身份待核来源$/, 'Showing $1 of $2 matches · $3 benchmarks · $4 versions or subsets · $5 source records pending identification'],
    [/^论文近(\d+)天 · Benchmark近(\d+)个月$/, 'Papers: past $1 days · Benchmarks: past $2 months'],
    [/^前 (\d+) 个$/, 'Top $1'], [/^(\d+) 项 Benchmark$/, '$1 benchmarks'],
    [/^(\d+) 个模型 · ([\d,]+) 条来源成绩$/, '$1 models · $2 reported results'],
    [/^([\d,]+) 项评测$/, '$1 benchmarks'],
    [/^数据截至\s*(.+)$/, 'Data as of $1'], [/^证据更新时间\s*(.+)$/, 'Source data updated $1'],
    [/^继续显示 · 还有 (\d+) 个 Benchmark$/, 'Show more · $1 benchmarks remaining']
  ];
  function translate(text) {
    if (!text || !hasChinese.test(text)) return text;
    const value = text.trim();
    if (protectedNames.has(value)) return text;
    let result = catalog.labels[value];
    if (!result) {
      for (const [pattern, replacement] of rules) {
        if (pattern.test(value)) { result = value.replace(pattern, replacement); break; }
      }
    }
    if (!result) {
      result = value.replace(chinesePhrase, phrase => {
        if (protectedNames.has(phrase)) return phrase;
        const match = catalog.labels[phrase];
        if (match) return ' ' + match + ' ';
        return phrase.replace(/[\u3400-\u9fff]+/g, part => catalog.labels[part] ? ' ' + catalog.labels[part] + ' ' : part);
      }).replace(/。/g,'. ').replace(/[：]/g,': ').replace(/[，、]/g,', ').replace(/；/g,'; ')
        .replace(/（/g,' (').replace(/）/g,') ').replace(/\s+([,.:;)])/g,'$1')
        .replace(/\s{2,}/g,' ').trim();
    }
    result = result.replace(/benchmarks Benchmark/g,'benchmarks').replace(/Other \/ Provider unconfirmed/g,'Provider unconfirmed').replace(/：/g,': ');
    return text.replace(value, () => result);
  }
  const attributes = ['title','aria-label','placeholder','alt','aria-description','label','data-label'];
  const ignore = 'script,style,textarea,code,pre,blockquote,[data-source-quote],[lang="zh-Hans"]';
  function localizeElement(element) {
    if (element.matches('option:not([value])')) element.value = element.textContent;
    for (const name of attributes) {
      const raw = element.getAttribute(name);
      const label = translate(raw);
      if (label !== raw) element.setAttribute(name,label);
    }
  }
  function localize(node) {
    if (!node.isConnected || node.parentElement?.closest(ignore)) return;
    if (node.nodeType === Node.TEXT_NODE) {
      const next = translate(node.data);
      if (next !== node.data) node.data = next;
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE || node.matches(ignore)) return;
    localizeElement(node);
    for (const child of node.childNodes) localize(child);
  }
  localize(document.documentElement);
  new MutationObserver(records => {
    const changed = new Set();
    for (const record of records) {
      if (record.type === 'childList') record.addedNodes.forEach(node => changed.add(node));
      else if (record.type === 'attributes') localizeElement(record.target);
      else changed.add(record.target);
    }
    for (const node of changed) if (!changed.has(node.parentNode)) localize(node);
  }).observe(document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:attributes});
})();
