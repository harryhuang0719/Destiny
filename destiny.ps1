$ErrorActionPreference = "Stop"
$DestinyRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $DestinyRoot ".venv\Scripts\python.exe"
$EntryPoint = Join-Path $DestinyRoot "scripts\destiny_analyzer.py"

if (Test-Path $VenvPython) {
    & $VenvPython $EntryPoint @args
} else {
    & py -3 $EntryPoint @args
}
exit $LASTEXITCODE
