"""On-demand dependency diagnostics. No jobs or agent settings are written."""

from __future__ import annotations

import re
import subprocess
from typing import Any

from print3d.blender import BlenderError, find_blender
from print3d.studio import StudioError, find_studio

PROBE_TIMEOUT = 5


def dependency_status() -> dict[str, Any]:
    checks = {}
    for name, finder, flag in (
        ("blender", find_blender, "--version"),
        ("studio", find_studio, "--help"),
    ):
        check: dict[str, Any] = {"path": None, "version": None, "ready": False}
        checks[name] = check
        try:
            binary = finder()
        except (BlenderError, StudioError) as exc:
            check.update(status="missing", message=str(exc))
            continue
        check["path"] = str(binary)
        try:
            result = subprocess.run(
                [str(binary), flag], capture_output=True, text=True, errors="replace",
                timeout=PROBE_TIMEOUT, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            check.update(status="unavailable", message=str(exc))
            continue
        if result.returncode != 0:
            check.update(status="unavailable", message=f"Dependency probe exited {result.returncode}.")
            continue
        version = re.search(
            r"(?:Blender|Bambu\s*Studio|BambuStudio)[ \t]+(?:version[ \t]+)?v?(\d+(?:\.\d+)+)",
            result.stdout + "\n" + result.stderr, re.IGNORECASE,
        )
        check.update(
            status="available", ready=True,
            version=version.group(1) if version else None,
            message="Dependency probe succeeded." if version else "Dependency probe succeeded; version unknown.",
        )
    return {"ready": all(check["ready"] for check in checks.values()), "dependencies": checks}
