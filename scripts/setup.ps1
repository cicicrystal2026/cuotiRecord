$ErrorActionPreference='Stop'
$repoDir=Split-Path -Parent $PSScriptRoot
$runtimeDir=Join-Path $env:LOCALAPPDATA 'CuotiRecord\runtime'
if(!(Test-Path -LiteralPath (Join-Path $runtimeDir 'Scripts\python.exe'))){python -m venv $runtimeDir;if($LASTEXITCODE -ne 0){throw '需要Python3.12或更高版本'}}
& (Join-Path $runtimeDir 'Scripts\python.exe') -m pip install -r (Join-Path $repoDir 'requirements.lock.txt')
if($LASTEXITCODE -ne 0){throw 'Python依赖安装失败'}
# DOCX content preview uses Playwright + the installed Chrome or Edge.
$playwrightDir=Join-Path $env:LOCALAPPDATA 'CuotiRecord\node'
if(!(Test-Path -LiteralPath (Join-Path $playwrightDir 'node_modules\playwright'))){npm install --prefix $playwrightDir playwright@1.58.2;if($LASTEXITCODE -ne 0){throw '需要Node.js/npm，用于DOCX预览'}}
Write-Output '环境准备完成。运行 scripts\start.ps1 启动。'
