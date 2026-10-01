"""Project OS vocabulary: the closed sets every project-scoped subsystem shares.

PROJECT is the durable unit of state. Runs execute *inside* a project, chats
are interfaces *into* a project, and the filesystem workspace is a
*materialized view* of a project. Everything in this module is a closed,
versioned vocabulary mirrored by ``packages/shared/src/schemas/projectOs.ts``;
``scripts/verify_ontology_parity.py`` fails the build if the two drift.

Nothing here grants authority. N1 still owns artifact types, N2 still owns
artifact lifecycle, N3 still owns who may produce what. The lifecycles below
are for project-level operational objects (content items, publication
attempts, knowledge items) that have no N2 entity of their own.
"""

from __future__ import annotations

from enum import Enum

PROJECT_OS_VERSION = "amc-project-os/v1"
WORKSPACE_SCHEMA_VERSION = "amc-workspace/v2"

# --------------------------------------------------------------------------
# Workspace mirror
# --------------------------------------------------------------------------

# Semantic folder taxonomy of a project workspace mirror. Created lazily: a
# folder exists on disk only once something is materialized into it.
WORKSPACE_FOLDERS: tuple[str, ...] = (
    "00_admin",
    "01_sources",
    "02_research",
    "03_strategy",
    "04_brand",
    "05_product",
    "06_design",
    "07_prompts",
    "08_creative",
    "09_web_app",
    "10_content",
    "11_search",
    "12_social",
    "13_campaigns",
    "14_paid_media",
    "15_crm",
    "16_calendar",
    "17_growth",
    "18_analytics",
    "19_operations",
    "20_exports",
    "21_archive",
)

# Machine materializations under ``<project>/.amc/``. Never transactional
# authority: the relational store is canonical, these are reconstructable.
SYSTEM_FOLDERS: tuple[str, ...] = (
    "runs",
    "events",
    "lineage",
    "manifests",
    "hashes",
    "approvals",
    "receipts",
    "memory",
    "checkpoints",
    "recovery",
    "objects",
)


class ProjectLifecycle(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"


PROJECT_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "ACTIVE": ("PAUSED", "ARCHIVED"),
    "PAUSED": ("ACTIVE", "ARCHIVED"),
    "ARCHIVED": ("ACTIVE",),
}

# --------------------------------------------------------------------------
# Storage authority
# --------------------------------------------------------------------------


class StorageLayer(str, Enum):
    RELATIONAL = "RELATIONAL"  # canonical state: identity, versions, lineage
    OBJECT = "OBJECT"          # large binaries: media, previews, archives
    MIRROR = "MIRROR"          # human-readable workspace, never authority


class StorageBackend(str, Enum):
    LOCAL = "LOCAL"
    R2 = "R2"


class StorageObjectStatus(str, Enum):
    PRESENT = "PRESENT"
    MISSING = "MISSING"
    UNVERIFIED = "UNVERIFIED"


# --------------------------------------------------------------------------
# Project activity stream (conversations are interfaces into projects)
# --------------------------------------------------------------------------


class ActivityType(str, Enum):
    PROJECT_CREATED = "PROJECT_CREATED"
    MESSAGE = "MESSAGE"
    WORK_STARTED = "WORK_STARTED"
    ARTIFACT_CREATED = "ARTIFACT_CREATED"
    ARTIFACT_UPDATED = "ARTIFACT_UPDATED"
    PREVIEW_READY = "PREVIEW_READY"
    VARIANT_READY = "VARIANT_READY"
    QA_BLOCKED = "QA_BLOCKED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    RECOVERING = "RECOVERING"
    COMMENT = "COMMENT"
    EDIT_REQUESTED = "EDIT_REQUESTED"


# --------------------------------------------------------------------------
# Content operations + calendar
# --------------------------------------------------------------------------


class ContentState(str, Enum):
    IDEA = "IDEA"
    PLANNED = "PLANNED"
    IN_PRODUCTION = "IN_PRODUCTION"
    REVIEW = "REVIEW"
    APPROVED = "APPROVED"
    READY = "READY"
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    VERIFIED = "VERIFIED"
    MEASURED = "MEASURED"
    REFRESH_DUE = "REFRESH_DUE"
    ARCHIVED = "ARCHIVED"


CONTENT_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "IDEA": ("PLANNED", "ARCHIVED"),
    "PLANNED": ("IN_PRODUCTION", "ARCHIVED"),
    "IN_PRODUCTION": ("REVIEW", "ARCHIVED"),
    "REVIEW": ("APPROVED", "IN_PRODUCTION", "ARCHIVED"),
    "APPROVED": ("READY", "IN_PRODUCTION", "ARCHIVED"),
    "READY": ("SCHEDULED", "IN_PRODUCTION", "ARCHIVED"),
    "SCHEDULED": ("DUE", "READY", "IN_PRODUCTION"),
    "DUE": ("PUBLISHING", "SCHEDULED", "IN_PRODUCTION"),
    "PUBLISHING": ("PUBLISHED", "SCHEDULED"),
    "PUBLISHED": ("VERIFIED",),
    "VERIFIED": ("MEASURED", "REFRESH_DUE", "ARCHIVED"),
    "MEASURED": ("REFRESH_DUE", "ARCHIVED"),
    "REFRESH_DUE": ("IN_PRODUCTION", "ARCHIVED"),
    "ARCHIVED": (),
}

