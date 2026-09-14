param([string]$Python = "python")

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$src = Join-Path $repo "src"
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$src;$env:PYTHONPATH" } else { $src }
& $Python -m tbhastrarium @args
exit $LASTEXITCODE
