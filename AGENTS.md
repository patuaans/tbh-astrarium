# Repository instructions

- Treat the full SHA-256 of `GameAssembly.dll` as the compatibility key.
- Never enable a memory reader or automation for an unknown game build.
- Keep user data under `%LOCALAPPDATA%\TBHAstrarium`; do not add it to Git.
- Do not commit game binaries, IL2CPP dumps, generated interop assemblies,
  extracted catalogs, saves, logs, or third-party binary bundles.
- Run `scripts/test.ps1` before changing source agents or automation policy.
- Validate new offsets with read-only probes before testing a write action.
- Do not modify or replace the installed game files as part of application tests.
- Add each verified build to `src/tbhastrarium/supported-builds.json` and
  `profiles/<sha256>/profile.json`; retain older profiles for diagnosis.
