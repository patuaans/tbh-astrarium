param(
    [string]$GameDir = $env:TBH_GAME_DIR,
    [string]$Configuration = "Release",
    [string]$Dotnet = "dotnet"
)

$ErrorActionPreference = "Stop"
if (-not $GameDir) {
    $candidate = Join-Path ${env:ProgramFiles(x86)} "Steam\steamapps\common\TaskbarHero"
    if (Test-Path -LiteralPath $candidate) { $GameDir = $candidate }
}
if (-not $GameDir -or -not (Test-Path -LiteralPath $GameDir)) {
    throw "Task Bar Hero was not found. Pass -GameDir or set TBH_GAME_DIR."
}

$dotnetCommand = Get-Command $Dotnet -ErrorAction SilentlyContinue
if (-not $dotnetCommand) {
    $candidate = Join-Path $env:ProgramFiles "dotnet\dotnet.exe"
    if (Test-Path -LiteralPath $candidate) { $dotnetCommand = Get-Item -LiteralPath $candidate }
}
if (-not $dotnetCommand) {
    throw ".NET SDK 6 or newer was not found. Install it or pass -Dotnet with the path to dotnet.exe."
}

$repo = Split-Path -Parent $PSScriptRoot
& $dotnetCommand.Source build (Join-Path $repo "companion\TBHAstrarium.Companion.csproj") `
    -c $Configuration -p:TaskBarHeroDir="$GameDir"
if ($LASTEXITCODE -ne 0) { throw "Companion build failed with exit code $LASTEXITCODE" }
