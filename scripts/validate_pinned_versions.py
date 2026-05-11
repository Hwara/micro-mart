"""Validate that pinned requirement versions exist on PyPI."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _iter_pins(path: Path):
    """Yield package/version pairs from package==version constraint lines."""
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line or "==" not in line:
            continue

        # drop environment marker (PEP 508)
        requirement_part = line.split(";", 1)[0].strip()
        package_part, version = requirement_part.split("==", 1)
        # drop extras for PyPI project endpoint
        package = package_part.split("[", 1)[0].strip()
        version = version.strip()
        if package and version:
            yield line_number, package, version


def _pypi_versions(package: str) -> set[str]:
    """Return all published versions for a package from the PyPI JSON API."""
    url = f"https://pypi.org/pypi/{package}/json"
    request = urllib.request.Request(url, headers={"User-Agent": "micro-mart-pin-validator"})
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.load(response)
    return set(payload.get("releases", {}))


def main() -> int:
    """Validate requirements/constraints.txt pins and return a process exit code."""
    constraints_path = (
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path("requirements/constraints.txt")
    )
    failures: list[str] = []

    for line_number, package, version in _iter_pins(constraints_path):
        try:
            versions = _pypi_versions(package)
        except urllib.error.HTTPError as exc:
            failures.append(
                f"{line_number}: {package}=={version} package lookup failed ({exc.code})"
            )
            continue
        except urllib.error.URLError as exc:
            failures.append(f"{line_number}: {package}=={version} network error: {exc.reason}")
            continue

        if version not in versions:
            failures.append(f"{line_number}: {package}=={version} version is not published on PyPI")

    if failures:
        print("Pinned version validation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"All pinned versions in {constraints_path} exist on PyPI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
