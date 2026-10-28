"""Pure host-readiness scoring for the intended shared VPS footprint.

This is a capacity sanity check, *not* proof of performance or security.
Do not infer VPS purchase/provisioning from a passing score.
"""

from __future__ import annotations


def assess_host(*, os_id: str, arch: str, cpu_cores: int,
                total_ram_gib: float, free_disk_gib: float,
                docker_available: bool, compose_available: bool,
                pg_dump_major: int | None, phase: str) -> dict:
    if phase not in {"preinstall", "staging"}:
        raise ValueError("phase must be preinstall or staging")
    blockers = []
    warnings = []
    if os_id not in {"ubuntu", "debian"}:
        blockers.append("unsupported_os")
    if arch not in {"x86_64", "aarch64"}:
        blockers.append("unsupported_architecture")
    if cpu_cores < 4:
        blockers.append("cpu_below_4")
    if total_ram_gib < 12:
        blockers.append("ram_below_12_gib")
    elif total_ram_gib < 20:
        warnings.append("recommended_ram_24_gib")
    if free_disk_gib < 60:
        blockers.append("available_storage_below_60_gib")
    if not docker_available:
        (blockers if phase == "staging" else warnings).append("docker_missing")
    if not compose_available:
        (blockers if phase == "staging" else warnings).append("docker_compose_missing")
    if pg_dump_major is None or pg_dump_major < 18:
        (blockers if phase == "staging" else warnings).append("pg18_client_missing")
    return {
        "ready": not blockers,
        "phase": phase,
        "blockers": blockers,
        "warnings": warnings,
        "cpu_cores": cpu_cores,
        "ram_gib": round(total_ram_gib, 2),
        "free_disk_gib": round(free_disk_gib, 2),
        "note": "Capacity/installed tools only; not a security, CPU performance or restore acceptance test",
    }
