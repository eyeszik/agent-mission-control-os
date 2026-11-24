import pytest
from services.langgraph.agency.obscura_preflight import preflight


def test_disabled_preserves_chromium():
    assert preflight().provider == 'chromium'
    assert preflight().status == 'DISABLED'


@pytest.mark.parametrize('task', ['e2e', 'webgl', 'webgpu', 'svg', 'creative', 'visual_qa'])
def test_compatibility_owner_preserved(task):
    result = preflight(enabled=True, task=task)
    assert result.provider == 'chromium'
    assert result.status == 'EXISTING_PATH'


def test_unsupported_platform():
    assert preflight(enabled=True, system='Windows', machine='x86_64').status == 'UNSUPPORTED_PLATFORM'


@pytest.mark.parametrize('system,machine', [('Linux', 'x86_64'), ('Linux', 'aarch64'), ('Darwin', 'arm64'), ('Darwin', 'x86_64')])
def test_no_flag_can_authorize_uncontained_execution(system, machine):
    result = preflight(enabled=True, system=system, machine=machine)
    assert result.status == 'BLOCKED'
    assert len(result.reasons) == 2
