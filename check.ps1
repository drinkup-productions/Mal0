@'
@echo off
copy /y malo\core\log.py broken_proof.txt >nul
exit /b 1
'@ | Set-Content -Encoding ascii probe.cmd