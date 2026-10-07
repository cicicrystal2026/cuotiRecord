# v0.3.2 技术文档

## 架构与数据

FastAPI 提供本机 HTTP API，原生 JavaScript/CSS 单页前端，SQLite 持久化。默认绑定 127.0.0.1:8765。资料、分页、题目、分析、考点关系、后台任务、复习会话与尝试分表保存；迁移版本截至 4，新增发行版不删除既有数据。

`app/main.py`：接口、校验与本机请求约束；`storage.py`：数据与迁移；`documents.py`：图片/PDF/DOCX 转换；`ai.py`：百炼兼容 API、输出规范化与证据约束；`domain.py`：分析有效性、考点统计与复习规则；`config.py`：本地 DPAPI 密钥；`subjects.py` 与 `knowledge.py`：学科与英语考点；`web/`：页面。

图片使用 Pillow；PDF 使用 PyMuPDF；DOCX 用 lxml 解析文字、OMML 公式与内嵌图，经 Playwright 重排成 PDF。重排预览保留内容，不保证 Word 原版排版。Node 依赖依次查找显式 CUOTI_NODE_MODULES、本机安装、项目 node_modules 与可用运行时。浏览器支持 Chrome/Edge 或已安装的 Playwright Chromium。

## AI 与版本

默认 OCR qwen3-vl-plus，分析 qwen3.8-max。HTTP 请求有超时，任务记录失败原因、模型/提示版本/知识库版本和用量。识别结果区分页面文本、学科、内容类型与习题；讲义无题不是识别失败。缺失作答、无法定位证据和考点超出库会阻止自动确认。英语知识库 english-core-1，22 个节点。

本版修复分析确认接口：非英语资料或旧知识库版本直接拒绝确认，保留原记录待重新分析。前端 GET 请求记录发起时路由序号，页面切换后忽略过期结果，避免覆盖新页面。

## 运行与安全边界

单机单用户。数据库与上传资料默认位于 LOCALAPPDATA/CuotiRecord/data，可用 CUOTI_DATA_DIR 指定隔离目录。密钥 DPAPI 仅当前 Windows 用户解密，不通过接口回显。仅允许本机请求与指定客户端头；HTML 动态文本转义。没有公网部署认证，不能直接作为公网多用户服务。

Python 依赖锁定 requirements.lock.txt；Playwright 1.58.2 锁定 package-lock.json。Windows 安装/启动/停止见 README。启动脚本使用隐藏窗口。数据备份需停止服务后复制完整数据目录；DPAPI 密钥跨用户/机器需重新配置。

## 自测与交付

pytest 在临时数据目录中使用构造资料及模拟 AI，不消耗模型费用。浏览器脚本要求 qa-* 隔离目录及无密钥，拒绝端口8765，覆盖实际文件转换、路由、复习状态与手机布局。历史脚本名称作为当前测试入口的兼容包装。

真实模型测试需运行 real-ai-smoke.py --allow-paid，只使用构造英语图片和无作答用例，报告写入被忽略的 test-results。本次发行未再次调用付费模型，历史真实模型记录仅供当时结果参考。

Git 忽略运行时数据、密钥、日志、依赖和旧版本地截图。公开原型重新生成于无密钥隔离实例。没有云服务、缓存凭据或孩子原始文件随代码发布。
