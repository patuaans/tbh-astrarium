# Release checklist

1. Obtain permission needed to distribute the helper and its automation.
2. Confirm the target game hash appears as a verified profile.
3. Install with `requirements-dev.txt` and `constraints-release.txt`, then run
   `scripts/test.ps1` in a clean virtual environment.
4. Run `scripts/build.ps1` and smoke-test the portable app on Windows.
5. Build the companion from a locally installed game; never commit its game
   references, `bin`, or `obj` directories.
6. Stage the intended source and run `scripts/check-release.ps1`. It rejects
   common private artifacts, large files, credentials, Steam IDs, and personal
   absolute paths.
7. Scan the complete Git history for secrets before making the repository
   public.
8. Attach the portable ZIP and companion DLL to a GitHub Release and publish
   their SHA-256 values. Keep release binaries out of Git history.
9. Document the exact supported game SHA-256 and known limitations in the
   release notes.
