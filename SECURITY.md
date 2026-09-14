# Security policy

## Reporting

Report a vulnerability privately to the repository owner before opening a
public issue. Include the affected version, reproduction steps, and whether a
game or user-data write occurred.

## Data handled by the application

TBH Astrarium keeps settings and history in `%LOCALAPPDATA%\TBHAstrarium`.
Diagnostic logs can include item identifiers, stage information, and local
timestamps. Remove those details before sharing a log publicly.

The application does not request Steam credentials and should never contain an
API key, password, save file, Steam session identifier, or authentication
token. Unknown game builds must remain fail-closed.
