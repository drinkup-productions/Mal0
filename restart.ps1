<#
  Restarts MalO. Asks the running app to shut down gracefully first, so it
  writes its notes, then relaunches.
  -Delay seconds to wait before relaunching.
#>
[CmdletBinding()]
param([int]$Delay = 3)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Say($msg, $colour = "Gray") {
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg) -ForegroundColor $colour
}

$data = if ($env:MALO_DATA) { $env:MALO_DATA } else { Join-Path $env:LOCALAPPDATA "MalOAvatar" }
$flag = Join-Path $data "quit.flag"

function Get-MalO {
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" |
        Where-Object { $_.CommandLine -and $_.CommandLine -match 'malo' }
}

$procs = @(Get-MalO)
if (-not $procs) { Say "no running MalO" "Yellow" }
else {
    Say ("asking {0} process(es) to shut down" -f $procs.Count)
    New-Item -ItemType File -Path $flag -Force | Out-Null

    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $deadline) {
        if (-not @(Get-MalO).Count) { Say "graceful exit" ; break }
        Start-Sleep -Milliseconds 500
    }
    $left = @(Get-MalO)
    if ($left.Count) {
        Say "graceful timeout - forcing" "Yellow"
        foreach ($p in $left) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 2
    }
    Remove-Item $flag -Force -ErrorAction SilentlyContinue
}

Say ("relaunching in {0}s" -f $Delay)
Start-Sleep -Seconds $Delay
Start-Process -FilePath "powershell.exe" `
    -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSScriptRoot\start.ps1`"" `
    -WorkingDirectory $PSScriptRoot
Say "relaunched"