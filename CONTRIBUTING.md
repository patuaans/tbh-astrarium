# Contributing

## Development setup

Use Python 3.11 or 3.12 on Windows:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -c constraints-release.txt
.\scripts\test.ps1 -Python .\.venv\Scripts\python.exe
```

All policy and controller tests must pass without attaching to the game. Live
integration tests belong in a private local research workspace and must never
consume, move, or synthesize an item without an explicit test plan.

## Game updates

Do not reuse offsets after the `GameAssembly.dll` hash changes. A supported
build requires:

1. A new profile directory named by the full SHA-256.
2. Static validation of every referenced RVA and field layout.
3. Read-only validation against a running game.
4. Offline policy tests and one controlled integration rehearsal.
5. A new entry in `supported-builds.json` only after those checks pass.

## Repository hygiene

Do not submit binaries or content extracted from Task Bar Hero. This includes
`GameAssembly.dll`, `global-metadata.dat`, IL2CPP dumps, interop DLLs, item
catalogs, save files, screenshots containing account information, and logs from
another user. Add synthetic fixtures when a test needs game-shaped data.
