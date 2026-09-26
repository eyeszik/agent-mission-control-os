"""Camera validation, 3D-scene path checks, and attention alignment.

STATIC is the default and camera movement is never added automatically. Every
non-static move must be motivated and fully specified (start, path, speed, end,
focus behaviour). Moving-camera shots are checked against a navigable scene
model for collisions / impossible paths before they are allowed to compile.
"""

from __future__ import annotations

from typing import Any

from .schemas import AttentionVector, CameraState, ShotIR


def validate_camera(shot: ShotIR) -> list[str]:
    """Structural problems with a shot's camera. Empty list == valid."""

    problems: list[str] = []
    camera = shot.camera
    if camera.is_moving:
        missing = camera.missing_move_fields()
        if missing:
            problems.append(
                f"{shot.id}: {camera.move.value} move missing required fields: {', '.join(missing)}"
            )
    return problems


def scene_path_conflicts(shot: ShotIR) -> list[str]:
    """Check a moving-camera shot's path against the shot's 3D scene model.

    The scene model lives in ``shot.set['scene']`` as a light-weight navigable
    description: ``{"obstacles": [...], "camera_path": [...], "actor_paths":
    {name: [...]}}``. A conflict is a camera path node that coincides with a
    declared obstacle or an actor position, which would be an impossible move.
    """

    if not shot.camera.is_moving:
        return []
    scene = shot.set.get("scene") if isinstance(shot.set, dict) else None
    if not isinstance(scene, dict):
        return []

    obstacles = {_norm(o) for o in scene.get("obstacles", []) if o}
    camera_path = [_norm(node) for node in scene.get("camera_path", []) if node]
    conflicts: list[str] = []

    for node in camera_path:
        if node in obstacles:
            conflicts.append(f"{shot.id}: camera path crosses obstacle '{node}'")
    actor_paths: dict[str, Any] = scene.get("actor_paths", {}) or {}
    for actor, path in actor_paths.items():
        actor_nodes = {_norm(n) for n in (path or []) if n}
        collision = sorted(set(camera_path) & actor_nodes)
        for node in collision:
            conflicts.append(f"{shot.id}: camera path collides with actor '{actor}' at '{node}'")
    return conflicts


def attention_alignment(shot: ShotIR) -> list[str]:
    """Warn when camera/focus/light do not reinforce the attention target,
    unless deliberate counterpoint is declared."""

    attention: AttentionVector | None = shot.attention
    if attention is None or attention.deliberate_counterpoint:
        return []

    target = _norm(attention.target)
    if not target:
        return []
    reinforcers = " ".join(
        [
            _norm(shot.primary_action),
            _norm(shot.camera.subject_relation or ""),
            _norm(shot.camera.focus_behavior or ""),
            _norm(_flatten(shot.light)),
        ]
    )
    target_words = {w for w in target.split() if len(w) > 2}
    if target_words and not (target_words & set(reinforcers.split())):
        return [
            f"{shot.id}: attention target '{attention.target}' is not reinforced by "
            "camera, focus, or light (declare deliberate_counterpoint if intended)"
        ]
    return []


def camera_summary(camera: CameraState) -> str:
    if not camera.is_moving:
        return "static camera"
    parts = [f"{camera.move.value.lower()} move"]
    if camera.motivation:
        parts.append(f"motivated by {camera.motivation}")
    if camera.start_position and camera.end_position:
        parts.append(f"from {camera.start_position} to {camera.end_position}")
    if camera.path:
        parts.append(f"along {camera.path}")
    if camera.speed_curve:
        parts.append(f"{camera.speed_curve} speed")
    if camera.focus_behavior:
        parts.append(f"focus {camera.focus_behavior}")
    return ", ".join(parts)


def _flatten(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(str(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(str(v) for v in value)
    return str(value)


def _norm(value: object) -> str:
    return str(value).strip().lower()
