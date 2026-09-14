"""Load and enforce the exact game-build allowlist.

Marketing version strings are not reliable for IL2CPP offsets. Every memory
reader or automation must match the complete GameAssembly.dll SHA-256 first.
"""

import hashlib
import json
import sys
from functools import lru_cache
from pathlib import Path


def resource_path(name):
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    packaged = root / "tbhastrarium" / name
    return packaged if packaged.exists() else Path(__file__).resolve().parent / name


@lru_cache(maxsize=1)
def supported_builds():
    payload = json.loads(resource_path("supported-builds.json").read_text(encoding="utf-8"))
    return {entry["gameAssemblySha256"].lower(): entry for entry in payload.get("builds", [])}


SUPPORTED_SHA256 = next(iter(supported_builds()))


@lru_cache(maxsize=8)
def _sha256_cached(path_string, size, modified_ns):
    del size, modified_ns
    digest = hashlib.sha256()
    with Path(path_string).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_sha256(path):
    path = Path(path).resolve()
    stat = path.stat()
    return _sha256_cached(str(path), stat.st_size, stat.st_mtime_ns)


def require_supported(path, feature):
    digest = file_sha256(path)
    profile = supported_builds().get(digest)
    if profile is None or feature not in profile.get("features", []):
        raise RuntimeError(
            f"Unsupported Task Bar Hero build ({digest[:12]}); {feature} was not started"
        )
    return profile
