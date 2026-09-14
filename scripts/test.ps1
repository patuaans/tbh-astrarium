param([string]$Python = "python")

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$src = Join-Path $repo "src"
$env:PYTHONPATH = if ($env:PYTHONPATH) { "$src;$env:PYTHONPATH" } else { $src }

$pythonTests = @(
    "test_storage.py",
    "test_stash_controller.py",
    "test_cube_controller.py",
    "test_stash_quick_access.py",
    "test_cube_ui.py"
)
$nodeTests = @(
    "test_stash_queue.cjs",
    "test_stash_agent.cjs",
    "test_cube_policy.cjs",
    "test_cube_agent.cjs"
)

foreach ($test in $pythonTests) {
    & $Python (Join-Path $repo "tests\$test")
    if ($LASTEXITCODE -ne 0) { throw "$test failed" }
}
foreach ($test in $nodeTests) {
    & node (Join-Path $repo "tests\$test")
    if ($LASTEXITCODE -ne 0) { throw "$test failed" }
}

Write-Host "All offline tests passed."
