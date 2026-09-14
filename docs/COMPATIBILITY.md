# Game-build compatibility

TBH Astrarium addresses native IL2CPP code by offsets relative to
`GameAssembly.dll`. A game update can move those functions even when the UI and
marketing version look unchanged.

| GameAssembly.dll SHA-256 | Steam build | Unity | Status |
| --- | --- | --- | --- |
| `a359faabf0101566a90f1d396b1c5528f2f2c77d710efe87125f7c197dcc3e27` | `25188646` | `6000.0.72f1` | Verified historical profile |

The application hashes the loaded `GameAssembly.dll` before reading memory or
attaching an automation agent. A hash absent from
`src/tbhastrarium/supported-builds.json` is unsupported.

Raw game dumps and generated interop assemblies are not part of the public
profile. Maintainers must obtain them from their own installation and follow
the process in [CONTRIBUTING.md](../CONTRIBUTING.md).
