# 论文 Meta 分析 · GitHub Pages 访问者版

公开网页发布 v120 评分快照（综合评分 v15、任务参考 v8）；后端源码独立保存在 backend/，不会包含在 Pages 发布目录中。网页不包含管理入口、队列或 API 密钥。
数据截至北京时间 2026-10-27 19:42，30,594 条原始成绩、132 个默认设置下的模型综合分。

## 发布

1. 将本目录内容提交到指定 GitHub 仓库的 main 分支（保留隐藏的 .github 目录）。
2. 在仓库 Settings → Pages → Build and deployment 将 Source 设为 GitHub Actions。
3. 在 Actions 中运行 Publish visitor website，等待部署成功。
4. 使用 Pages 设置页或成功任务返回的真实网址访问。仅浏览网站不需要 GitHub 账号。

支持个人站点根目录和项目站点 /仓库名/ 子路径；Benchmark 独立详情使用 benchmark/ 目录。
网页展示固定快照。任务分析与评分通过独立的任务后端提供，连接配置与运行方式见 `backend/README.md`。
发布仓库：https://github.com/niuxuwen/papermeta-analysis。GitHub Pages 地址：https://niuxuwen.github.io/papermeta-analysis/。

## 验证

node --test test-pages.cjs test-task-connection.cjs test-candidate-recovery.cjs test-task-v8.cjs test-source-scoring-v15.cjs test-task-loading.cjs test-common-evidence.cjs

该检查读取整份真实快照，验证根目录及项目子路径下的数据完整性、原分数、日期和详情身份。
第三方图标许可见 site/vendor-logos/。

## 首页加载

首页的六个模型与四项近期评测在构建时从同一份真实快照写入 HTML，首次展示不请求完整成绩归档。
打开能力地图或共同测试时按需加载完整快照；后台 Worker 校验 SHA-256、解压并解析，避免阻塞页面交互。
榜单与目录使用约 578 KB 的独立数据，包含全部实验设置的原分数、参考区间、图表数值、访客来源导出、能力标签、目录合并关系及真实成绩统计；浏览榜单、评测目录及能力地图无需先下载约 10.7 MB 的完整来源归档。模型档案按型号单独加载：索引约 91 KB，单个档案最大约 186 KB；GPT-6-Astra 档案约 91 KB，GPT-5.2 约 64 KB。所有轻量数据使用 SHA-256 校验，保留原始成绩及评分结果；通过 `node --test test-ranking-loading.cjs` 比对榜单、来源导出和模型档案与真实快照的一致性。
独立评测详情只读取对应来源文件，使用不到 1 KB 的紧凑索引。完整归档与原始成绩保留。

更新公开快照后运行 `node build-home.cjs`，再运行上述测试。该命令不重新评分，不调用模型 API。
生成的 `performance-validation.json` 记录源快照指纹、首屏数据体积及首页真实结果。

任务页使用同一快照派生的约 250 KB 任务数据，不下载约 10.7 MB 的完整归档。任务画像分析与候选数据加载并行，任务指标规则从同源的校验文件读取，不再经临时隧道重复下载。提交前仍核对后端快照和任务评分版本。完整榜单及模型来源详情按需读取完整数据，原始归档保留。

`build-home.cjs` 会先运行 `build-task-evidence.cjs`，更新带 SHA-256 的任务数据及紧凑索引。七领域的轻量预览与完整快照逐项相同，验证见 `task-loading-validation.json` 与 `test-task-loading.cjs test-common-evidence.cjs`。

## 访问者展示范围

模型详情展示评分、参考区间、评测覆盖、实验设置与原始来源。拟合参数、来源预算、校准诊断和内部处理状态仅用于管理展示，不进入访问者页面或访问者 CSV。
访客来源导出保留论文原值与来源坐标；这项展示调整不修改快照、综合评分或原始成绩。

任务后端当前通过本机临时 HTTPS 隧道连接，依赖本机任务服务与隧道进程运行。没有后台服务时，页面会显示不可用并保留成绩浏览；不会以演示结果代替任务计算。

共同测试结果可在模型表现页面及模型详情中打开。统一厂商规则候选已完成开发与新来源检验，未达到替换现版的依据；线上评分仍为 v15。详见 [实验与发布范围](UNIFORM-EVIDENCE-V121.md)。
