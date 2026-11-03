# End-to-end check on the real local models (needs Ollama running and the models pulled).
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$env:STUDIO_HOME = $Root
& (Join-Path $Root '.venv\Scripts\studio.exe') doctor
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& (Join-Path $Root '.venv\Scripts\studio.exe') smoke @args
exit $LASTEXITCODE
