# 论文 Meta 分析 · GitHub Pages 访问者版

公开网页发布 v120 评分快照（综合评分 v15、任务参考 v8）；后端源码独立保存在 backend/，不会包含在 Pages 发布目录中。网页不包含管理入口、队列或 API 密钥。
数据截至北京时间 2026-10-27 19:42，30,594 条原始成绩、132 个默认设置下的模型综合分。

## 发布

1. 将本目录内容提交到指定 GitHub 仓库的 main 分支（保留隐藏的 .github 目录）。
2. 在仓库 Settings → Pages → Build and deployment 将 Source 设为 GitHub Actions。
3. 在 Actions 中运行 Publish visitor website，等待部署成功。
4. 使用 Pages 设置页或成功任务返回的真实网址访问。仅浏览网站不需要 GitHub 账号。

支持个人站点根目录和项目站点 /仓库名/ 子路径；Benchmark 独立详情使用 benchmark/ 目录。
网页展示后台已核验的最新一批公开数据。服务器每五分钟检查一次，发现新成绩、标签或评分结果后自动发布；网页每分钟检查新版本，并在完整性校验通过后切换。构建、发布及网络缓存带来额外延迟，不保证秒级更新。任务分析与评分通过独立的任务后端提供，连接配置与运行方式见 `backend/README.md`。
发布仓库：https://github.com/niuxuwen/papermeta-analysis。GitHub Pages 地址：https://niuxuwen.github.io/papermeta-analysis/。

## 验证

node --test test-pages.cjs test-task-connection.cjs test-candidate-recovery.cjs test-task-v8.cjs test-source-scoring-v15.cjs test-task-loading.cjs test-common-evidence.cjs

该检查读取整份真实快照，验证根目录及项目子路径下的数据完整性、原分数、日期和详情身份。
第三方图标许可见 site/vendor-logos/。

## 首页加载

首页的六个模型与四项近期评测在构建时从同一份真实快照写入 HTML，首次展示不请求完整成绩归档。
完整原始归档独立保留用于数据核验。共同测试及单项来源对比读取约 1.79 MB 的原始比较记录，分成 7 个最大 256 KiB 的分片；每片校验 SHA-256，连接中断仅重试该片，完整读取后再发布比较结果。
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

## 自动发布

`backend/publish_live.py --project /path/to/benchmark-radar` 从已运行服务的只读 workspace 获取当前核验结果，去除进程信息并扫描凭据。只把公开数据写入专用 `live-data` 分支；该分支由发布器管理，每次以租约更新独立的最新一版，不积累全部快照历史，不改写 main。服务器专用部署私钥只保存在服务器 `deployment/publication/`，不进入 Git、网站或 Actions。

GitHub Actions 从 main 读取网页代码，从 live-data 读取公开数据，执行 `backend/build_live.py`、`build-home.cjs` 和 `validate-live.cjs`。榜单、目录统计、模型原始来源与服务器公开结果逐项核对后才部署；数据读取、版本核验或构建失败时保留上次成功网站。此流程不启动新采集任务、不调用模型接口，也不重算综合评分。服务器任务规则投影只用于构建同版本的静态数据。

浏览器先验证新数据再替换整个版本；阅读详情弹窗或编辑任务时暂缓切换。网络失败、内容损坏或较旧 CDN 响应不会清空已加载数据。新发布数据可能因为部署或缓存延迟稍后才可见。

更新协议检查：`node --test test-publication-updates.cjs`；发布边界检查：`python backend/test_live_publication.py`。冻结的真实样本回归仍使用现有测试，自动发布校验使用当批真实数据，不硬编码旧型号数量或成绩。
