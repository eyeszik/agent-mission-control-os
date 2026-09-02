from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from services.langgraph.agency.assets import (
    render_background_pattern_svg,
    render_hero_svg,
    render_logo_svg,
)

_ZO_WORKSPACE = Path("/home/workspace")
_ZO_EXPORT_ROOT = _ZO_WORKSPACE / "Documents" / "agent-mission-control-ideas"


def resolve_export_root() -> Path:
    override = (os.environ.get("AMC_EXPORT_ROOT") or "").strip()
    if override:
        return Path(override)
    if _ZO_WORKSPACE.is_dir() and os.access(_ZO_WORKSPACE, os.W_OK):
        return _ZO_EXPORT_ROOT
    return Path(tempfile.gettempdir()) / "amc-idea-exports"


DEFAULT_EXPORT_ROOT = resolve_export_root()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "idea"


def _write_text(path: Path, body: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.rstrip() + "\n", encoding="utf-8")
    return str(path)


def _write_json(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return str(path)


def _brand_palette(package: dict) -> tuple[str, str, str]:
    tokens = (((package.get("design_system") or {}).get("tokens_json") or {}).get("brand") or {}).get("raw") or {}
    primary = ((tokens.get("primary") or {}).get("value")) or "#1F2937"
    secondary = ((tokens.get("secondary") or {}).get("value")) or "#F59E0B"
    surface = ((tokens.get("surface") or {}).get("value")) or "#F9FAFB"
    return primary, secondary, surface


def _write_rendered_assets(root: Path, package: dict) -> list[str]:
    asset_execution = package.get("asset_execution") or {}
    rendered_assets = asset_execution.get("rendered_assets") or []
    if not rendered_assets:
        return []
    primary, secondary, surface = _brand_palette(package)
    brief = package.get("brief") or {}
    strategy = package.get("strategy") or {}
    copy_variants = package.get("copy_variants") or []
    headline = (copy_variants[0] or {}).get("headline") if copy_variants else None
    audience = brief.get("target_audience") or "the intended audience"
    files_written: list[str] = []
    for asset in rendered_assets:
        output_path = root / asset["output_path"]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        asset_type = asset.get("asset_type")
        if asset_type == "logo_mark":
            body = render_logo_svg(
                brand_name=brief.get("brand_name") or "Brand",
                primary=primary,
                secondary=secondary,
                surface=surface,
                tagline=strategy.get("positioning_statement"),
            )
        elif asset_type == "background_pattern":
            body = render_background_pattern_svg(
                brand_name=brief.get("brand_name") or "Brand",
                primary=primary,
                secondary=secondary,
                surface=surface,
            )
        else:
            body = render_hero_svg(
                brand_name=brief.get("brand_name") or "Brand",
                headline=headline or strategy.get("positioning_statement") or "Built to launch",
                audience=audience,
                primary=primary,
                secondary=secondary,
                surface=surface,
                accent=secondary,
            )
        output_path.write_text(body, encoding="utf-8")
        files_written.append(str(output_path))
    review_queue = asset_execution.get("review_queue") or {}
    if review_queue.get("review_artifact_path"):
        checklist = "\n".join(f"- {item}" for item in review_queue.get("checklist") or [])
        files_written.append(
            _write_text(
                root / review_queue["review_artifact_path"],
                "\n".join(
                    [
                        "# Asset Approval Inbox",
                        "",
                        f"Status: {review_queue.get('review_status', 'pending_review')}",
                        "",
                        "## Review checklist",
                        checklist or "- Review required",
                    ]
                ),
            )
        )
    adapters = asset_execution.get("publishing_adapters") or []
    if adapters:
        files_written.append(_write_json(root / "branding" / "publishing-adapters.json", adapters))
    return files_written


def export_idea_workspace(*, brand_name: str, run_id: str, package: dict) -> dict:
    slug = _slugify(brand_name)
    override = (os.environ.get("AMC_EXPORT_ROOT") or "").strip()
    base = Path(override) if override else Path(DEFAULT_EXPORT_ROOT)
    root = base / f"{slug}-{run_id[:8]}"
    business = root / "business"
    branding = root / "branding"
    design_system = branding / "design-system"
    rendered_assets = branding / "rendered"
    files_written: list[str] = []

    business_workspace = package.get("business_workspace") or {}
    branding_workspace = package.get("branding_workspace") or {}
    design_package = package.get("design_system") or {}

    files_written.append(_write_json(root / "workspace-package.json", package))
    files_written.append(_write_json(root / "business" / "overview.json", business_workspace.get("overview") or {}))
    files_written.append(_write_json(root / "branding" / "raw-brand-data.json", branding_workspace.get("raw_brand_data") or {}))
    files_written.append(_write_json(design_system / "tokens.json", design_package.get("tokens_json") or {}))
    files_written.append(_write_json(design_system / "tailwind.extend.json", design_package.get("tailwind_config") or {}))
    files_written.append(_write_text(design_system / "global-tokens.css", design_package.get("global_tokens_css") or ":root {}\n"))

    for section in ("internal_docs", "production_docs", "prompt_library"):
        for document in business_workspace.get(section) or []:
            files_written.append(_write_text(root / document["path"], document["body"]))

    for section in ("internal_assets", "external_assets", "visual_asset_prompts"):
        for document in branding_workspace.get(section) or []:
            files_written.append(_write_text(root / document["path"], document["body"]))

    for section in ("component_scaffolds", "asset_recipes"):
        for document in design_package.get(section) or []:
            files_written.append(_write_text(root / document["path"], document["body"]))

    files_written.extend(_write_rendered_assets(root, package))

    validation_notes = "\n".join(f"- {item}" for item in (design_package.get("validation_notes") or []))
    files_written.append(_write_text(design_system / "validation-notes.md", f"# Validation Notes\n\n{validation_notes}" if validation_notes else "# Validation Notes\n"))

    return {
        "root_folder": str(root),
        "business_folder": str(business),
        "branding_folder": str(branding),
        "design_system_folder": str(design_system),
        "rendered_assets_folder": str(rendered_assets),
        "files_written": files_written,
    }
