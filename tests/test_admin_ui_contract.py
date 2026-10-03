from growth.admin_ui import ADMIN_CSS, ADMIN_HTML, ADMIN_JS


def test_command_center_integrity_contract():
    assert "Analytics ingestion" in ADMIN_JS
    assert "Analytics integrity" in ADMIN_JS
    assert "Analytics integrity needs attention" in ADMIN_JS
    assert "All key systems look healthy" in ADMIN_JS

    assert "Provider total estimate:" in ADMIN_JS
    assert "unique of ${num(declared)} declared fixtures" not in ADMIN_JS

    assert "\u2014 No change vs prior" in ADMIN_JS


def test_command_center_visual_system_contract():
    assert "command-center-ui-v2" in ADMIN_CSS

    assert "overview-funnel-grid" in ADMIN_HTML
    assert "overview-insight-grid" in ADMIN_HTML
    assert "env-pill" in ADMIN_HTML

    assert "grid-template-columns:repeat(3,minmax(0,1fr))" in ADMIN_CSS
    assert "@media(max-width:800px)" in ADMIN_CSS
    assert "@media(max-width:520px)" in ADMIN_CSS

    assert '<script src="http' not in ADMIN_HTML
    assert '<link href="http' not in ADMIN_HTML


def test_command_center_sidebar_remains_navigable():
    assert "height:100dvh" in ADMIN_CSS
    assert "overflow-y:auto" in ADMIN_CSS
    assert "scrollbar-gutter:stable" in ADMIN_CSS
    assert "dashboard-loading" in ADMIN_CSS
    assert "Refreshing dashboard" in ADMIN_JS


def test_command_center_alert_severity_and_loading_copy():
    assert "alert-severity-v2" in ADMIN_JS
    assert "const good=" in ADMIN_JS
    assert "All key systems look healthy" in ADMIN_JS
    assert "alert-ok" in ADMIN_JS
    assert "alert-warn" in ADMIN_JS
    assert "&#10003;" in ADMIN_JS
    assert "Refreshing dashboard..." in ADMIN_JS
    assert "Refreshing dashboard?" not in ADMIN_JS
