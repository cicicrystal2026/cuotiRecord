# 知错 v0.1.0 技术文档

日期：2026-10-07；实现基线：Python/FastAPI + SQLite + 原生HTML/CSS/JS；运行于Windows本机。

## 1. 架构与目录

浏览器 → 127.0.0.1:8765 FastAPI → SQLite/本地原文件；后台任务线程池执行文件转换及阿里云HTTP请求。前端无构建过程、不加载CDN。HTML页面路由使用hash，API路径/api。

| 路径 | 职责 |
|---|---|
| app/main.py | API、输入校验、本机访问限制、静态文件 |
| app/storage.py | 事务、FK、WAL、结构初始化和启动恢复 |
| app/config.py | DPAPI密钥加密、官方域名校验 |
| app/documents.py | 图片、PDF、DOCX解析与预览 |
| app/ai.py | 阿里云兼容接口、提示词、结构化结果及证据校验 |
| app/jobs.py | 队列状态、逐页识别、逐题分析、重试 |
| app/domain.py | 当前版本、考点统计、复习资格、掌握证据 |
| app/knowledge.py | 固定ID基础考点库 |
| web/ | 页面与交互 |
| scripts/ | 环境准备、后台启动停止、Word渲染、浏览器QA |
| tests/ | 隔离数据库下的自动化测试 |
| docs/versions/v0.1.0/ | PRD、技术文档、验收、变更、截图 |

运行环境与资料独立于WPS仓库：`%LOCALAPPDATA%\CuotiRecord\runtime`、`data`。可用CUOTI_DATA_DIR指定测试数据库目录；测试使用隔离目录，不污染孩子档案。

## 2. 数据模型与版本

profile单例 → sources → files/pages/questions；questions → question_versions、analyses → analysis_changes；sessions → items → attempts。

主键UUID；时间UTC ISO保存、上海时区展示；学习日期单独保存为YYYY-MM-DD。SQLite启用外键及WAL、15秒busy timeout。初始迁移版本1，旧表保留，启动不会清空数据；新增字段应添加后续迁移，不修改已有用户数据的含义。

题目实质字段变化版本+1；分析带question_version、model、prompt_version、knowledge_version与原始proposal；用户修改写analysis_changes。只有当前版本已确认分析进入资格判断；删除单题清除版本、分析、结果并清空计划快照，删除资料级联后删除限定资料目录。

本版未做独立学期实体：profile是唯一当前档案的显示设置，资料集合不随日期自动隔离。多学期需要新增semester实体和显式迁移，禁止按编辑后的档案日期静默搬迁。

## 3. 文件管道

图片：Pillow校正EXIF方向，RGB JPEG预览，最大2200边，原件保留，40M像素上限。PDF：PyMuPDF按原页渲染，最长边1800，文字提取作为识别补充；扫描PDF仍可逐页图文识别。加密/空文件/超20页有提示。

DOCX：zip/lxml读取段落、表格、嵌入图片、常用OMML公式转MathML → 本地HTML → Playwright启动已安装Chrome/Edge打印PDF → PyMuPDF预览。禁用外部资源，不执行文档脚本，XML禁止外部实体，解压内容总量上限150MB。此方案是内容重排，不是Word原版排版引擎；常用分式、上下标、根式已支持，复杂公式/浮动图/页眉页脚/批注可能不保真，页面明确提示核对或转PDF。

可用CUOTI_NODE指定Node，CUOTI_NODE_MODULES指定模块目录，CUOTI_BROWSER指定浏览器。当前电脑使用已有运行时中的Playwright；setup.ps1为独立迁移安装固定版本。

## 4. 阿里云配置与调用

默认视觉识别模型qwen3-vl-plus，分析模型qwen3.8-max；模型ID均可修改，不自动切换供应商。默认兼容接口 `https://dashscope.aliyuncs.com/compatible-mode/v1`。根据阿里云账户地域/工作空间调整官方端点与模型权限，以阿里云控制台为准。

Key从DASHSCOPE_API_KEY优先读取，其次是设置页保存的Windows DPAPI密文；配置存资料目录settings.json，API仅回传configured标记，不返回Key或密文。DPAPI绑定当前Windows账户，迁移后应重新输入Key。

POST /chat/completions，Bearer授权，stream=false；分析enable_thinking=true，识别false；最终输出最多6000token，连接15秒、整体120秒。解析最终content中的JSON，校验字符串、库内ID、错因类型及连续作答证据。视觉模型跨版本的原生JSON模式不强制启用，采用提示词要求JSON并严格解析。没有Key/异常返回不替换为演示答案。

