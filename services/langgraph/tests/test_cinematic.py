"""Cinematic capability: regression fixtures A-J plus focused unit tests.

The fixtures mirror the named acceptance scenarios for the cinematic compiler.
They assert behaviour, not prose: routing, source-authority precedence,
continuity, camera discipline, entropy control, model independence, and the
generation firewall.
"""

from __future__ import annotations

import json

from services.langgraph.agency.cinematic import route_request, run_pipeline
from services.langgraph.agency.cinematic.adapters import adapt
from services.langgraph.agency.cinematic.authority import (
    promote_to_canon,
    requires_human_review,
    resolve_facts,
    unresolved_items,
)
from services.langgraph.agency.cinematic.camera import scene_path_conflicts, validate_camera
from services.langgraph.agency.cinematic.compilers import (
    PROTECTED_DIMENSIONS,
    compile_i2v,
    compile_t2v,
)
from services.langgraph.agency.cinematic.continuity import handshake_gaps
from services.langgraph.agency.cinematic.evaluation import (
    MAX_REPAIR_CYCLES,
    evaluate_shot,
    repair_shot,
)
from services.langgraph.agency.cinematic.motion import compile_brand_motion
from services.langgraph.agency.cinematic.schemas import (
    BrandMotion,
    CameraMove,
    CameraState,
    Character,
    CinematicRequest,
    ContinuityState,
    Fact,
    FactStatus,
    FinalFrameHandshake,
    InputMode,
    ModelProfile,
    PhysicsEvent,
    ProjectIR,
    PromptTarget,
    Scene,
    Beat,
    ShotIR,
    SourceAuthority,
    Story,
)
from services.langgraph.agency.cinematic.storyboard import (
    panels_to_shots,
    script_to_storyboard,
    shot_to_panel,
)


# --------------------------------------------------------------------------- #
# Fixture A — simple T2V
# --------------------------------------------------------------------------- #
def test_fixture_a_simple_t2v():
    result = run_pipeline(
        CinematicRequest(text="A woman waits alone for the last train in the rain.")
    )
    assert result.matched
    assert result.target is PromptTarget.t2v
    assert len(result.prompts) == 1
    prompt = result.prompts[0].prompt

    assert "waits alone for the last train" in prompt  # one clear action
    assert "a woman" in prompt.lower()                  # character
    assert "rain" in prompt.lower()                     # location
    assert "camera" in prompt.lower()                   # camera
    assert "available light" in prompt.lower()          # lighting
    assert "resolves and settles" in prompt.lower()     # final state

    # prompts-only mode must not emit a full production package
    prompts_only = run_pipeline(
        CinematicRequest(text="A woman waits for the train.", mode=InputMode.prompts_only)
    )
    assert prompts_only.prompts
    assert prompts_only.capability is None


def test_fixture_a_prompt_is_shorter_than_production_state():
    result = run_pipeline(
        CinematicRequest(text="A woman waits alone for the last train in the rain.")
    )
    shot_state = result.project.shots[0].model_dump_json()
    assert len(result.prompts[0].prompt) < len(shot_state)


# --------------------------------------------------------------------------- #
# Fixture B — character continuity
# --------------------------------------------------------------------------- #
def test_fixture_b_character_continuity():
    character = Character(
        id="mara",
        recurring=True,
        immutable_identity={"face": "freckled", "hair": "short auburn"},
        wardrobe={"coat": "red wool"},
    )
    s1 = ShotIR(
        id="s1",
        character_state={"subject": "Mara"},
        identity_refs=["character:mara"],
        final_frame=FinalFrameHandshake(subject_position="doorway", gaze="toward the hall"),
    )
    s2 = ShotIR(
        id="s2",
        character_state={"subject": "Mara"},
        identity_refs=["character:mara"],
        continuity=ContinuityState(),
    )
    project = ProjectIR(characters=[character], shots=[s1, s2])
    result = run_pipeline(CinematicRequest(mode=InputMode.video_package, project=project))

    # immutable identity packet is reused
    packet_ids = {p.packet_id for p in result.project.packets}
    assert "character:mara" in packet_ids
    packet = next(p for p in result.project.packets if p.packet_id == "character:mara")
    assert packet.locked["wardrobe"] == {"coat": "red wool"}

    # end-state of shot 1 propagated into shot 2's entry requirements
    propagated_s2 = result.project.shots[1]
    assert propagated_s2.continuity.entry_requirements.subject_position == "doorway"
    assert propagated_s2.continuity.inherits_from == "s1"


def test_continuity_gap_detected():
    s1 = ShotIR(id="s1", final_frame=FinalFrameHandshake(gaze="down"))
    s2 = ShotIR(
        id="s2",
        continuity=ContinuityState(entry_requirements=FinalFrameHandshake(gaze="up")),
    )
    gaps = handshake_gaps(s1, s2)
    assert any("gaze" in g for g in gaps)


