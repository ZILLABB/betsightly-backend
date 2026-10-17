"""The protected manual admin workflow must not expose unsafe one-click booking."""
from growth.admin_ui import ADMIN_JS, ADMIN_HTML


def test_manual_admin_offers_explicit_tier_replacement():
    assert 'id="manualReplaceOfficialDisplay"' in ADMIN_HTML
    assert 'Replace today\'s displayed official tier' in ADMIN_HTML
    assert "replace_official_display" in ADMIN_JS
    assert "['2_odds','5_odds','10_odds','over_1_5']" in ADMIN_JS


def test_imported_code_must_be_decoded_and_previewed_before_publishing():
    assert "manualImportedCode=null" in ADMIN_JS
    assert "manualPreviewConfirmed=null" in ADMIN_JS
    assert "manualCodePublish').disabled=true" in ADMIN_JS
    assert "manualPreviewConfirmed.lines!==request.lines" in ADMIN_JS
    assert "/manual-tiers/publish-imported" in ADMIN_JS
    assert "manual-publish-imported" in ADMIN_HTML
    assert 'id="manualCodePublish" disabled' in ADMIN_HTML
    assert "Publish reviewed rows" in ADMIN_HTML
    assert "Click Find games from code" in ADMIN_JS


def test_admin_displays_http_or_validation_error_instead_of_generic_failed():
    assert "Array.isArray(detail)" in ADMIN_JS
    assert "'HTTP '+r.status" in ADMIN_JS
    assert "Network request failed" in ADMIN_JS
    assert "if(!request.lines.trim())" in ADMIN_JS


def test_editorial_history_remains_intact_in_admin_language():
    assert "original model tickets and codes are preserved" in ADMIN_HTML.lower()
    assert "original model selection, code and Results remain unchanged" in ADMIN_JS



def test_manual_ui_displays_nonblocking_cross_tier_exposure():
    assert 'd.cross_tier_warnings||[]' in ADMIN_JS
    assert 'Shared fixtures (allowed for manual tickets)' in ADMIN_JS
    assert 'Outcomes across tickets can be correlated.' in ADMIN_JS
