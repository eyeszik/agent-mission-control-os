"""Continuity: memory packets and the END_STATE(N) -> START_STATE(N+1) handshake.

Prompts are compiled as *relevant memory packets + local shot delta*, never as
a restatement of the whole project bible. Between consecutive shots the previous
shot's final-frame handshake must satisfy the next shot's entry requirements;
mismatches are surfaced (and can be repaired locally).
"""

from __future__ import annotations

from .schemas import (
    Character,
    FinalFrameHandshake,
    MemoryPacket,
    ProjectIR,
    ShotIR,
    SourceAuthority,
)

_HANDSHAKE_FIELDS = (
    "subject_position",
    "gaze",
    "prop_state",
    "camera_orientation",
    "light_state",
    "motion_state",
)


def character_packet(character: Character) -> MemoryPacket:
    """Immutable identity + wardrobe only — the continuity-critical subset."""

    locked = dict(character.immutable_identity)
    if character.wardrobe:
        locked["wardrobe"] = character.wardrobe
    if character.movement_signature:
        locked["movement_signature"] = character.movement_signature
    return MemoryPacket(
        packet_id=f"character:{character.id}",
        kind="character",
        locked=locked,
        authority=SourceAuthority.established_canon,
    )


def build_packets(project: ProjectIR) -> list[MemoryPacket]:
    packets = list(project.packets)
    known = {p.packet_id for p in packets}
    for character in project.characters:
        packet = character_packet(character)
        if packet.packet_id not in known:
            packets.append(packet)
            known.add(packet.packet_id)
    return packets


def handshake_gaps(previous: ShotIR, nxt: ShotIR) -> list[str]:
    """Fields where the next shot states an entry requirement the previous
    shot's final frame does not satisfy."""

    end = previous.final_frame
    entry = nxt.continuity.entry_requirements
    gaps: list[str] = []
    for field in _HANDSHAKE_FIELDS:
        required = getattr(entry, field)
        if not required:
            continue
        established = getattr(end, field)
        if not established:
            gaps.append(f"{field}: next shot requires '{required}' but previous shot left it unset")
        elif _norm(established) != _norm(required):
            gaps.append(
                f"{field}: next shot requires '{required}' but previous shot ended '{established}'"
            )
    return gaps


def propagate(previous: ShotIR, nxt: ShotIR) -> ShotIR:
    """Inherit the previous shot's final frame as the next shot's entry
    requirements where the next shot has not overridden them."""

    end = previous.final_frame
    entry = nxt.continuity.entry_requirements
    merged = {
        field: getattr(entry, field) or getattr(end, field) for field in _HANDSHAKE_FIELDS
    }
    updated_entry = FinalFrameHandshake(**merged)
    updated_continuity = nxt.continuity.model_copy(
        update={"inherits_from": previous.id, "entry_requirements": updated_entry}
    )
    return nxt.model_copy(update={"continuity": updated_continuity})


def validate_sequence(shots: list[ShotIR]) -> dict[str, list[str]]:
    """Return {shot_id: [gaps]} for every consecutive pair with a mismatch."""

    report: dict[str, list[str]] = {}
    for previous, nxt in zip(shots, shots[1:]):
        gaps = handshake_gaps(previous, nxt)
        if gaps:
            report[nxt.id] = gaps
    return report


def _norm(value: object) -> str:
    return str(value).strip().lower()
