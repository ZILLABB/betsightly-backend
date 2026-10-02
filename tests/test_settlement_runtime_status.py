import leagues.results_checker as results_checker


class _AliveThread:
    def is_alive(self):
        return True


def test_settlement_status_reports_loop_runtime(monkeypatch):
    thread = _AliveThread()

    monkeypatch.setattr(
        results_checker,
        "_results_checker_thread",
        thread,
    )
    monkeypatch.setattr(
        results_checker,
        "_last_loop_iteration",
        7,
    )
    monkeypatch.setattr(
        results_checker,
        "_last_loop_started_at",
        "2026-10-02T14:13:00+00:00",
    )
    monkeypatch.setattr(
        results_checker,
        "_last_loop_finished_at",
        "2026-10-02T14:13:03+00:00",
    )
    monkeypatch.setattr(
        results_checker,
        "_last_loop_error",
        None,
    )
    monkeypatch.setattr(
        results_checker,
        "_last_loop_summary",
        {
            "published_slips": {
                "slips_checked": 5,
                "won": 1,
            }
        },
    )

    status = results_checker.settlement_status()

    assert status["thread_alive"] is True
    assert status["iteration"] == 7
    assert (
        status["last_cycle_finished_at"]
        == "2026-10-02T14:13:03+00:00"
    )
    assert status["last_cycle_error"] is None
    assert (
        status["last_cycle_summary"]
        ["published_slips"]
        ["slips_checked"]
        == 5
    )


def test_results_checker_start_is_idempotent(monkeypatch):
    thread = _AliveThread()

    monkeypatch.setattr(
        results_checker,
        "_results_checker_thread",
        thread,
    )

    class _ShouldNotStart:
        def __init__(self, *args, **kwargs):
            raise AssertionError(
                "a second results checker was started"
            )

    monkeypatch.setattr(
        results_checker.threading,
        "Thread",
        _ShouldNotStart,
    )

    assert (
        results_checker.start_background_loop()
        is thread
    )