# --------------------------------------------------------------------------- #
# Fixture C — storyboard generation
# --------------------------------------------------------------------------- #
def test_fixture_c_storyboard_generation():
    story = Story(
        scenes=[
            Scene(
                id="sc1",
                beats=[
                    Beat(id="b1", summary="she enters the room"),
                    Beat(id="b2", summary="she sees the letter", dramatic_change="dread"),
                    Beat(id="b3", summary="she reads it and sits"),
                ],
            )
        ]
    )
    board = script_to_storyboard(story)
    assert len(board) == 9                      # 9-panel default
    assert board[0].shot_id == "shot_001"       # panel -> shot mapping
    assert board[0].action == "she enters the room"
    assert board[2].composition                 # third beat carried into a panel


# --------------------------------------------------------------------------- #
# Fixture D — storyboard to video
# --------------------------------------------------------------------------- #
def test_fixture_d_storyboard_to_video():
    shots = [
        ShotIR(id="a", primary_action="hand reaches for the cup", character_state={"subject": "a hand"}),
        ShotIR(id="b", primary_action="cup lifts to frame", character_state={"subject": "a hand"}),
        ShotIR(id="c", primary_action="steam rises", character_state={"subject": "the cup"}),
    ]
    panels = [shot_to_panel(shot, i + 1) for i, shot in enumerate(shots)]
    recovered = panels_to_shots(panels)
    assert len(recovered) == 3                                  # one shot per panel
    assert recovered[0].primary_action == "hand reaches for the cup"  # blocking recovered

    result = run_pipeline(
        CinematicRequest(mode=InputMode.video_package, project=ProjectIR(shots=recovered))
    )
    assert len(result.prompts) == 3
    assert all(p.target is PromptTarget.t2v for p in result.prompts)


# --------------------------------------------------------------------------- #
# Fixture E — image to video
# --------------------------------------------------------------------------- #
def test_fixture_e_image_to_video():
    shot = ShotIR(id="p1", primary_action="she slowly turns her head toward the window")
    prompt = compile_i2v(shot, "portrait.png").prompt
    assert prompt.lower().startswith("preserve")          # preservation dominates
    assert "turns her head" in prompt                     # motion is the focus
    # no lengthy re-description of appearance the image already fixes
    assert "wardrobe" not in prompt or prompt.count("preserve") == 1

    routed = run_pipeline(CinematicRequest(text="image to video: make this portrait blink", source_image="p.png"))
    assert routed.target is PromptTarget.i2v


# --------------------------------------------------------------------------- #
# Fixture F — overloaded prompt / entropy control
# --------------------------------------------------------------------------- #
def test_fixture_f_entropy_control():
    shot = ShotIR(
        id="f1",
        character_state={"subject": "a lone cyclist"},
        location={"description": "a coastal road at dawn"},
        primary_action="pedals hard into a headwind",
        light={"source": "low sun"},
        color={"grade": "teal-and-orange " * 40},
        atmosphere={"haze": "salt spray " * 40},
        secondary_action="gulls scatter " * 20,
        final_frame=FinalFrameHandshake(motion_state="crests the hill"),
    )
    compiled = compile_t2v(shot, max_chars=220)
    assert compiled.dropped_optional                      # optional detail removed
    # protected dimensions survive
    assert "a lone cyclist" in compiled.prompt
    assert "pedals hard" in compiled.prompt
    assert "camera" in compiled.prompt.lower()
    assert "crests the hill" in compiled.prompt


def test_protected_dimensions_never_dropped():
    assert {"identity", "action", "camera", "light", "continuity", "end_state"} <= PROTECTED_DIMENSIONS


# --------------------------------------------------------------------------- #
# Fixture G — conflicting sources / source authority
# --------------------------------------------------------------------------- #
def test_fixture_g_conflicting_sources():
    facts = [
        Fact(key="coat", value="red", authority=SourceAuthority.supplied_script, status=FactStatus.defined),
        Fact(key="coat", value="blue", authority=SourceAuthority.verified_reference_fact, status=FactStatus.defined),
    ]
    ledger, conflicts = resolve_facts(facts)
    assert len(conflicts) == 1
    # higher authority (SUPPLIED_SCRIPT) preserved, no silent mutation
    assert conflicts[0]["kept_value"] == "red"
    assert conflicts[0]["kept_authority"] == SourceAuthority.supplied_script.value
    assert requires_human_review(ledger, [])


def test_inference_never_becomes_canon_silently():
    inferred = Fact(key="mood", value="tense", authority=SourceAuthority.reasonable_inference, status=FactStatus.inferred)
    try:
        promote_to_canon(inferred)
        raise AssertionError("expected promotion of an inference to be refused")
    except ValueError:
        pass


def test_unknown_critical_becomes_a_question():
    facts = [Fact(key="ending", value=None, authority=SourceAuthority.creative_default, status=FactStatus.unknown_critical, note="How does it end?")]
    items = unresolved_items(facts)
    assert items and items[0]["kind"] == "unknown_critical"


