"""PSEM is a Foundry grammar and genome profile whose colour rules are computed and enforced, not asserted."""

from __future__ import annotations

import pytest

from services.langgraph.agency.foundry import psem
from services.langgraph.agency.foundry.compose import poster, roles_used
from services.langgraph.agency.foundry.contracts import UserBrief
from services.langgraph.agency.foundry.grammars import GRAMMARS
from services.langgraph.agency.ui_ux.tokens import wcag_contrast_ratio

ROLE_TO_PSEM = psem.ROLES


def _genome(seed: int = 7):
    return psem.compile_psem_genome(psem.psem_brief("Halden Fen (fictional)", seed=seed), project_id="proj-psem")


def test_psem_is_a_registered_grammar_with_lineage_and_anti_patterns():
    g = GRAMMARS[psem.GRAMMAR_ID]
    assert "monumental_negative_space" in g.composition_operators and "micro_label" in g.composition_operators
    assert "reproduces no specific work" in g.lineage_note
    assert any("more than one accent" in a for a in g.anti_patterns)
    assert any("accent text on paper" in a for a in g.anti_patterns)


def test_pairings_are_computed_with_the_repository_wcag_function():
    for key, pair in psem.PAIRINGS.items():
        fg, bg = key.split("/")
        assert pair["ratio"] == round(wcag_contrast_ratio(psem.PALETTE[fg], psem.PALETTE[bg]), 2)
    # The palette's trap: accents fail on paper, pass on charcoal.
    assert psem.PAIRINGS["signal_red/paper"]["graphic"] is False and psem.PAIRINGS["amber/paper"]["graphic"] is False
    assert psem.PAIRINGS["signal_red/charcoal"]["text"] is True and psem.PAIRINGS["charcoal/amber"]["text"] is True
    assert psem.PAIRINGS["fog/paper"]["text"] is False and psem.PAIRINGS["fog/paper"]["large_text"] is True


@pytest.mark.parametrize(("fg", "bg", "use"), [("signal_red", "paper", "graphic"), ("amber", "paper", "large_text"),
                                               ("fog", "paper", "text"), ("graphite", "charcoal", "text")])
def test_forbidden_pairings_are_refused(fg, bg, use):
    with pytest.raises(psem.PsemUsageError):
        psem.check_usage(fg, bg, use)


def test_one_accent_per_composition_unless_approved():
    psem.one_accent({"charcoal", "paper", "signal_red"})
    with pytest.raises(psem.PsemUsageError):
        psem.one_accent({"charcoal", "signal_red", "amber"})
    psem.one_accent({"charcoal", "signal_red", "amber"}, approved_second_accent=True)


def test_genome_locks_the_palette_and_refuses_a_different_one():
    g = _genome()
    assert g.color_rules["locked"] is True and "color_rules.palette" in g.invariants
    assert g.palette.ink == psem.PALETTE["charcoal"] and g.palette.accent == psem.PALETTE["signal_red"]
    assert g.composition_rules["dominant_grammar"] == psem.GRAMMAR_ID
    other = psem.psem_brief("X").model_copy(update={"brand_constraints": {"palette": {
        "ink": "#000000", "paper": "#ffffff", "accent": "#ff0000", "accent_2": "#00ff00", "muted": "#888888"}}})
    with pytest.raises(psem.PsemUsageError):
        psem.compile_psem_genome(other, project_id="p")
    with pytest.raises(psem.PsemUsageError):
        psem.compile_psem_genome(UserBrief(organization="X", visual_direction={"swiss_editorial": 1},
                                           brand_constraints=psem.psem_brief("X").brand_constraints), project_id="p")


def test_a_psem_poster_passes_its_own_pairing_rules_everywhere():
    g = _genome()
    for seed in range(6):
        ir = poster(g, headline="Made slowly, used daily", subhead="Small-batch stoneware", cta="Visit", variant_seed=seed)
        bg = ROLE_TO_PSEM[ir.background]
        assert bg == "charcoal"  # accents are only legal on charcoal
        used = {ROLE_TO_PSEM[r] for r in roles_used(ir) if r in ROLE_TO_PSEM}
        psem.one_accent(used)
        for p in ir.primitives:
            for role in {p.fill, p.stroke} - {None, "none"}:
                if ROLE_TO_PSEM[role] != bg:
                    psem.check_usage(ROLE_TO_PSEM[role], bg, "graphic")
        for t in ir.text:
            psem.check_usage(ROLE_TO_PSEM[t.fill], bg, "large_text" if t.size >= 24 else "text")


def test_psem_tokens_compile_through_the_one_token_compiler():
    doc, css, source_hash = psem.compile_psem_tokens(_genome())
    assert "--amc-color-graphite" in css and "--amc-color-accent" in css
    assert doc["$extensions"]["amc.psem"]["grammar"] == psem.GRAMMAR_ID
    assert "signal_red/paper" not in doc["$extensions"]["amc.psem"]["pairings"]  # only legal pairs are published
    assert len(source_hash) == 64
    assert psem.compile_psem_tokens(_genome()) == (doc, css, source_hash)  # deterministic
