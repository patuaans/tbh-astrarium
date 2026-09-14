# TBH Astrarium

TBH Astrarium is an unofficial Windows companion for **TBH: Task Bar Hero**.
It displays the live drop queue and provides opt-in utilities for chest opening,
stash routing, synthesis, and alchemy.

The project is in alpha. Every native offset-based memory feature is restricted
to an explicitly verified `GameAssembly.dll` SHA-256. An unknown game update
leaves those features disabled instead of trying old offsets.

## Before using it

The current [Task Bar Hero terms](https://store.steampowered.com/eula/3678970_eula_0)
prohibit unauthorized reverse engineering, hacks, macros, and auto programs.
Only use or distribute the automation features if you have permission from the
game publisher and comply with Steam's rules. The project is not affiliated
with the game developers or Valve. See [NOTICE.md](NOTICE.md).

## Supported platform

- Windows 10 or Windows 11, x64
- Python 3.11 or 3.12 when running from source
- Task Bar Hero through Steam
- BepInEx IL2CPP when building or using the Auto Unbox companion

See [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md) for the exact supported game
build. Marketing version numbers alone are not accepted as compatibility proof.

## Run from source

```powershell
git clone <repository-url> TBHAstrarium
cd TBHAstrarium
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\scripts\run.ps1 -Python .\.venv\Scripts\python.exe
```

Task Bar Hero must already be running. If Windows denies process access, run
TBH Astrarium at the same privilege level as the game.

User settings, watch lists, logs, and the SQLite database are stored in:

```text
%LOCALAPPDATA%\TBHAstrarium
```

They are never expected inside the repository.

## Optional local item names

Game and wiki datasets are intentionally absent from Git. The app reads item
type, grade, and level from a supported running game. Unknown display names use
an item ID fallback.

Users who independently have permission to use a catalog may place either file
below in `%LOCALAPPDATA%\TBHAstrarium`:

- `catalog.local.json`: object mapping item ID strings to display names.
- `wiki-items.local.json`: array using the richer catalog shape accepted by
  `load_catalog()`.

## Auto Unbox companion

Auto Unbox uses a separate BepInEx plugin because it must call the game's
managed `StageBox` API on Unity's main thread. Build it only after BepInEx has
generated the game's interop assemblies:

```powershell
$env:TBH_GAME_DIR = "D:\SteamLibrary\steamapps\common\TaskbarHero"
.\scripts\build-companion.ps1
```

The companion build also requires the .NET 6 SDK or newer. Use `-Dotnet` when
`dotnet.exe` is installed outside `PATH`.

Copy `companion\bin\Release\net6.0\TBHAstrarium.Companion.dll` into the game's
`BepInEx\plugins` directory, then start the game. The named pipe retains its old
identifier so existing local installations remain compatible.

## Build the Windows app

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -c constraints-release.txt
.\scripts\test.ps1 -Python .\.venv\Scripts\python.exe
.\scripts\build.ps1 -Python .\.venv\Scripts\python.exe
```

The portable build is written to `dist\TBHAstrarium`. Build artifacts are
ignored by Git and should be attached to a GitHub Release with a SHA-256 digest.

## Repository layout

```text
src/tbhastrarium/   Python application and Frida agents
companion/          BepInEx Auto Unbox source
profiles/           public compatibility records without raw game dumps
tests/              offline controller, policy, storage, and UI tests
scripts/            run, test, and build entry points
docs/               compatibility and release guidance
```

## Privacy and networking

TBH Astrarium stores its own data locally and does not contain telemetry or an
update service. The main application reads the local game process. Automation
uses a local Frida session or a local named pipe to the companion.

## License

Original source code in this repository is licensed under the [MIT License](LICENSE).
Game assets, game data, extracted metadata, and third-party components are not
covered by that license.
