$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Push-Location $repo
try {
    $tracked = @(git ls-files)
    if ($LASTEXITCODE -ne 0 -or -not $tracked.Count) {
        throw "No tracked files were found. Stage the intended release source first."
    }

    $blockedNames = @(
        '*.exe', '*.dll', '*.pdb', '*.zip', '*.reg', '*.es3', '*.db',
        '*.jsonl', '*.dmp', 'dump.cs', 'script.json', 'stringliteral.json',
        'il2cpp.h', 'wiki-items.json', 'tbh_items_min.json', 'catalog.local.json'
    )
    foreach ($path in $tracked) {
        foreach ($pattern in $blockedNames) {
            if ((Split-Path $path -Leaf) -like $pattern) {
                throw "Blocked release artifact is tracked: $path"
            }
        }
        $item = Get-Item -LiteralPath $path
        if ($item.Length -gt 10MB) { throw "Tracked file exceeds 10 MB: $path" }
    }

    $sensitivePatterns = @(
        [regex]::Escape(('C:' + [char]92 + 'Users' + [char]92)),
        '765611[0-9]{11}',
        'ghp_[A-Za-z0-9]+',
        'github_pat_[A-Za-z0-9_]+',
        'sk-[A-Za-z0-9_-]{20,}',
        'BEGIN [A-Z ]+PRIVATE KEY'
    )
    foreach ($pattern in $sensitivePatterns) {
        $matches = @(git grep --cached -n -I -E $pattern -- 2>$null)
        if ($LASTEXITCODE -eq 0 -and $matches.Count) {
            throw "Possible private data matched '$pattern':`n$($matches -join "`n")"
        }
        if ($LASTEXITCODE -notin 0, 1) { throw "git grep failed for pattern: $pattern" }
    }

    git diff --cached --check
    if ($LASTEXITCODE -ne 0) { throw "The staged diff has whitespace errors." }
    Write-Host "Release hygiene check passed for $($tracked.Count) tracked files."
}
finally {
    Pop-Location
}