# States that may only be entered while an approval bound to the item's exact
# current version exists. Editing an approved item returns it to production.
APPROVAL_BOUND_CONTENT_STATES: tuple[str, ...] = (
    "APPROVED",
    "READY",
    "SCHEDULED",
    "DUE",
    "PUBLISHING",
)

CALENDAR_HORIZON_DAYS: tuple[int, ...] = (14, 30, 90, 182, 365)


class ContentKind(str, Enum):
    ARTICLE = "article"
    EMAIL = "email"
    NEWSLETTER = "newsletter"
    CAROUSEL = "carousel"
    SOCIAL_POST = "social_post"
    THREAD = "thread"
    VIDEO_SCRIPT = "video_script"
    SHORT_VIDEO = "short_video"
    REEL = "reel"
    STORY = "story"
    PODCAST_EPISODE = "podcast_episode"
    FAQ = "faq"
    LANDING_SECTION = "landing_section"
    AI_SEARCH_ANSWER = "ai_search_answer"
    PAID_CREATIVE = "paid_creative"


# Every content kind resolves to exactly one N1 artifact type + owner. Content
# kinds are subtypes, never new ArtifactTypes.
CONTENT_KIND_ARTIFACT: dict[str, tuple[str, str]] = {
    "article": ("copy_variant", "copy"),
    "email": ("copy_variant", "copy"),
    "newsletter": ("copy_variant", "copy"),
    "carousel": ("creative_concept", "creative"),
    "social_post": ("copy_variant", "copy"),
    "thread": ("copy_variant", "copy"),
    "video_script": ("copy_variant", "copy"),
    "short_video": ("media_asset", "creative"),
    "reel": ("media_asset", "creative"),
    "story": ("creative_concept", "creative"),
    "podcast_episode": ("media_asset", "creative"),
    "faq": ("copy_variant", "copy"),
    "landing_section": ("copy_variant", "copy"),
    "ai_search_answer": ("copy_variant", "copy"),
    "paid_creative": ("creative_concept", "creative"),
}


class ScheduledJobKind(str, Enum):
    PUBLISH = "PUBLISH"
    REFRESH = "REFRESH"
    LIFECYCLE = "LIFECYCLE"


class ScheduledJobStatus(str, Enum):
    PENDING = "PENDING"
    BLOCKED = "BLOCKED"
    ENQUEUED = "ENQUEUED"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# --------------------------------------------------------------------------
# Publishing
# --------------------------------------------------------------------------


class PublicationState(str, Enum):
    SPEC = "SPEC"
    VALIDATED = "VALIDATED"
    AUTHORIZED = "AUTHORIZED"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    READBACK = "READBACK"
    RECONCILED = "RECONCILED"
    VERIFIED = "VERIFIED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    UNCERTAIN = "UNCERTAIN"


PUBLICATION_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "SPEC": ("VALIDATED", "BLOCKED", "FAILED"),
    "VALIDATED": ("AUTHORIZED", "BLOCKED"),
    "AUTHORIZED": ("APPROVED", "BLOCKED"),
    "APPROVED": ("EXECUTING", "BLOCKED"),
    "EXECUTING": ("READBACK", "FAILED", "UNCERTAIN"),
    "READBACK": ("RECONCILED", "UNCERTAIN", "FAILED"),
    "UNCERTAIN": ("RECONCILED", "FAILED"),
    "RECONCILED": ("VERIFIED", "FAILED"),
    "VERIFIED": (),
    "BLOCKED": (),
    "FAILED": (),
}


class ProviderMode(str, Enum):
    DISABLED = "DISABLED"
    DRY_RUN = "DRY_RUN"
    LIVE = "LIVE"


# --------------------------------------------------------------------------
# Memory
# --------------------------------------------------------------------------


class MemoryScope(str, Enum):
    M0_AGENCY = "M0_AGENCY"
    M1_BRAND_CANON = "M1_BRAND_CANON"
    M2_PROJECT = "M2_PROJECT"
    M3_CONVERSATION = "M3_CONVERSATION"
    M4_EVIDENCE = "M4_EVIDENCE"
    M5_PERFORMANCE = "M5_PERFORMANCE"
    M6_LEARNING = "M6_LEARNING"


class MemoryAuthority(str, Enum):
    BRAND_CANON = "BRAND_CANON"
    APPROVED_PROJECT_DECISION = "APPROVED_PROJECT_DECISION"
    VERIFIED_EVIDENCE = "VERIFIED_EVIDENCE"
    WORKING_CONTEXT = "WORKING_CONTEXT"
    LEARNING_SIGNAL = "LEARNING_SIGNAL"


