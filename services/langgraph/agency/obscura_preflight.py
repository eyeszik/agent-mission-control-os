"""Optional browser routing preflight; never launches uncontained page code.

This is discovery, not an execution permit. Existing Chromium owners remain
unchanged. Upstream capability assertions do not establish AMC readiness.
"""
from dataclasses import dataclass
from typing import Literal

Provider = Literal['chromium', 'obscura']


@dataclass(frozen=True)
class BrowserPreflight:
    provider: Provider
    status: Literal['EXISTING_PATH', 'DISABLED', 'UNSUPPORTED_PLATFORM', 'BLOCKED']
    reasons: tuple[str, ...] = ()


def preflight(*, enabled: bool = False, task: str = 'research',
              system: str = '', machine: str = '') -> BrowserPreflight:
    """Keep compatibility tasks on their existing owner; fail closed otherwise.

    No caller-supplied boolean can certify sandbox or egress readiness. Those
    controls require a future independently tested canonical execution adapter.
    """
    if task in {'e2e', 'webgl', 'webgpu', 'svg', 'creative', 'visual_qa'}:
        return BrowserPreflight('chromium', 'EXISTING_PATH')
    if not enabled:
        return BrowserPreflight('chromium', 'DISABLED')
    if system not in {'Linux', 'Darwin'} or machine not in {'x86_64', 'arm64', 'aarch64'}:
        return BrowserPreflight('obscura', 'UNSUPPORTED_PLATFORM')
    return BrowserPreflight('obscura', 'BLOCKED', (
        'PUBLIC_BROWSING_DISABLED: restricted public egress is not activated',
        'AUTHENTICATED_PATH_REQUIRED: supplied HTML uses the project extraction API',
    ))
