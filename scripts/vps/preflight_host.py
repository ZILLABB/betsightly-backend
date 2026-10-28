"""Inspect a Linux VPS without changing it or reading application secrets.

Run: python -m scripts.vps.preflight_host --phase preinstall
After installing Docker and PostgreSQL 18 client, use --phase staging.
Exit 0 = minimum checks pass; 2 = unmet minimum. Emits sanitized JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys

from utils.vps_host_preflight import assess_host


def _os_id():
    try:
        with open("/etc/os-release", encoding="utf-8") as file:
            for line in file:
                if line.startswith("ID="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "unknown"


def _ram_gib():
    with open("/proc/meminfo", encoding="utf-8") as file:
        first = file.readline()
    match = re.search(r"^MemTotal:\s+(\d+)\s+kB", first)
    if not match:
        raise ValueError("unable to read system memory")
    return int(match.group(1)) / (1024 * 1024)


def _command_ok(command):
    try:
        return subprocess.run(command, capture_output=True, timeout=6, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _pg_dump_major():
    if not shutil.which("pg_dump"):
        return None
    try:
        proc = subprocess.run(["pg_dump", "--version"], capture_output=True,
                              text=True, timeout=6, check=True)
        match = re.search(r"\b(\d+)\.\d+\b|\b(\d+)\b", proc.stdout)
        return int(next(group for group in match.groups() if group is not None)) if match else None
    except (OSError, subprocess.SubprocessError):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("preinstall", "staging"),
                        default="preinstall")
    args = parser.parse_args()
    try:
        usage = shutil.disk_usage("/")
        result = assess_host(
            os_id=_os_id(),
            arch=platform.machine(),
            cpu_cores=os.cpu_count() or 0,
            total_ram_gib=_ram_gib(),
            free_disk_gib=usage.free / 1024 ** 3,
            docker_available=_command_ok(["docker", "version", "--format", "{{.Server.Version}}"]),
            compose_available=_command_ok(["docker", "compose", "version"]),
            pg_dump_major=_pg_dump_major(),
            phase=args.phase,
        )
    except Exception as exc:
        result = {"ready": False, "blockers": [f"preflight_error:{type(exc).__name__}"]}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ready"] else 2


if __name__ == "__main__":
    sys.exit(main())
