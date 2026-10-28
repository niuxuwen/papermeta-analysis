# v120 更新

综合评分 v15，任务参考 v8。共同来源软校准与真实验证结果见 SCORING-VALIDATION.md。此包通过 v108–v119 已发布代码基线安装、幂等重装、回滚和数据保留检查。

服务保存完成并退出后，在原项目目录执行：

```bash
.venv/bin/python /实际上传路径/papermeta-common-source-scoring-v120-20261029.zip --project . --apply
```

随后按原命令加 `--resume-service` 启动。安装器仅更新代码，不替换论文、成绩、队列、配置和密钥，不调用模型接口；基线或目录锁不匹配时停止。

回滚：

```bash
.venv/bin/python 同一更新包 --project . --rollback deployment/backups/本次备份文件.zip
```

安装包：site/downloads/papermeta-common-source-scoring-v120-20261029.zip。
