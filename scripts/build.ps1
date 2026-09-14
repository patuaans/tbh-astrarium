param(
    [string]$Python = "python",
    [switch]$SkipDependencyCheck
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$src = Join-Path $repo "src"
$dist = Join-Path $repo "dist"
$build = Join-Path $repo ".build"
$entry = Join-Path $PSScriptRoot "entrypoint.py"

if (-not $SkipDependencyCheck) {
    & $Python -c "import frida, PyInstaller"
    if ($LASTEXITCODE -ne 0) {
        throw "Missing build dependencies. Run: $Python -m pip install -r requirements-dev.txt"
    }
}

& $Python -m PyInstaller --noconfirm --clean --windowed --onedir `
    --name "TBHAstrarium" `
    --distpath $dist `
    --workpath (Join-Path $build "work") `
    --specpath (Join-Path $build "spec") `
    --paths $src `
    --collect-all frida `
    --runtime-hook (Join-Path $PSScriptRoot "pyi_tk_runtime.py") `
    --add-data "$(Join-Path $src 'tbhastrarium\agents');tbhastrarium\agents" `
    --add-data "$(Join-Path $src 'tbhastrarium\supported-builds.json');tbhastrarium" `
    $entry

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
Write-Host "Built: $dist\TBHAstrarium\TBHAstrarium.exe"
