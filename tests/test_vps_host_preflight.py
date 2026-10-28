from utils.vps_host_preflight import assess_host


def _host(**overrides):
    fields = dict(os_id="ubuntu", arch="x86_64", cpu_cores=8,
                  total_ram_gib=24, free_disk_gib=100,
                  docker_available=True, compose_available=True,
                  pg_dump_major=18, phase="staging")
    fields.update(overrides)
    return assess_host(**fields)


def test_24_gib_vps_satisfies_minimum_tool_preflight():
    assert _host()["ready"]
    assert not _host()["warnings"]


def test_preinstall_can_be_ready_when_tooling_not_installed():
    result = _host(phase="preinstall", docker_available=False,
                   compose_available=False, pg_dump_major=None)
    assert result["ready"]
    assert "docker_missing" in result["warnings"]


def test_staging_fails_missing_docker_compose_and_pg18():
    result = _host(docker_available=False, compose_available=False,
                   pg_dump_major=16)
    assert not result["ready"]
    assert "docker_missing" in result["blockers"]
    assert "docker_compose_missing" in result["blockers"]
    assert "pg18_client_missing" in result["blockers"]


def test_cpu_ram_disk_bounds_fail_without_faking_readiness():
    r = _host(cpu_cores=2, total_ram_gib=8, free_disk_gib=12)
    assert not r["ready"]
    assert set(r["blockers"]) >= {
        "cpu_below_4", "ram_below_12_gib", "available_storage_below_60_gib"
    }


def test_unsupported_platform_is_blocked():
    assert "unsupported_os" in _host(os_id="windows")["blockers"]
    assert "unsupported_architecture" in _host(arch="i686")["blockers"]


def test_sized_16g_host_warns_but_can_stage():
    result = _host(total_ram_gib=16)
    assert result["ready"]
    assert result["warnings"] == ["recommended_ram_24_gib"]