# --------------------------------------------------------------------------- #
# Fixture H — brand motion
# --------------------------------------------------------------------------- #
def test_fixture_h_brand_motion():
    brand = BrandMotion(identity="restrained luxury", holds=["on the dial"], amplitude="low", timing="slow")
    text = compile_brand_motion(brand)
    assert "restrained" in text.lower() or "low-amplitude" in text.lower()
    assert "deliberate holds" in text.lower()
    assert "no spring or bounce" in text.lower()   # arbitrary bounce excluded by default


# --------------------------------------------------------------------------- #
# Fixture I — capability-only request (no invented scene)
# --------------------------------------------------------------------------- #
def test_fixture_i_capability_only():
    result = run_pipeline(CinematicRequest(text="What can the cinematic system do?"))
    assert result.matched
    assert not result.generative
    assert result.capability is not None
    assert not result.prompts             # no invented movie scene
    assert not result.project


# --------------------------------------------------------------------------- #
# Fixture J — unknown model / portable prompt
# --------------------------------------------------------------------------- #
def test_fixture_j_unknown_model_portable():
    result = run_pipeline(
        CinematicRequest(text="text to video of a man walking through a market", mode=InputMode.video_package)
    )
    prompt = result.prompts[0]
    assert prompt.prompt_style == "natural"      # portable natural language
    assert "{" not in prompt.prompt              # no invented model-specific JSON params


def test_json_model_emits_json_only_when_required():
    plain = compile_t2v(ShotIR(id="j", character_state={"subject": "a man"}, primary_action="walks"))
    profile = ModelProfile(provider="acme", model="v1", prompt_style="json", negative_support=False)
    adapted = adapt(plain, profile)
    assert adapted.prompt_style == "json"
    payload = json.loads(adapted.prompt)
    assert payload["target"] == "T2V"
    # negatives the model can't take are surfaced, not silently dropped
    assert not adapted.negative_constraints or adapted.unsupported_requirements


# --------------------------------------------------------------------------- #
# Routing discipline — no hijacking of unrelated work
# --------------------------------------------------------------------------- #
def test_routing_matches_cinematic_intents():
    for text in [
        "write a text-to-video prompt",
        "storyboard this scene",
        "brand film creative direction",
        "image-to-video of this photo",
    ]:
        assert route_request(text).matched, text


def test_routing_ignores_unrelated_requests():
    for text in [
        "refactor this python function",
        "design a logo for my coffee brand",
        "write a blog post about coffee",
        "fix the failing unit test",
    ]:
        assert not route_request(text).matched, text


# --------------------------------------------------------------------------- #
# Camera discipline
# --------------------------------------------------------------------------- #
def test_static_is_default_and_moves_require_full_fields():
    static = ShotIR(id="c1", character_state={"subject": "x"})
    assert static.camera.move is CameraMove.static
    assert validate_camera(static) == []

    underspecified = ShotIR(id="c2", camera=CameraState(move=CameraMove.dolly))
    problems = validate_camera(underspecified)
    assert problems and "missing required fields" in problems[0]


def test_scene_path_collision_detected():
    shot = ShotIR(
        id="c3",
        camera=CameraState(
            move=CameraMove.dolly,
            motivation="follow",
            start_position="A",
            path="A->B",
            speed_curve="ease",
            end_position="B",
            focus_behavior="hold",
        ),
        set={"scene": {"obstacles": ["column"], "camera_path": ["A", "column", "B"]}},
    )
    conflicts = scene_path_conflicts(shot)
    assert any("obstacle" in c for c in conflicts)


# --------------------------------------------------------------------------- #
# Evaluator + bounded repair
# --------------------------------------------------------------------------- #
def test_repair_is_bounded_and_local():
    assert MAX_REPAIR_CYCLES == 3
    shot = ShotIR(id="r1", camera=CameraState(move=CameraMove.crane))  # invalid + no identity
    fixed, log = repair_shot(shot)
    assert log                                   # repairs applied
    assert not fixed.camera.is_moving            # camera simplified
    assert fixed.identity_refs                   # identity strengthened
    assert evaluate_shot(fixed).passed


def test_physics_is_causal():
    event = PhysicsEvent(trigger="cup tips", primary_consequence="coffee spills")
    shot = ShotIR(id="ph", character_state={"subject": "x"}, physics=[event])
    result = evaluate_shot(shot)
    physics = next(f for f in result.findings if f.dimension.value == "physics")
    assert physics.passed


# --------------------------------------------------------------------------- #
# Firewall — capability never claims generation authority
# --------------------------------------------------------------------------- #
def test_capability_never_generates_assets():
    result = run_pipeline(
        CinematicRequest(text="text to video of a sunrise", mode=InputMode.video_package)
    )
    assert result.generation_firewall == "PROMPT_PACKAGE_READY"
    manifest = run_pipeline(CinematicRequest(text="what can you do?")).capability
    assert "never invokes a media provider or writes a generated asset" in manifest["guarantees"]
