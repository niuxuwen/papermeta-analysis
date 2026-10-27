# 论文 Meta 分析 · GitHub Pages 访问者版

此目录只包含可公开的网页与 v111 真实数据快照，不包含服务端程序、管理入口、队列或 API 密钥。
数据截至北京时间 2026-10-27 19:42，30,594 条原始成绩、132 个默认设置下的模型综合分。

## 发布

1. 将本目录内容提交到指定 GitHub 仓库的 main 分支（保留隐藏的 .github 目录）。
2. 在仓库 Settings → Pages → Build and deployment 将 Source 设为 GitHub Actions。
3. 在 Actions 中运行 Publish visitor website，等待部署成功。
4. 使用 Pages 设置页或成功任务返回的真实网址访问。仅浏览网站不需要 GitHub 账号。

支持个人站点根目录和项目站点 /仓库名/ 子路径；Benchmark 独立详情使用 benchmark/ 目录。
网页展示固定快照，任务画像分析与重新评分仍需要后端连接，页面保留明确说明。
发布仓库：https://github.com/niuxuwen/papermeta-analysis。GitHub Pages 地址：https://niuxuwen.github.io/papermeta-analysis/。

## 验证

node --test test-pages.cjs

该检查读取整份真实快照，验证根目录及项目子路径下的数据完整性、原分数、日期和详情身份。
第三方图标许可见 site/vendor-logos/。
