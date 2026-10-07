param([int]$Port=8765)
$ErrorActionPreference='Stop'
$repoDir=Split-Path -Parent $PSScriptRoot
$runtimeDir=Join-Path $env:LOCALAPPDATA 'CuotiRecord\runtime'
$pythonExe=Join-Path $runtimeDir 'Scripts\python.exe'
if(!(Test-Path -LiteralPath $pythonExe)){throw '请先运行 scripts\setup.ps1'}
$runDir=Join-Path $env:LOCALAPPDATA 'CuotiRecord'
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
try{
  $health=Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
  if($health.version -like '0.*'){Write-Output "已启动：http://127.0.0.1:$Port";exit 0}
  throw '端口被其他服务占用'
}catch{
  if(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue){throw "端口 $Port 已被占用"}
}
$serverProcess=Start-Process -FilePath $pythonExe -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port $Port" -WorkingDirectory $repoDir -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runDir 'server-out.log') -RedirectStandardError (Join-Path $runDir 'server-error.log') -PassThru
$serverProcess.Id | Set-Content -Path (Join-Path $runDir "server-$Port.pid") -Encoding ascii
for($i=0;$i -lt 30;$i++){
  Start-Sleep -Milliseconds 300
  try{Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 1 | Out-Null;Write-Output "本地链接：http://127.0.0.1:$Port";exit 0}catch{}
}
throw "启动失败，请查看 $runDir\server-error.log"