# Highest first. A lower class may never silently override a higher one.
MEMORY_AUTHORITY_ORDER: tuple[str, ...] = (
    "BRAND_CANON",
    "APPROVED_PROJECT_DECISION",
    "VERIFIED_EVIDENCE",
    "WORKING_CONTEXT",
    "LEARNING_SIGNAL",
)

# Which authority classes a record in each scope may legitimately claim.
MEMORY_SCOPE_AUTHORITIES: dict[str, tuple[str, ...]] = {
    "M0_AGENCY": ("WORKING_CONTEXT",),
    "M1_BRAND_CANON": ("BRAND_CANON",),
    "M2_PROJECT": ("APPROVED_PROJECT_DECISION", "WORKING_CONTEXT"),
    "M3_CONVERSATION": ("WORKING_CONTEXT",),
    "M4_EVIDENCE": ("VERIFIED_EVIDENCE", "WORKING_CONTEXT"),
    "M5_PERFORMANCE": ("VERIFIED_EVIDENCE", "WORKING_CONTEXT"),
    "M6_LEARNING": ("LEARNING_SIGNAL",),
}

# Scopes that never leave their project/brand in portfolio-level reads.
PRIVATE_MEMORY_SCOPES: tuple[str, ...] = (
    "M1_BRAND_CANON",
    "M2_PROJECT",
    "M3_CONVERSATION",
    "M4_EVIDENCE",
    "M5_PERFORMANCE",
)


class MemoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    INVALIDATED = "INVALIDATED"
    QUARANTINED = "QUARANTINED"


# --------------------------------------------------------------------------
# KnowledgeOps
# --------------------------------------------------------------------------

KNOWLEDGE_STAGES: tuple[str, ...] = (
    "DISCOVER",
    "FETCH",
    "SANITIZE",
    "INJECTION_SCAN",
    "RIGHTS_CLASSIFY",
    "CLAIM_EXTRACT",
    "DATE_FRESHNESS",
    "DEDUPE",
    "TRIANGULATE",
    "CONTRADICTION_CHECK",
    "EVIDENCE_SCORE",
    "CAPSULE",
    "REVIEW",
    "PROMOTE",
)


class RightsClass(str, Enum):
    OPEN_LICENSE = "OPEN_LICENSE"
    LICENSED = "LICENSED"
    SUMMARY_ONLY = "SUMMARY_ONLY"
    PROPRIETARY_NO_COPY = "PROPRIETARY_NO_COPY"
    UNKNOWN = "UNKNOWN"


class KnowledgeStatus(str, Enum):
    IN_PIPELINE = "IN_PIPELINE"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    PROMOTED = "PROMOTED"
    REJECTED = "REJECTED"


# --------------------------------------------------------------------------
# Cost x quality routing
# --------------------------------------------------------------------------

# Routing priority, cheapest-to-justify first. "premium_final" is reached only
# when every cheaper tier is unavailable or failed evaluation.
ROUTING_TIERS: tuple[str, ...] = (
    "reuse_approved_asset",
    "deterministic_transform",
    "local_free_execution",
    "cheap_draft",
    "evaluate",
    "premium_final",
    "post_process",
)

UNKNOWN = "UNKNOWN"

# --------------------------------------------------------------------------
# Self-improvement promotion flow (wraps the compiled-agency LearningLedger)
# --------------------------------------------------------------------------

LEARNING_PROMOTION_STAGES: tuple[str, ...] = (
    "SIGNAL",
    "QUARANTINE",
    "DATASET",
    "BASELINE",
    "SHADOW_TEST",
    "DIGITAL_TWIN",
    "REGRESSION_COMPARISON",
    "GOVERNANCE_PROPOSAL",
    "HUMAN_APPROVAL",
    "VERSIONED_PROMOTION",
    "MONITOR",
    "ROLLBACK",
)

# --------------------------------------------------------------------------
# Implementation status labels used across docs, APIs and the UI
# --------------------------------------------------------------------------


class CapabilityStatus(str, Enum):
    IMPLEMENTED = "IMPLEMENTED"
    IMPLEMENTED_FAIL_CLOSED = "IMPLEMENTED_FAIL_CLOSED"
    DRY_RUN_ONLY = "DRY_RUN_ONLY"
    LOCAL_ONLY = "LOCAL_ONLY"
    EXTERNAL_ACTIVATION_REQUIRED = "EXTERNAL_ACTIVATION_REQUIRED"
    NOT_AVAILABLE = "NOT_AVAILABLE"


def enum_values(enum_cls: type[Enum]) -> tuple[str, ...]:
    return tuple(member.value for member in enum_cls)


def can_transition(transitions: dict[str, tuple[str, ...]], current: str, target: str) -> bool:
    return target in transitions.get(current, ())


def authority_rank(authority: str) -> int:
    """Higher number = higher authority. Unknown authority ranks lowest."""
    try:
        return len(MEMORY_AUTHORITY_ORDER) - MEMORY_AUTHORITY_ORDER.index(authority)
    except ValueError:
        return 0
