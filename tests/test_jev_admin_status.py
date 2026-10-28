"""Jev admin view must be inert, protected and HTML safe."""
from growth.jev_admin_status import render_desk


def test_read_only_atlantic_research_page():
    report = {
        "provider": {"status": "api_calls_disabled"},
        "audits": {"total": 0},
        "external_sources": {"openligadb_fetch_enabled": False},
        "basketball": {"NBA": "shadow_contract_available_but_not_live"},
    }
    page = render_desk(report)
    assert "Jev External Intelligence" in page
    assert "api_calls_disabled" in page
    assert "Back to Command Center" in page
    assert "Research-only" in page
    assert "No public betting changes" in page
    assert "<script" not in page.lower()
    assert "onclick" not in page.lower()


def test_provider_fields_are_escaped():
    report = {
        "provider": {"status": "<script>alert('x')</script>"},
        "audits": {"total": 0},
        "external_sources": {},
        "basketball": {},
    }
    result = render_desk(report)
    assert "<script>alert" not in result
    assert "&lt;script&gt;" in result
