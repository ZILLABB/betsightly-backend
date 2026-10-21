"""Contract tests for the protected admin's actual inline UI and state machine.

The admin is intentionally served as a same-origin Python HTML/CSS/JS module,
so these checks cover the JavaScript sent to the browser rather than pretending
there is an independent React admin build.
"""
from __future__ import annotations

import shutil
import subprocess

import pytest

from growth.admin_ui import ADMIN_CSS, ADMIN_HTML, ADMIN_JS


def test_manual_workflow_has_accessible_phase_by_phase_feedback():
    assert 'id="manualWorkflow"' in ADMIN_HTML
    assert 'aria-live="polite"' in ADMIN_HTML
    assert 'aria-busy="false"' in ADMIN_HTML
    assert 'id="manualWorkflowTitle"' in ADMIN_HTML
    assert 'id="manualWorkflowDetail"' in ADMIN_HTML
    for name in ("Read code", "Review selections", "Check live prices",
                 "Publish", "Confirm saved"):
        assert name in ADMIN_HTML
    for step in ("1", "2", "3", "4", "5"):
        assert f'data-manual-step="{step}"' in ADMIN_HTML


def test_manual_upload_guard_and_publication_reconciliation():
    assert "if(manualBusyOperation)return;" in ADMIN_JS
    assert "manualFormLock(true)" in ADMIN_JS
    assert "manualFormLock(false)" in ADMIN_JS
    assert "manualPublishUncertain=true" in ADMIN_JS
    assert "if(manualPublishUncertain && (name==='publish'||name==='publish-imported'))" in ADMIN_JS
    assert "manualRefreshPublished()" in ADMIN_JS
    assert "manualUncertainTier" in ADMIN_JS
    assert "manualPreviewConfirmed=null" in ADMIN_JS
    assert "current.share_code===d.share_code" in ADMIN_JS
    assert "manualStage(5,'success','Published and saved" in ADMIN_JS
    assert "data-act=\"manual-refresh\"" in ADMIN_HTML


def test_file_import_never_discards_selections_silently():
    assert "if(file.size>16000)" in ADMIN_JS
    assert "if(source.length>6000)" in ADMIN_JS
    assert "silently truncating games is unsafe" in ADMIN_JS
    assert "source.slice(0,6000)" not in ADMIN_JS
    assert "manualImportedCode=null;manualPreviewConfirmed=null" in ADMIN_JS


def test_shared_admin_loading_feedback_is_real_not_a_fake_progress_percentage():
    assert 'id="adminActivity"' in ADMIN_HTML
    assert 'id="adminActivityText"' in ADMIN_HTML
    assert "adminActionInFlight.has(act)" in ADMIN_JS
    assert "adminRunAction(el.dataset.act,el,fn)" in ADMIN_JS
    for surface in ("health", "audienceKpis", "contentTable", "pubTable", "refTable"):
        assert f"adminTableLoading('{surface}'" in ADMIN_JS
        assert f"adminTableReady('{surface}'" in ADMIN_JS
    assert "aria-busy" in ADMIN_JS
    assert ".admin-table-skeleton" in ADMIN_CSS
    assert ".manual-workflow" in ADMIN_CSS
    assert "@media(prefers-reduced-motion:reduce)" in ADMIN_CSS


def test_admin_uses_approved_atlantic_brand_with_semantic_status_colors():
    assert "--bg:#0B2238" in ADMIN_CSS
    assert "--brand:#69B0D6" in ADMIN_CSS
    assert "--amber:#E5AD70" in ADMIN_CSS
    assert "--success:#77D4B6" in ADMIN_CSS
    assert ".manual-workflow-steps" in ADMIN_CSS
    assert ".btn:focus-visible" in ADMIN_CSS


def test_admin_browser_javascript_syntax_is_valid():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node unavailable; manual review of admin JS required")
    proc = subprocess.run(
        [node, "--check"],
        input=ADMIN_JS,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
