import pytest
from utils.vps_cutover import require_writer_activation, APPROVED_TOKEN


@pytest.mark.parametrize("role", ["publication", "settlement", "telegram"])
def test_new_vps_writer_requires_explicit_activation(role):
    for value in (None, "", "true", "disabled", "approved"):
        with pytest.raises(SystemExit):
            require_writer_activation(role, value)
    require_writer_activation(role, APPROVED_TOKEN)


@pytest.mark.parametrize("role", ["web", "worker", "scheduler", "all"])
def test_legacy_roles_remain_compatible(role):
    require_writer_activation(role, None)
