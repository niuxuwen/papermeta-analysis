# v119 更新

网页使用综合评分 v14、任务参考 v8。修正来源指标语义和推理条件，取消 v13 的分数顺序投影；原始成绩保留。当前结果与验证局限见 SCORING-VALIDATION.md。

服务器代码包：`site/downloads/papermeta-source-audited-scoring-v119-20261028.zip`。

在原服务器正常停止服务并完成检查点保存后，进入原项目目录执行（替换包的上传路径）：

```bash
cd /inspire/hdd/global_user/chaimingxu-240108540141/MAMINGYU/wispaper/benchmark-radar
python /实际上传路径/papermeta-source-audited-scoring-v119-20261028.zip --project . --apply
```

再按原启动命令加 `--resume-service` 恢复。安装检查现有代码基线与目录锁，不强制覆盖不匹配的代码；安装过程不调用模型 API，也不替换数据、配置、密钥或任务队列。安装后重新发布服务快照时评分更新。

回滚使用同一代码包和安装输出的备份路径：

```bash
python /实际上传路径/papermeta-source-audited-scoring-v119-20261028.zip --project . --rollback deployment/backups/本次备份文件.zip
```

GitHub Pages 展示固定快照；任务服务目前使用本机临时 HTTPS 隧道，依赖本机持续运行。本次不代表原集群服务器已经安装更新。
