# 任务后端

网页成绩继续使用公开快照。此进程只提供任务能力分析、任务评分和临时结果查询；使用同一份快照与现有 Radar 的评分代码，不启动论文提取。

任务参考 v5：分项分别估计，缺测不再补 50 分；按已测能力权重汇总，并按相同能力覆盖及来源比较网络分组。编程任务使用表格上下文支持的任务成果指标；摘要/压缩损伤、其他领域分项及含义未明确的指标保留原始来源，不混入编程任务分。软件交付类参考显示为“代码任务成果参考”，不能解释为单元测试正确率。其余任务的目录标签仍是 Benchmark 级相关性依据，不声称完成了全部指标级能力归因。参数与结果均未经用户真实工作任务的外部验证。

服务器准备：Python 环境中须能导入已有 `benchmark-radar/recent_benchmarks` 与其依赖。使用环境变量配置 `RADAR_API_KEY`、`RADAR_LLM_URL`、`RADAR_LLM_MODEL`，密钥不要写进仓库或网页配置。

```bash
python backend/task_service.py \
  --radar-root /path/to/benchmark-radar \
  --snapshot /path/to/public-snapshot.json.gz \
  --port 1894
```

通过 HTTPS 网关将任务服务接入公网，然后在 `site/task-backend.json` 填写 `enabled: true` 和 HTTPS `base_url`。前端会核对 `snapshot_id`，数据版本不一致时不提交任务。服务默认允许来源 `https://niuxuwen.github.io`；其他前端来源使用 `--allow-origin` 显式添加。

本机试用入口使用临时隧道，依赖本机进程持续运行，不作为长期部署。正式更新数据时须同时更新网页快照和任务服务。

任务能力分析使用服务端配置的模型，每日默认最多接受 24 次分析执行，重复输入可复用内存结果；任务评分不调用模型。请求体、并发、队列和结果大小均有限制，不开放采集、管理或凭据接口。任务描述与结果不写入文件，异步查询使用随机任务凭据。
