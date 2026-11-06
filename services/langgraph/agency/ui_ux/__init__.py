"""UI/UX design compiler: governed product/brand state -> validated UI spec.

Pure and deterministic. Terminal success is ``UIUX_SPEC_READY``; it hands off a
specification and prompt inputs, and never generates, renders, publishes, or
deploys an interface. See docs/ui-ux-design-compiler.md.
"""

from .compiler import compile_uiux, infer_surface
from .models import (
    UIUX_COMPILER_VERSION,
    UIUX_SCHEMA_VERSION,
    UIUX_SPEC_READY,
    BrandContext,
    SurfaceMode,
    UIUXDesignIR,
    UIUXRequest,
    UIUXTerminal,
)
from .prompt_adapter import (
    brand_context_from_core,
    directive_buckets,
    request_from_asset_requirement,
    serialize_spec_section,
    surface_for_asset_type,
)

__all__ = [
    "UIUX_COMPILER_VERSION",
    "UIUX_SCHEMA_VERSION",
    "UIUX_SPEC_READY",
    "BrandContext",
    "SurfaceMode",
    "UIUXDesignIR",
    "UIUXRequest",
    "UIUXTerminal",
    "brand_context_from_core",
    "compile_uiux",
    "directive_buckets",
    "infer_surface",
    "request_from_asset_requirement",
    "serialize_spec_section",
    "surface_for_asset_type",
]
