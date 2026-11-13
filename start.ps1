<#
  Starts MalO. Ensures the Letta app server, the broker token, and the app.
  -NoApp      services only, no window
  -Headless   app in server mode, no window, no tray
#>
[CmdletBinding()]
param(
    [switch]$NoApp,
    [switch]$Headless,
    [int]$Port = 4500,
    [int]$BrokerPort = 8766
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Say($msg, $colour = "Gray") {
    Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg) -ForegroundColor $colour
}

function Die($msg) {
    Say $msg "Red"
    exit 1
}

function Test-Port($p) {
    $null -ne (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)
}

function Get-Cfg {
    $p = Join-Path $env:LOCALAPPDATA "MalOAvatar\config.json"
    if (-not (Test-Path $p)) { return @{} }
    try { return (Get-Content $p -Raw | ConvertFrom-Json) } catch { return @{} }
}

# ---- preflight -----------------------------------------------------------
Say "preflight"
foreach ($exe in @("node", "letta", "python")) {
    $hit = Get-Command $exe -All -ErrorAction SilentlyContinue |
           Where-Object { $_.Source -match '\.(exe|cmd|bat|ps1)$' }
    if (-not $hit) { Die "$exe not on PATH" }
}
Say ("node {0}, python {1}" -f (node -v), (python -V)) "DarkGray"

# ---- letta server --------------------------------------------------------
function Start-Detached($target, $arguments, $out, $err) {
    $all = @(Get-Command $target -All -ErrorAction Stop | Select-Object -Expand Source)
    $exe  = $all | Where-Object { $_ -match '\.exe$' } | Select-Object -First 1
    $shim = $all | Where-Object { $_ -match '\.(cmd|bat)$' } | Select-Object -First 1
    $ps1  = $all | Where-Object { $_ -match '\.ps1$' } | Select-Object -First 1
    if ($exe) {
        Start-Process -FilePath $exe -ArgumentList $arguments `
            -WindowStyle Minimized -RedirectStandardOutput $out -RedirectStandardError $err
    } elseif ($shim) {
        Start-Process -FilePath "cmd.exe" `
            -ArgumentList (@("/c", "`"$shim`"") + $arguments) `
            -WindowStyle Minimized -RedirectStandardOutput $out -RedirectStandardError $err
    } elseif ($ps1) {
        Start-Process -FilePath "powershell.exe" `
            -ArgumentList (@("-NoProfile", "-File", "`"$ps1`"") + $arguments) `
            -WindowStyle Minimized -RedirectStandardOutput $out -RedirectStandardError $err
    } else {
        throw "$target has no launchable shim"
    }
}

if (Test-Port $Port) {
    Say "letta server already on $Port"
} else {
    Say "starting letta server on $Port"
    $log = Join-Path $env:TEMP "malo-letta-server.log"
    Start-Detached "letta" @("server", "--backend", "local",
                             "--listen", "ws://127.0.0.1:$Port") $log "$log.err"
    $deadline = (Get-Date).AddSeconds(40)
    while (-not (Test-Port $Port)) {
        if ((Get-Date) -gt $deadline) {
            Say "server did not bind $Port - see $log" "Red"
            Get-Content "$log.err" -Tail 15 -ErrorAction SilentlyContinue
            exit 1
        }
        Start-Sleep -Milliseconds 500
    }
    Say "server up"
}

# ---- broker token --------------------------------------------------------
$cfg = Get-Cfg
if (-not $cfg.broker_token) {
    Say "no broker token - pairing this machine"
    python -m malo --pair desktop
    $cfg = Get-Cfg
    if (-not $cfg.broker_token) { Die "pairing did not write a token" }
} else {
    Say "broker token present"
}

if ($cfg.broker_port -and $cfg.broker_port -ne $BrokerPort) {
    Say "config broker_port is $($cfg.broker_port), script uses $BrokerPort" "Yellow"
}

if (Test-Port $BrokerPort) {
    Say "broker already on $BrokerPort" "Yellow"
} else {
    Say "broker will start with the app on $BrokerPort"
}

# ---- app -----------------------------------------------------------------
if ($NoApp) {
    Say "services ready - exiting (-NoApp)"
    exit 0
}

if ($Headless) {
    Say "starting headless"
    python -m malo --broker --server
} else {
    Say "starting app"
    python -m malo --broker
}