提示词math-evidence-1；知识库math-core-1。原页和已核对文本发送模型；文档文字为资料，不当作指令。缺失/歧义/库外ID/伪证据强制待确认。用户逐题核对后确认。首版只显示普通数学符号，不加载LaTeX渲染器；复杂图形题先补全可复习文字条件。

官方依据：[视觉推理说明](https://help.aliyun.com/zh/model-studio/visual-reasoning)。本账户两个模型连接和基础构造题真实调用已通过；记录过一次120秒超时。复杂题模型质量仍待实际样本验收，模拟测试不能证明解题正确率。

## 5. API分组

| 接口 | 操作 |
|---|---|
| GET health/bootstrap/dashboard | 健康、档案/库/模型状态、首页 |
| PUT profile；GET/PUT config；POST config/test | 档案、密钥与模型配置、文本连接验证 |
| GET/POST sources；GET/PUT/DELETE sources/:id | 资料列表、multipart录入、详情修改删除 |
| POST sources/:id/convert或recognize或analyze | 预览、识别、选题分析；返回task_id |
| GET tasks/:id | queued/running/success/partial/failed |
| POST sources/:id/questions；PUT/GET/DELETE questions/:id | 手动录入、乐观版本核对、详情删除 |
| POST questions/:id/manual-analysis；PUT questions/:id/analysis | 显式人工分析、逐题确认/暂存 |
| POST sources/:id/save | 保存所选题，未确认可作为待确认入档 |
| GET history/knowledge | 交集筛选、考点关联统计 |
| GET review/candidates；POST review/sessions | 推荐原题、幂等创建快照计划 |
| GET review/sessions/:id；POST .../state | 读取、暂停恢复提前结束 |
| POST review/items/:id/reveal或attempt | 服务端提示/答案展开、幂等结果追加 |
| GET pages/:id/image或files/:id/download | 数据目录限定的原页/原文件 |
| POST sample | 用户主动导入明确示例，不作真实模型结果 |

输入错误400、不存在404、版本冲突409；网络与模型错误返回已清理的说明，不回传供应商原错误正文及密钥。

## 6. 状态和并发

任务线程池最大2。任务按资料/类型避免重复活动任务；识别成功页不会重跑；服务重启将未完成任务标为失败可重试。分析写入前重新检查题目版本，防止旧结果覆盖新版本；成功题结果立即持久化。

创建复习计划使用SQLite BEGIN IMMEDIATE后检查活动计划；request_key唯一。attempts.item_id唯一及INSERT OR IGNORE保证重复提交只计一次。答案在items.snapshot服务端保存，session_view未展开时删除answer与check_action字段；提示动作会记录hint_used，服务端拒绝独立正确。

状态只看当前题目版本的尝试；连续独立正确至少两次，上海不同日历日且≥24h才已验证；错误或提示打断连续证据。用户自报不等于机器批改。

## 7. 本地边界与部署

服务只绑定127.0.0.1；Host限制本机，变更请求需X-Cuoti-Client及同源Origin。CSP只允许本机脚本样式和图片/data/blob，无CDN；不允许iframe。配置端点只允许HTTPS的阿里云域名，不跟随重定向；上传名清理、所有删除目标解析后限制在资料子目录。

这不是多用户服务，没有网络账号鉴权，不向局域网公开。原题和作答本地保存，但AI按需传给阿里云。日志只保存服务访问状态，不打印密钥和模型请求正文。

## 8. 启动、测试与维护

见根README启动命令。依赖精确版本见requirements.lock.txt。pytest隔离临时数据库；浏览器QA使用独立8766服务，支持390px手机与1440px桌面。测试报告见ACCEPTANCE。

升级前停止服务并复制完整data目录，保持schema迁移可重跑。密钥在其他Windows账户需要重新输入。源码回滚不代表数据库迁移自动回滚，新增迁移需要明确兼容性方案。

## 9. 首批考点ID

- `sets`：集合 / 集合概念与运算
- `logic`：集合 / 命题与充分必要条件
- `domain`：函数 / 定义域与值域
- `representation`：函数 / 函数表示与图像
- `monotonicity`：函数 / 函数单调性
- `parity`：函数 / 函数奇偶性
- `exponential`：函数 / 指数与对数函数
- `quadratic`：函数 / 二次函数与方程
- `derivative`：函数 / 导数与函数应用
- `inequality`：基础数学 / 不等式
- `trigonometry`：基础数学 / 三角函数
- `sequence`：基础数学 / 数列
- `vectors`：基础数学 / 平面向量
- `geometry`：基础数学 / 解析几何基础
- `probability`：基础数学 / 概率与统计基础
