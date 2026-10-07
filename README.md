# 错题记录 CuotiRecord

当前版本 **v0.3.2**。面向高中学生，记录做题时间、原题、作答、考点与复习结果。

入口提供语文、数学、英语、物理、政治、历史、地理七科。各科支持资料录入、题目核对与历史记录；目前仅英语开放 AI 错题分析、22 个基础考点及原题复习。化学、生物已移除。

## Windows 本地运行

需要 Python 3.12+、Node.js 22+、npm 和已安装的 Chrome 或 Edge。PowerShell 在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
powershell -ExecutionPolicy Bypass -File scripts/start.ps1
```

打开 http://127.0.0.1:8765 。首次建立学习档案后选择学科。在设置页面填写阿里云百炼 API Key；未配置密钥时可用明确标记的固定示例体验流程。

默认图片识别模型 `qwen3-vl-plus`，分析模型 `qwen3.8-max`，可在设置修改。模型可用性取决于账户权限。调用真实 AI 会产生费用，需要人工核对后确认分析。

图片、PDF、DOCX 可录入；DOCX 以内容重排生成预览，不保证与 Word 原始分页一致。数据默认保存到 `%LOCALAPPDATA%/CuotiRecord/data`，API Key 使用 Windows DPAPI 加密，绑定当前 Windows 用户。数据库、密钥和学生上传资料均不进入 Git 仓库。

## 自测

```powershell
& "$env:LOCALAPPDATA\CuotiRecord\runtime\Scripts\python.exe" -m pytest -q
```

浏览器自测需另开终端启动无密钥、全新隔离测试实例：

```powershell
$env:CUOTI_DATA_DIR="$env:LOCALAPPDATA\CuotiRecord\qa-browser"
& "$env:LOCALAPPDATA\CuotiRecord\runtime\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8771
```

然后在仓库根目录的另一个终端执行：

```powershell
npm ci
$env:CUOTI_QA_URL='http://127.0.0.1:8771'
npm run test:browser
```

脚本拒绝测试生产端口 8765、已配置密钥或非 qa-* 数据目录。测试使用合成题目，不调用付费 AI。真实模型测试另见 `scripts/real-ai-smoke.py --help`，必须显式选择付费调用。

## 文档

- [当前 PRD 与逐页原型](docs/versions/v0.3.2/PRD.md)
- [当前技术文档](docs/versions/v0.3.2/TECHNICAL.md)
- [自测验收报告](docs/versions/v0.3.2/ACCEPTANCE.md)
- [版本变更](docs/versions/v0.3.2/CHANGELOG.md)
- [功能清单](docs/FEATURES.md)
- [历史版本](docs/README.md)

公开页面截图仅含合成验收资料。软件为单机单学生版本，不提供账号系统、云同步或自动生成新题。
