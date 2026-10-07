param([int]$Port=8765)
$pidFile=Join-Path $env:LOCALAPPDATA "CuotiRecord\server-$Port.pid"
if(!(Test-Path -LiteralPath $pidFile)){Write-Output '没有找到本应用的进程记录';exit}
$serverPid=[int](Get-Content -LiteralPath $pidFile)
$processInfo=Get-CimInstance Win32_Process -Filter "ProcessId=$serverPid"
if($processInfo -and $processInfo.CommandLine -match 'uvicorn app.main:app' -and $processInfo.CommandLine -match "--port $Port"){
  Stop-Process -Id $serverPid
  Remove-Item -LiteralPath $pidFile
  Write-Output '本地服务已停止，资料保留。'
}else{Write-Output '原服务已退出；未停止其他进程。'}
