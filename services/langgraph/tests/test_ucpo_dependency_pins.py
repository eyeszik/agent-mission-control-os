import json


def test_generated_source_dependency_pins_match_workspace():
    """The sandbox rejects generated source that targets uninstalled versions."""
    from pathlib import Path
    from services.langgraph.agency.ucpo.source import DEPENDENCIES

    root = Path(__file__).resolve().parents[3]
    workspace = json.loads((root / "apps/web/package.json").read_text())
    for name, version in DEPENDENCIES.items():
        assert version == workspace["dependencies"][name], name
