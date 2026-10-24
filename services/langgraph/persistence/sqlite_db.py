import os
import sqlite3

DB_PATH = os.environ.get("AMC_DB_PATH", "amc_local.db")

_MIGRATIONS = [
    (1, """CREATE TABLE IF NOT EXISTS idempotency_keys (key TEXT PRIMARY KEY, result TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);"""),
    (2, """
        CREATE TABLE IF NOT EXISTS idempotency_records (
            scope TEXT NOT NULL, key TEXT NOT NULL, request_hash TEXT NOT NULL,
            status TEXT NOT NULL, result TEXT, error TEXT, attempt_count INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT NOT NULL,
            PRIMARY KEY (scope, key)
        );
        CREATE INDEX IF NOT EXISTS idx_idempotency_expires_at ON idempotency_records (expires_at);
    """),
    (3, """
        CREATE TABLE IF NOT EXISTS run_events_v2 (
            event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL,
            sequence INTEGER NOT NULL, schema_version TEXT NOT NULL, event_type TEXT NOT NULL, node_id TEXT,
            observed_at TEXT NOT NULL, started_at TEXT, completed_at TEXT, persisted_at TEXT NOT NULL,
            checkpoint_ref TEXT, safe_payload TEXT NOT NULL, redactions_applied TEXT NOT NULL,
            UNIQUE (run_id, sequence)
        );
        CREATE INDEX IF NOT EXISTS idx_run_events_v2_cursor ON run_events_v2 (run_id, sequence);
        CREATE INDEX IF NOT EXISTS idx_run_events_v2_tenant ON run_events_v2 (tenant_id, project_id, run_id);
    """),
    (4, """
        CREATE TABLE IF NOT EXISTS analytics_events (
            event_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL, run_id TEXT,
            event_name TEXT NOT NULL, source TEXT NOT NULL, occurred_at TEXT NOT NULL,
            properties TEXT NOT NULL, schema_version TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_analytics_tenant_time ON analytics_events (tenant_id, project_id, occurred_at DESC);
        CREATE TABLE IF NOT EXISTS publication_jobs (
            job_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL,
            provider TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL, idempotency_key TEXT NOT NULL,
            payload TEXT NOT NULL, external_id TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE (provider, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS spend_authorizations (
            authorization_id TEXT PRIMARY KEY, run_id TEXT, tenant_id TEXT NOT NULL, project_id TEXT NOT NULL,
            provider TEXT NOT NULL, amount_minor INTEGER NOT NULL, currency TEXT NOT NULL, status TEXT NOT NULL,
            requested_by TEXT NOT NULL, approved_by TEXT, reason TEXT NOT NULL, external_id TEXT,
            created_at TEXT NOT NULL, decided_at TEXT, executed_at TEXT
        );
    """),
    (5, """
        CREATE TABLE IF NOT EXISTS engagements (
            engagement_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            objective TEXT NOT NULL,
            desired_outcome TEXT NOT NULL,
            status TEXT NOT NULL,
            constraints TEXT NOT NULL,
            permissions TEXT NOT NULL,
            metadata TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_engagements_tenant_project ON engagements (tenant_id, project_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_engagements_status ON engagements (status, updated_at DESC);

        CREATE TABLE IF NOT EXISTS workstreams (
            workstream_id TEXT PRIMARY KEY,
            engagement_id TEXT NOT NULL REFERENCES engagements(engagement_id) ON DELETE CASCADE,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            department TEXT NOT NULL,
            objective TEXT NOT NULL,
            status TEXT NOT NULL,
            dependencies TEXT NOT NULL,
            acceptance_criteria TEXT NOT NULL,
            permissions TEXT NOT NULL,
            metadata TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_workstreams_engagement ON workstreams (engagement_id, status, created_at);

        CREATE TABLE IF NOT EXISTS agency_evidence (
            evidence_id TEXT PRIMARY KEY,
            engagement_id TEXT NOT NULL REFERENCES engagements(engagement_id) ON DELETE CASCADE,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            evidence_type TEXT NOT NULL,
            source_ref TEXT,
            claim TEXT NOT NULL,
            epistemic_status TEXT NOT NULL,
            confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
            collected_at TEXT NOT NULL,
            freshness_seconds INTEGER CHECK (freshness_seconds IS NULL OR freshness_seconds >= 0),
            payload TEXT NOT NULL,
            metadata TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_agency_evidence_engagement ON agency_evidence (engagement_id, epistemic_status, collected_at DESC);

        CREATE TABLE IF NOT EXISTS agency_decisions (
            decision_id TEXT PRIMARY KEY,
            engagement_id TEXT NOT NULL REFERENCES engagements(engagement_id) ON DELETE CASCADE,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            question TEXT NOT NULL,
            alternatives TEXT NOT NULL,
            selected_option TEXT NOT NULL,
            evidence_ids TEXT NOT NULL,
            assumptions TEXT NOT NULL,
            affected_artifact_ids TEXT NOT NULL,
            confidence TEXT NOT NULL,
            status TEXT NOT NULL,
            approver TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_agency_decisions_engagement ON agency_decisions (engagement_id, status, created_at DESC);

        CREATE TABLE IF NOT EXISTS agency_artifacts (
            artifact_id TEXT PRIMARY KEY,
            engagement_id TEXT NOT NULL REFERENCES engagements(engagement_id) ON DELETE CASCADE,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            workstream_id TEXT REFERENCES workstreams(workstream_id) ON DELETE SET NULL,
            artifact_type TEXT NOT NULL,
            subtype TEXT,
            owner_department TEXT NOT NULL,
            version INTEGER NOT NULL CHECK (version > 0),
            status TEXT NOT NULL,
            content_location TEXT,
            content_hash TEXT,
            semantic_fingerprint TEXT,
            assumptions TEXT NOT NULL,
            validation TEXT NOT NULL,
            approval TEXT NOT NULL,
            metadata TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_agency_artifacts_engagement ON agency_artifacts (engagement_id, status, artifact_type);
        CREATE INDEX IF NOT EXISTS idx_agency_artifacts_workstream ON agency_artifacts (workstream_id) WHERE workstream_id IS NOT NULL;

        CREATE TABLE IF NOT EXISTS artifact_dependencies (
            artifact_id TEXT NOT NULL REFERENCES agency_artifacts(artifact_id) ON DELETE CASCADE,
            depends_on_artifact_id TEXT NOT NULL REFERENCES agency_artifacts(artifact_id) ON DELETE CASCADE,
            relationship TEXT NOT NULL CHECK (relationship IN ('hard', 'soft')),
            created_at TEXT NOT NULL,
            PRIMARY KEY (artifact_id, depends_on_artifact_id),
            CHECK (artifact_id <> depends_on_artifact_id)
        );
        CREATE INDEX IF NOT EXISTS idx_artifact_dependencies_upstream ON artifact_dependencies (depends_on_artifact_id, artifact_id);
    """),
    (6, """
        CREATE TABLE IF NOT EXISTS reliability_meta(
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reliability_bindings(
            project_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            payload TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reliability_policy_decisions(
            decision_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_reliability_policy_project
          ON reliability_policy_decisions(tenant_id, project_id);

        CREATE TABLE IF NOT EXISTS reliability_idempotency(
            idempotency_key TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_reliability_idem_project
          ON reliability_idempotency(tenant_id, project_id);

        CREATE TABLE IF NOT EXISTS reliability_outbox(
            message_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            status TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_reliability_outbox_pending
          ON reliability_outbox(tenant_id, project_id, status);

        CREATE TABLE IF NOT EXISTS reliability_audit_chain(
            seq INTEGER PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            checkpoint_hash TEXT NOT NULL UNIQUE,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_reliability_audit_project
          ON reliability_audit_chain(tenant_id, project_id, seq);

        CREATE TABLE IF NOT EXISTS reliability_recovery(
            recovery_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            status TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_reliability_recovery_open
          ON reliability_recovery(tenant_id, project_id, status);

        INSERT OR REPLACE INTO reliability_meta(key,value)
        VALUES('schema_version','1');
    """),
    (7, """
        CREATE TABLE IF NOT EXISTS approvals (
            approval_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            confidence REAL,
            status TEXT DEFAULT 'pending',
            reviewer TEXT,
            decision TEXT,
            created_at TEXT NOT NULL,
            decided_at TEXT,
            subject_type TEXT,
            subject_ref TEXT,
            subject_version_ref TEXT,
            subject_hash TEXT,
            authority_ref TEXT,
            policy_version TEXT,
            stale_reason TEXT,
            staled_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_approvals_tenant_status ON approvals (tenant_id, status);
        CREATE INDEX IF NOT EXISTS idx_approvals_run_created ON approvals (run_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS tenant_project_bindings (
            project_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            status TEXT NOT NULL,
            binding_hash TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            revoked_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_tenant_project_bindings_tenant
          ON tenant_project_bindings(tenant_id, status);

        CREATE TABLE IF NOT EXISTS policy_decision_records (
            decision_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            subject_ref TEXT NOT NULL,
            action TEXT NOT NULL,
            target TEXT NOT NULL,
            policy_version TEXT NOT NULL,
            input_hash TEXT NOT NULL,
            effect TEXT NOT NULL,
            required_authority_refs TEXT NOT NULL,
            evidence_refs TEXT NOT NULL,
            decision_hash TEXT NOT NULL,
            payload TEXT NOT NULL,
            decided_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_policy_decisions_project
          ON policy_decision_records(tenant_id, project_id, decided_at DESC);

        CREATE TABLE IF NOT EXISTS trust_idempotency_records (
            idempotency_key TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            operation_id TEXT NOT NULL,
            request_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            result_ref TEXT,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_trust_idempotency_project
          ON trust_idempotency_records(tenant_id, project_id, updated_at DESC);

        CREATE TABLE IF NOT EXISTS outbox_messages (
            message_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            topic TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            payload_ref TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL,
            claimed_by TEXT,
            next_attempt_at TEXT,
            delivered_at TEXT,
            last_error TEXT,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_outbox_messages_project
          ON outbox_messages(tenant_id, project_id, status, created_at);

        CREATE TABLE IF NOT EXISTS audit_checkpoints (
            seq INTEGER PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            object_ref TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            previous_hash TEXT NOT NULL,
            checkpoint_hash TEXT NOT NULL UNIQUE,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_audit_checkpoints_project
          ON audit_checkpoints(tenant_id, project_id, seq);

        CREATE TABLE IF NOT EXISTS recovery_cases (
            recovery_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            operation_id TEXT NOT NULL,
            reason TEXT NOT NULL,
            execution_ref TEXT,
            observation_ref TEXT,
            idempotency_key TEXT,
            status TEXT NOT NULL,
            evidence_refs TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            resolved_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_recovery_cases_project
          ON recovery_cases(tenant_id, project_id, status, created_at DESC);
    """),
    (8, """
        CREATE TABLE IF NOT EXISTS execution_receipts (
            operation_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            work_order_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_execution_receipts_run
          ON execution_receipts(run_id, started_at);

        CREATE TABLE IF NOT EXISTS observation_receipts (
            operation_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            matches INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_observation_receipts_run
          ON observation_receipts(run_id, observed_at);

        CREATE TABLE IF NOT EXISTS dispatch_permits (
            permit_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            work_order_id TEXT NOT NULL,
            payload TEXT NOT NULL,
            issued_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_dispatch_permits_run
          ON dispatch_permits(run_id, issued_at);

        CREATE TABLE IF NOT EXISTS failure_fingerprints (
            fingerprint TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            operation_id TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_failure_fingerprints_run
          ON failure_fingerprints(run_id, operation_id);

        CREATE TABLE IF NOT EXISTS completion_evaluations (
            evaluation_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            terminal_candidate TEXT NOT NULL,
            proof_coverage REAL NOT NULL,
            confidence REAL NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_completion_evaluations_run
          ON completion_evaluations(run_id, created_at DESC);
    """),
    (9, """
        CREATE TABLE IF NOT EXISTS lineage_remediation_queue (
            remediation_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            approval_id TEXT,
            artifact_id TEXT NOT NULL,
            artifact_version_ref TEXT NOT NULL,
            changed_artifact_id TEXT NOT NULL,
            changed_version_ref TEXT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('OPEN', 'REGENERATED', 'RETRIED', 'RESOLVED')),
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            resolved_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_lineage_remediation_project
          ON lineage_remediation_queue(tenant_id, project_id, status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_lineage_remediation_run
          ON lineage_remediation_queue(run_id, status, created_at DESC);
    """),
    (10, """
        CREATE TABLE IF NOT EXISTS invalidation_obligations (
            obligation_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            artifact_branch TEXT NOT NULL,
            node_id TEXT NOT NULL,
            event_class TEXT NOT NULL CHECK (event_class IN (
                'SPEC_CHANGE',
                'MODEL_PARAM_CHANGE',
                'TOOL_RESULT_CHANGE',
                'SCHEMA_CHANGE',
                'ACL_SECRET_CHANGE',
                'MEMORY_WRITE',
                'CLOCK_WINDOW_ADVANCE',
                'HOOK_GAP'
            )),
            state TEXT NOT NULL CHECK (state IN (
                'OPEN',
                'DISCHARGED_RECOMPUTE',
                'DISCHARGED_CUTOFF',
                'HOOK_GAP'
            )),
            demanded INTEGER NOT NULL CHECK (demanded IN (0, 1)),
            cause_k TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            discharged_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_invalidation_obligations_project
          ON invalidation_obligations(tenant_id, project_id, state, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_invalidation_obligations_branch
          ON invalidation_obligations(run_id, artifact_branch, event_class, updated_at DESC);
    """),
    (11, """
        CREATE TABLE IF NOT EXISTS tenants (
            tenant_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_projects_tenant ON projects(tenant_id);
    """),
    (12, """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            pipeline TEXT NOT NULL,
            status TEXT NOT NULL,
            metadata TEXT,
            result TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_runs_tenant_project ON runs (tenant_id, project_id);
        CREATE INDEX IF NOT EXISTS idx_runs_status_updated ON runs (status, updated_at DESC);
    """),
    (13, """
        -- Project OS: PROJECT is the durable unit of state. Mirrors
        -- supabase/migrations/20261001_amc_project_os_v1.sql.
        CREATE TABLE IF NOT EXISTS project_workspaces (
            project_id TEXT PRIMARY KEY REFERENCES projects(project_id) ON DELETE CASCADE,
            tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            slug TEXT NOT NULL,
            display_name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            lifecycle_state TEXT NOT NULL CHECK (lifecycle_state IN ('ACTIVE','PAUSED','ARCHIVED')),
            brand_id TEXT,
            brand_name TEXT,
            workspace_schema_version TEXT NOT NULL,
            manifest TEXT NOT NULL,
            manifest_hash TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (tenant_id, slug)
        );
        CREATE TABLE IF NOT EXISTS project_events (
            event_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL CHECK (sequence > 0),
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL,
            thread_id TEXT,
            subject_ref TEXT,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (project_id, sequence)
        );
        CREATE TABLE IF NOT EXISTS storage_objects (
            object_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
            backend TEXT NOT NULL CHECK (backend IN ('LOCAL','R2')),
            storage_uri TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
            mime_type TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('PRESENT','MISSING','UNVERIFIED')),
            created_at TEXT NOT NULL,
            verified_at TEXT,
            UNIQUE (project_id, backend, content_hash)
        );
        CREATE TABLE IF NOT EXISTS artifact_versions (
            artifact_id TEXT NOT NULL REFERENCES agency_artifacts(artifact_id) ON DELETE CASCADE,
            version INTEGER NOT NULL CHECK (version > 0),
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            content_hash TEXT,
            content_location TEXT,
            semantic_fingerprint TEXT,
            metadata TEXT NOT NULL,
            change_kind TEXT NOT NULL CHECK (change_kind IN ('create','revise','restore','replace_master')),
            restored_from_version INTEGER,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (artifact_id, version)
        );
        CREATE TABLE IF NOT EXISTS asset_rights (
            rights_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
            artifact_id TEXT NOT NULL REFERENCES agency_artifacts(artifact_id) ON DELETE CASCADE,
            license TEXT NOT NULL,
            territory TEXT NOT NULL,
            usage_scope TEXT NOT NULL,
            attribution TEXT,
            source_ref TEXT,
            expires_at TEXT,
            status TEXT NOT NULL CHECK (status IN ('active','expired','revoked')),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conversation_threads (
            thread_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
            campaign_id TEXT,
            title TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('open','archived')),
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conversation_messages (
            message_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL REFERENCES conversation_threads(thread_id) ON DELETE CASCADE,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            author TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('user','agent','system')),
            activity_type TEXT NOT NULL,
            body TEXT NOT NULL,
            artifact_refs TEXT NOT NULL,
            event_id TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS artifact_comments (
            comment_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            artifact_id TEXT NOT NULL REFERENCES agency_artifacts(artifact_id) ON DELETE CASCADE,
            version_ref TEXT NOT NULL,
            author TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS artifact_edit_requests (
            request_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            artifact_id TEXT NOT NULL REFERENCES agency_artifacts(artifact_id) ON DELETE CASCADE,
            base_version_ref TEXT NOT NULL,
            instruction TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('open','applied','rejected','stale')),
            requested_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            resolved_at TEXT
        );
        CREATE TABLE IF NOT EXISTS content_atoms (
            atom_id TEXT NOT NULL,
            version INTEGER NOT NULL CHECK (version > 0),
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
            campaign_id TEXT,
            title TEXT NOT NULL,
            claims TEXT NOT NULL,
            source_refs TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (atom_id, version)
        );
        CREATE TABLE IF NOT EXISTS content_items (
            content_item_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
            campaign_id TEXT,
            atom_id TEXT,
            atom_version INTEGER,
            artifact_id TEXT,
            kind TEXT NOT NULL,
            channel TEXT NOT NULL,
            title TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('IDEA','PLANNED','IN_PRODUCTION','REVIEW','APPROVED','READY','SCHEDULED','DUE','PUBLISHING','PUBLISHED','VERIFIED','MEASURED','REFRESH_DUE','ARCHIVED')),
            version INTEGER NOT NULL CHECK (version > 0),
            body TEXT NOT NULL,
            claim_refs TEXT NOT NULL,
            rights_ref TEXT,
            approved_version INTEGER,
            approval_ref TEXT,
            evidence_fresh_until TEXT,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS calendars (
            calendar_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            timezone TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS schedule_slots (
            slot_id TEXT PRIMARY KEY,
            calendar_id TEXT NOT NULL REFERENCES calendars(calendar_id) ON DELETE CASCADE,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            content_item_id TEXT REFERENCES content_items(content_item_id) ON DELETE SET NULL,
            channel TEXT NOT NULL,
            scheduled_for TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('open','filled','released','cancelled')),
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scheduled_jobs (
            job_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
            slot_id TEXT,
            content_item_id TEXT,
            job_kind TEXT NOT NULL CHECK (job_kind IN ('PUBLISH','REFRESH','LIFECYCLE')),
            due_at TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('PENDING','BLOCKED','ENQUEUED','DELIVERED','FAILED','CANCELLED')),
            idempotency_key TEXT NOT NULL UNIQUE,
            outbox_message_id TEXT,
            block_reasons TEXT NOT NULL,
            payload TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS publication_attempts (
            attempt_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
            job_id TEXT,
            content_item_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            mode TEXT NOT NULL CHECK (mode IN ('DISABLED','DRY_RUN','LIVE')),
            state TEXT NOT NULL CHECK (state IN ('SPEC','VALIDATED','AUTHORIZED','APPROVED','EXECUTING','READBACK','RECONCILED','VERIFIED','BLOCKED','FAILED','UNCERTAIN')),
            request_hash TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            external_ref TEXT,
            readback TEXT NOT NULL,
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (provider, idempotency_key)
        );
        CREATE TABLE IF NOT EXISTS publication_receipts (
            receipt_id TEXT PRIMARY KEY,
            attempt_id TEXT NOT NULL REFERENCES publication_attempts(attempt_id) ON DELETE CASCADE,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('dispatch_permit','execution','observation')),
            payload TEXT NOT NULL,
            receipt_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS memory_records (
            memory_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            project_id TEXT REFERENCES projects(project_id) ON DELETE CASCADE,
            thread_id TEXT,
            scope TEXT NOT NULL CHECK (scope IN ('M0_AGENCY','M1_BRAND_CANON','M2_PROJECT','M3_CONVERSATION','M4_EVIDENCE','M5_PERFORMANCE','M6_LEARNING')),
            authority TEXT NOT NULL CHECK (authority IN ('BRAND_CANON','APPROVED_PROJECT_DECISION','VERIFIED_EVIDENCE','WORKING_CONTEXT','LEARNING_SIGNAL')),
            subject_key TEXT NOT NULL,
            body TEXT NOT NULL,
            source_refs TEXT NOT NULL,
            fresh_until TEXT,
            status TEXT NOT NULL CHECK (status IN ('ACTIVE','SUPERSEDED','INVALIDATED','QUARANTINED')),
            supersedes TEXT,
            content_hash TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS knowledge_items (
            item_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            project_id TEXT REFERENCES projects(project_id) ON DELETE CASCADE,
            domain TEXT NOT NULL,
            source_uri TEXT NOT NULL,
            rights_class TEXT NOT NULL,
            stage TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('IN_PIPELINE','AWAITING_REVIEW','PROMOTED','REJECTED')),
            claims TEXT NOT NULL,
            evidence_score REAL NOT NULL,
            rejection_reasons TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            fetched_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS prompt_records (
            prompt_id TEXT NOT NULL,
            version INTEGER NOT NULL CHECK (version > 0),
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
            artifact_target TEXT,
            department TEXT NOT NULL,
            family TEXT,
            campaign_id TEXT,
            status TEXT NOT NULL,
            prompt_hash TEXT NOT NULL,
            body TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (prompt_id, version)
        );
        CREATE TABLE IF NOT EXISTS provider_profiles (
            profile_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            task TEXT NOT NULL,
            mode TEXT NOT NULL CHECK (mode IN ('DISABLED','DRY_RUN','LIVE')),
            body TEXT NOT NULL,
            last_verified_at TEXT,
            created_at TEXT NOT NULL,
            UNIQUE (tenant_id, provider, model, task)
        );
        CREATE TABLE IF NOT EXISTS growth_experiments (
            experiment_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
            hypothesis TEXT NOT NULL,
            target_metric TEXT NOT NULL,
            segment TEXT NOT NULL,
            intervention TEXT NOT NULL,
            asset_refs TEXT NOT NULL,
            start_at TEXT,
            end_at TEXT,
            sample_requirement INTEGER NOT NULL CHECK (sample_requirement > 0),
            status TEXT NOT NULL CHECK (status IN ('DRAFT','RUNNING','CONCLUDED','ABANDONED')),
            observed_result TEXT,
            decision TEXT,
            learning_signal_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS learning_signals (
            signal_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            seq INTEGER NOT NULL CHECK (seq > 0),
            status TEXT NOT NULL,
            payload TEXT NOT NULL,
            prev_hash TEXT NOT NULL,
            hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (tenant_id, seq)
        );
        CREATE TABLE IF NOT EXISTS learning_promotions (
            promotion_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            signal_id TEXT NOT NULL REFERENCES learning_signals(signal_id) ON DELETE CASCADE,
            stage TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('IN_PROGRESS','AWAITING_HUMAN_APPROVAL','PROMOTED','ROLLED_BACK','REJECTED')),
            evidence TEXT NOT NULL,
            approved_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_project_workspaces_tenant ON project_workspaces(tenant_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_project_events_cursor ON project_events(project_id, sequence);
        CREATE INDEX IF NOT EXISTS idx_storage_objects_project ON storage_objects(project_id, status);
        CREATE INDEX IF NOT EXISTS idx_artifact_versions_project ON artifact_versions(project_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_asset_rights_artifact ON asset_rights(artifact_id, status);
        CREATE INDEX IF NOT EXISTS idx_asset_rights_expiry ON asset_rights(project_id, expires_at);
        CREATE INDEX IF NOT EXISTS idx_threads_project ON conversation_threads(project_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_messages_thread ON conversation_messages(thread_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_comments_artifact ON artifact_comments(artifact_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_edit_requests_artifact ON artifact_edit_requests(artifact_id, status);
        CREATE INDEX IF NOT EXISTS idx_content_atoms_project ON content_atoms(project_id, atom_id);
        CREATE INDEX IF NOT EXISTS idx_content_items_project ON content_items(project_id, state, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_calendars_project ON calendars(project_id);
        CREATE INDEX IF NOT EXISTS idx_slots_calendar ON schedule_slots(calendar_id, scheduled_for);
        CREATE INDEX IF NOT EXISTS idx_jobs_due ON scheduled_jobs(status, due_at);
        CREATE INDEX IF NOT EXISTS idx_jobs_project ON scheduled_jobs(project_id, due_at);
        CREATE INDEX IF NOT EXISTS idx_publication_attempts_item ON publication_attempts(content_item_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_publication_receipts_attempt ON publication_receipts(attempt_id);
        CREATE INDEX IF NOT EXISTS idx_memory_scope ON memory_records(tenant_id, project_id, scope, subject_key, status);
        CREATE INDEX IF NOT EXISTS idx_knowledge_tenant ON knowledge_items(tenant_id, project_id, status);
        CREATE INDEX IF NOT EXISTS idx_knowledge_hash ON knowledge_items(tenant_id, content_hash);
        CREATE INDEX IF NOT EXISTS idx_prompt_records_project ON prompt_records(project_id, prompt_id);
        CREATE INDEX IF NOT EXISTS idx_growth_experiments_project ON growth_experiments(project_id, status);
        CREATE INDEX IF NOT EXISTS idx_learning_promotions_signal ON learning_promotions(signal_id);
    """),
    (14, """
        -- Durable run runtime: leases, fencing, write-ahead intents and a
        -- transition log. Mirrors supabase/migrations/20261009_amc_durable_runtime_v1.sql.
        CREATE TABLE IF NOT EXISTS durable_jobs (
            job_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            spec TEXT NOT NULL,
            spec_hash TEXT NOT NULL,
            requested_by TEXT NOT NULL,
            state TEXT NOT NULL,
            logical_tick INTEGER NOT NULL DEFAULT 0 CHECK (logical_tick >= 0),
            version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
            lease_owner TEXT,
            lease_token INTEGER NOT NULL DEFAULT 0 CHECK (lease_token >= 0),
            lease_expires_at TEXT,
            attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts BETWEEN 1 AND 3),
            recurrence_seconds INTEGER,
            next_due_at TEXT NOT NULL,
            last_reasons TEXT NOT NULL DEFAULT '[]',
            failure_fingerprints TEXT NOT NULL DEFAULT '{}',
            result TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS durable_intents (
            idempotency_key TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES durable_jobs(job_id) ON DELETE CASCADE,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            logical_tick INTEGER NOT NULL,
            operation TEXT NOT NULL,
            target TEXT NOT NULL,
            input_hash TEXT NOT NULL,
            contract_version TEXT NOT NULL,
            retry_class TEXT NOT NULL CHECK (retry_class IN ('RETRY_SAFE','COMPENSATABLE','NON_RETRYABLE')),
            pre_image TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL CHECK (status IN ('INTENT','COMMITTED','ABANDONED')),
            fencing_token INTEGER NOT NULL,
            receipt TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            committed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS durable_transitions (
            transition_id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL REFERENCES durable_jobs(job_id) ON DELETE CASCADE,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            from_state TEXT NOT NULL,
            to_state TEXT NOT NULL,
            fencing_token INTEGER NOT NULL,
            logical_tick INTEGER NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            trace_id TEXT,
            observed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS durable_ticks (
            trace_id TEXT PRIMARY KEY,
            job_id TEXT,
            tenant_id TEXT,
            project_id TEXT,
            worker_id TEXT NOT NULL,
            logical_tick INTEGER,
            outcome TEXT NOT NULL,
            telemetry TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_durable_jobs_due ON durable_jobs(state, next_due_at);
        CREATE INDEX IF NOT EXISTS idx_durable_jobs_project ON durable_jobs(project_id, state);
        CREATE INDEX IF NOT EXISTS idx_durable_intents_job ON durable_intents(job_id, logical_tick);
        CREATE INDEX IF NOT EXISTS idx_durable_transitions_job ON durable_transitions(job_id, transition_id);
    """),
    (15, """
        -- VNEXUS creative intelligence: brand genome versions, creative knowledge graph,
        -- branches, media jobs, prompt genomes, measurements and a hash-chained audit log.
        -- Mirrors supabase/migrations/20261011_amc_vnexus_v1.sql.
        create table if not exists vnexus_brands (
            brand_id text primary key,
            tenant_id text not null references tenants(tenant_id) on delete cascade,
            owner_project_id text not null references projects(project_id) on delete restrict,
            display_name text not null,
            created_by text not null,
            created_at text not null
        );

        create table if not exists vnexus_genome_versions (
            version_id text primary key,
            tenant_id text not null references tenants(tenant_id) on delete cascade,
            brand_id text not null references vnexus_brands(brand_id) on delete cascade,
            scope text not null check (scope in ('brand','project','page','component','asset')),
            scope_ref text not null,
            project_id text not null references projects(project_id) on delete cascade,
            version integer not null check (version >= 1),
            parent_version_id text references vnexus_genome_versions(version_id),
            status text not null check (status in ('DRAFT','EXPERIMENTAL','IN_REVIEW','APPROVED','REJECTED','SUPERSEDED')),
            document TEXT not null,
            content_hash text not null,
            revision integer not null default 1 check (revision >= 1),
            origin text not null check (origin in ('AUTHORED','REVERT','BRANCH_PROMOTION','IMPORT')),
            origin_ref text,
            created_by text not null,
            created_at text not null,
            updated_at text not null,
            submitted_by text,
            submitted_at text,
            approval_id text,
            decided_by text,
            decided_at text,
            unique (brand_id, scope, scope_ref, version)
        );

        create unique index if not exists uq_vnexus_genome_approved
            on vnexus_genome_versions(brand_id, scope, scope_ref) where status = 'APPROVED';

        create table if not exists vnexus_audit_log (
            entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id text not null references tenants(tenant_id) on delete cascade,
            chain_ref text not null,
            subject_type text not null,
            subject_id text not null,
            action text not null,
            actor text not null,
            from_state text,
            to_state text,
            detail TEXT not null default '{}',
            prev_hash text,
            entry_hash text not null unique,
            created_at text not null
        );

        create table if not exists vnexus_graph_nodes (
            node_id text primary key,
            tenant_id text not null references tenants(tenant_id) on delete cascade,
            brand_id text not null references vnexus_brands(brand_id) on delete cascade,
            kind text not null,
            label text not null,
            attributes TEXT not null default '{}',
            content_hash text not null,
            valid_from text not null,
            valid_to text,
            superseded_by text references vnexus_graph_nodes(node_id),
            created_by text not null,
            created_at text not null
        );

        create table if not exists vnexus_graph_edges (
            edge_id text primary key,
            tenant_id text not null references tenants(tenant_id) on delete cascade,
            brand_id text not null references vnexus_brands(brand_id) on delete cascade,
            kind text not null,
            src_node_id text not null references vnexus_graph_nodes(node_id) on delete cascade,
            dst_node_id text not null references vnexus_graph_nodes(node_id) on delete cascade,
            provenance TEXT not null default '{}',
            valid_from text not null,
            valid_to text,
            created_by text not null,
            created_at text not null,
            check (src_node_id <> dst_node_id)
        );

        create table if not exists vnexus_branches (
            branch_id text primary key,
            tenant_id text not null references tenants(tenant_id) on delete cascade,
            brand_id text not null references vnexus_brands(brand_id) on delete cascade,
            scope text not null,
            scope_ref text not null,
            project_id text not null references projects(project_id) on delete cascade,
            base_version_id text not null references vnexus_genome_versions(version_id),
            parent_branch_id text references vnexus_branches(branch_id),
            name text not null,
            hypothesis text not null default '',
            changes TEXT not null,
            changes_hash text not null,
            state text not null check (state in ('OPEN','IN_REVIEW','PROMOTED','REJECTED','ARCHIVED')),
            revision integer not null default 1 check (revision >= 1),
            proposal_version_id text references vnexus_genome_versions(version_id),
            decision_note text,
            created_by text not null,
            created_at text not null,
            updated_at text not null
        );

        create table if not exists vnexus_branch_evaluations (
            evaluation_id text primary key,
            tenant_id text not null references tenants(tenant_id) on delete cascade,
            branch_id text not null references vnexus_branches(branch_id) on delete cascade,
            kind text not null check (kind in ('DETERMINISTIC','HUMAN')),
            evaluator text not null,
            changes_hash text not null,
            payload TEXT not null,
            payload_hash text not null,
            created_at text not null
        );

        create table if not exists vnexus_media_jobs (
            job_id text primary key,
            tenant_id text not null references tenants(tenant_id) on delete cascade,
            project_id text not null references projects(project_id) on delete cascade,
            provider_id text not null,
            capability text not null,
            request TEXT not null,
            request_hash text not null,
            idempotency_key text not null,
            state text not null check (state in ('PLANNED','VALIDATED','AUTHORIZED','QUEUED','RUNNING','ARTIFACT_RECEIVED','QC_PASSED','FAILED','CANCELED')),
            estimate TEXT not null default '{}',
            budget_ceiling_minor integer not null default 0 check (budget_ceiling_minor >= 0),
            currency text not null default 'USD',
            authorized_by text,
            authorized_at text,
            attempts integer not null default 0 check (attempts >= 0),
            max_attempts integer not null default 2 check (max_attempts between 1 and 3),
            provider_job_ref text,
            artifact TEXT not null default '{}',
            qc TEXT not null default '{}',
            error text,
            version integer not null default 1 check (version >= 1),
            created_by text not null,
            created_at text not null,
            updated_at text not null,
            unique (tenant_id, idempotency_key)
        );

        create table if not exists vnexus_media_job_transitions (
            transition_id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id text not null references vnexus_media_jobs(job_id) on delete cascade,
            tenant_id text not null,
            from_state text not null,
            to_state text not null,
            reason text not null default '',
            actor text not null,
            observed_at text not null
        );

        create table if not exists vnexus_prompt_genomes (
            prompt_version_id text primary key,
            tenant_id text not null references tenants(tenant_id) on delete cascade,
            brand_id text not null references vnexus_brands(brand_id) on delete cascade,
            prompt_id text not null,
            version integer not null check (version >= 1),
            parent_version_id text references vnexus_prompt_genomes(prompt_version_id),
            status text not null check (status in ('DRAFT','APPROVED','SUPERSEDED','SOURCE_REQUIRED')),
            source_kind text not null check (source_kind in ('ORIGINAL_IMPORT','DERIVED','AUTHORED')),
            source_hash text,
            document TEXT not null,
            content_hash text not null,
            created_by text not null,
            created_at text not null,
            unique (brand_id, prompt_id, version)
        );

        create table if not exists vnexus_measurements (
            measurement_id text primary key,
            tenant_id text not null references tenants(tenant_id) on delete cascade,
            project_id text not null references projects(project_id) on delete cascade,
            campaign_ref text not null,
            metric text not null,
            value REAL not null,
            unit text not null,
            source text not null,
            source_ref text not null,
            observed_at text not null,
            recorded_by text not null,
            recorded_at text not null,
            kind text not null default 'MEASURED' check (kind = 'MEASURED')
        );

        create index if not exists idx_vnexus_genome_scope on vnexus_genome_versions(brand_id, scope, scope_ref, status);
        create index if not exists idx_vnexus_audit_chain on vnexus_audit_log(chain_ref, entry_id);
        create index if not exists idx_vnexus_nodes_brand on vnexus_graph_nodes(brand_id, kind);
        create index if not exists idx_vnexus_edges_src on vnexus_graph_edges(src_node_id, kind);
        create index if not exists idx_vnexus_edges_dst on vnexus_graph_edges(dst_node_id, kind);
        create index if not exists idx_vnexus_branches_brand on vnexus_branches(brand_id, state);
        create index if not exists idx_vnexus_media_jobs_project on vnexus_media_jobs(project_id, state);
        create index if not exists idx_vnexus_measurements_campaign on vnexus_measurements(project_id, campaign_ref);
    """),
    (16, """
        -- ACE v12 governed action plane and agency clients. Additive only: no existing
        -- table is altered. Mirrors supabase/migrations/20261012_amc_actions_v1.sql.

        create table if not exists action_requests (
            action_id text primary key,
            tenant_id text not null references tenants(tenant_id) on delete cascade,
            project_id text not null references projects(project_id) on delete cascade,
            client_id text,
            capability_id text not null,
            capability_version text not null,
            environment text not null check (environment in ('LOCAL','SANDBOX','LIVE')),
            actor_ref text not null,
            target_ref text not null,
            args text not null,
            args_hash text not null,
            payload_hash text not null,
            context_hash text not null,
            dependency_hashes text not null,
            policy_version text not null,
            risk text not null,
            risk_hash text not null,
            effective_class text not null check (effective_class in ('R0','R1','R2','R3','R4','R5','R6')),
            binding text not null,
            binding_hash text not null,
            run_id text,
            approval_id text,
            financial_approval_id text,
            budget_reservation_id text,
            idempotency_key text not null,
            request_hash text not null,
            correlation_id text not null,
            state text not null check (state in ('PROPOSED','VALIDATED','PREPARED','AWAITING_APPROVAL','AUTHORIZED','RESERVED',
                'DISPATCHING','OBSERVING','VERIFIED','COMPLETED','REJECTED','BLOCKED','EXPIRED','CANCELLED','FAILED','UNKNOWN',
                'RECONCILING','NEEDS_HUMAN')),
            version integer not null default 1 check (version >= 1),
            attempts integer not null default 0 check (attempts >= 0 and attempts <= 3),
            reconcile_attempts integer not null default 0 check (reconcile_attempts >= 0),
            lease_owner text,
            lease_expires_at text,
            retry_eligible integer not null default 0,
            reasons text not null,
            outcome text,
            injection_flags text not null,
            created_at text not null,
            updated_at text not null,
            expires_at text not null,
            unique (tenant_id, idempotency_key)
        );

        create table if not exists action_transitions (
            entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_id text not null references action_requests(action_id) on delete cascade,
            tenant_id text not null references tenants(tenant_id) on delete cascade,
            from_state text,
            to_state text not null,
            actor text not null,
            reason text not null,
            evidence text not null,
            prev_hash text,
            entry_hash text not null,
            created_at text not null
        );

        create table if not exists action_budget_policies (
            policy_id text primary key,
            tenant_id text not null references tenants(tenant_id) on delete cascade,
            scope_kind text not null check (scope_kind in ('ACTION','PROJECT','CLIENT','TENANT_DAY','TENANT_MONTH')),
            scope_ref text not null,
            currency text not null check (length(currency) = 3 and currency = upper(currency)),
            ceiling_minor bigint not null check (ceiling_minor >= 0),
            created_by text not null,
            created_at text not null,
            unique (tenant_id, scope_kind, scope_ref, currency)
        );

        create table if not exists action_budget_reservations (
            reservation_id text primary key,
            tenant_id text not null references tenants(tenant_id) on delete cascade,
            project_id text not null references projects(project_id) on delete cascade,
            client_id text,
            action_id text not null references action_requests(action_id) on delete cascade,
            currency text not null check (length(currency) = 3 and currency = upper(currency)),
            amount_minor bigint not null check (amount_minor >= 0),
            committed_minor bigint check (committed_minor is null or committed_minor >= 0),
            status text not null check (status in ('RESERVED','COMMITTED','RELEASED','EXPIRED','REFUNDED')),
            expires_at text not null,
            evidence text not null,
            created_at text not null,
            updated_at text not null
        );

        create table if not exists action_freezes (
            freeze_id text primary key,
            tenant_id text not null references tenants(tenant_id) on delete cascade,
            scope_kind text not null check (scope_kind in ('TENANT','PROJECT')),
            scope_ref text not null,
            reason text not null,
            frozen_by text not null,
            frozen_at text not null,
            lifted_by text,
            lifted_at text,
            lift_reason text
        );

        create table if not exists action_project_settings (
            project_id text primary key references projects(project_id) on delete cascade,
            tenant_id text not null references tenants(tenant_id) on delete cascade,
            autonomy text not null check (autonomy in ('OBSERVE','DRAFT','PREPARE','REQUEST_APPROVAL')),
            updated_by text not null,
            updated_at text not null
        );

        -- The sandbox fake providers' "remote" state. Only sandbox adapters read or
        -- write it; nothing here was delivered anywhere.
        create table if not exists action_sandbox_effects (
            effect_id text primary key,
            tenant_id text not null references tenants(tenant_id) on delete cascade,
            provider text not null,
            operation text not null,
            idempotency_key text not null,
            target_ref text not null,
            payload_hash text not null,
            state text not null,
            cost_minor bigint not null default 0,
            currency text,
            body text not null,
            created_at text not null,
            updated_at text not null,
            unique (tenant_id, provider, idempotency_key)
        );

        create table if not exists agency_clients (
            client_id text primary key,
            tenant_id text not null references tenants(tenant_id) on delete cascade,
            display_name text not null,
            slug text not null,
            status text not null check (status in ('ACTIVE','OFFBOARDING','ARCHIVED')),
            notes text not null default '',
            created_by text not null,
            created_at text not null,
            updated_at text not null,
            unique (tenant_id, slug)
        );

        create table if not exists agency_client_projects (
            project_id text primary key references projects(project_id) on delete cascade,
            client_id text not null references agency_clients(client_id) on delete cascade,
            tenant_id text not null references tenants(tenant_id) on delete cascade,
            linked_by text not null,
            linked_at text not null
        );

        create index if not exists idx_action_requests_project on action_requests(project_id, state);
        create index if not exists idx_action_requests_tenant_state on action_requests(tenant_id, state);
        create index if not exists idx_action_transitions_action on action_transitions(action_id, entry_id);
        create index if not exists idx_action_reservations_tenant on action_budget_reservations(tenant_id, currency, status);
        create index if not exists idx_action_freezes_scope on action_freezes(tenant_id, scope_kind, scope_ref);
        create index if not exists idx_agency_client_projects_client on agency_client_projects(client_id);
    """),
    (17, """
        -- ACE v100: recover uncertain provider outcomes as durable journal states.
        -- SQLite cannot change a CHECK in place: rebuild inside a single transaction.
        BEGIN TRANSACTION;
        CREATE TABLE durable_intents_new (
            idempotency_key TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES durable_jobs(job_id) ON DELETE CASCADE,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            logical_tick INTEGER NOT NULL,
            operation TEXT NOT NULL,
            target TEXT NOT NULL,
            input_hash TEXT NOT NULL,
            contract_version TEXT NOT NULL,
            retry_class TEXT NOT NULL CHECK (retry_class IN ('RETRY_SAFE','COMPENSATABLE','NON_RETRYABLE')),
            pre_image TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL CHECK (status IN ('INTENT','UNCONFIRMED','COMMITTED','FAILED','ABANDONED')),
            fencing_token INTEGER NOT NULL,
            receipt TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            committed_at TEXT
        );
        INSERT INTO durable_intents_new SELECT * FROM durable_intents;
        DROP TABLE durable_intents;
        ALTER TABLE durable_intents_new RENAME TO durable_intents;
        CREATE INDEX idx_durable_intents_job ON durable_intents(job_id, logical_tick);
        COMMIT;
    """),

    (18, """
        -- ACE v100: append-only, cryptographically authenticated per-project evidence.
        CREATE TABLE IF NOT EXISTS ace_provenance (
            tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id),
            project_id TEXT NOT NULL REFERENCES projects(project_id),
            sequence INTEGER NOT NULL CHECK (sequence >= 1),
            key_id TEXT NOT NULL,
            actor TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            previous_hash TEXT NOT NULL,
            payload_digest TEXT NOT NULL,
            record_hash TEXT NOT NULL,
            signature TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            PRIMARY KEY (tenant_id, project_id, sequence)
        );
        CREATE INDEX IF NOT EXISTS idx_ace_provenance_project
            ON ace_provenance(project_id, sequence);
    """),

    (19, """
        -- Mission council: ideas, engine state, checkpoints, blueprints, tool audits.
        -- Additive only. A mission is a runs row (status, approvals and run_events are
        -- reused). Mirrors supabase/migrations/20261022_amc_mission_council_v1.sql.
        CREATE TABLE IF NOT EXISTS council_ideas (
            idea_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('OPEN','PROMOTED')),
            created_by TEXT NOT NULL,
            seed_key TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_council_ideas_seed ON council_ideas(tenant_id, seed_key) WHERE seed_key IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_council_ideas_project ON council_ideas(project_id, created_at);

        CREATE TABLE IF NOT EXISTS council_missions (
            mission_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
            idea_id TEXT NOT NULL REFERENCES council_ideas(idea_id) ON DELETE CASCADE,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            engine TEXT NOT NULL CHECK (engine IN ('langgraph','crewai','autogen')),
            model_mode TEXT NOT NULL CHECK (model_mode IN ('MOCK_DETERMINISTIC','PROVIDER')),
            phase TEXT NOT NULL CHECK (phase IN ('STRATEGY','AUDIT','GATE','PROTOTYPE','DONE')),
            version INTEGER NOT NULL DEFAULT 0,
            lease_owner TEXT,
            lease_expires_at TEXT,
            approval_id TEXT,
            approval_subject_hash TEXT,
            consumed_approval_id TEXT,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_council_missions_idea ON council_missions(idea_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_council_missions_project ON council_missions(project_id, created_at);

        CREATE TABLE IF NOT EXISTS council_checkpoints (
            checkpoint_id TEXT PRIMARY KEY,
            mission_id TEXT NOT NULL REFERENCES council_missions(mission_id) ON DELETE CASCADE,
            seq INTEGER NOT NULL CHECK (seq >= 0),
            phase TEXT NOT NULL,
            engine TEXT NOT NULL,
            state TEXT NOT NULL,
            state_hash TEXT NOT NULL,
            prev_hash TEXT NOT NULL,
            native_checkpoint_id TEXT,
            created_at TEXT NOT NULL,
            UNIQUE (mission_id, seq)
        );

        CREATE TABLE IF NOT EXISTS council_blueprints (
            blueprint_id TEXT PRIMARY KEY,
            idea_id TEXT NOT NULL REFERENCES council_ideas(idea_id) ON DELETE CASCADE,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('DRAFT','PROMOTED')),
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            sources TEXT NOT NULL,
            verification TEXT,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            promoted_by TEXT,
            promoted_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_council_blueprints_idea ON council_blueprints(idea_id, created_at);

        CREATE TABLE IF NOT EXISTS council_tool_audits (
            audit_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            mission_id TEXT,
            seat TEXT,
            tool_id TEXT NOT NULL,
            sensitivity TEXT NOT NULL,
            decision TEXT NOT NULL CHECK (decision IN ('ALLOWED','DENIED','FAILED','TIMEOUT')),
            reason_code TEXT NOT NULL,
            args_redacted TEXT NOT NULL,
            args_hash TEXT NOT NULL,
            result_summary TEXT,
            approval_id TEXT,
            action_hash TEXT,
            duration_ms INTEGER,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_council_tool_audits_mission ON council_tool_audits(mission_id, created_at);

        CREATE TABLE IF NOT EXISTS council_approval_consumptions (
            approval_id TEXT NOT NULL,
            mission_id TEXT NOT NULL,
            action_hash TEXT NOT NULL,
            consumed_by TEXT NOT NULL,
            consumed_at TEXT NOT NULL,
            PRIMARY KEY (approval_id, action_hash)
        );
    """),
    (20, """
        -- Agency operating framework: per-project plans pinned to the immutable
        -- 295-task catalog, and one instance row per task. Additive only. Evidence,
        -- artifacts, decisions, approvals and audit events stay in their existing
        -- stores and are referenced here, never copied. Mirrors
        -- supabase/migrations/20261024_amc_agency_framework_v1.sql.
        CREATE TABLE IF NOT EXISTS agency_framework_plans (
            plan_id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
            catalog_id TEXT NOT NULL,
            catalog_version TEXT NOT NULL,
            catalog_sha256 TEXT NOT NULL,
            archetype TEXT NOT NULL,
            engagement_scope TEXT NOT NULL DEFAULT '',
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (project_id, catalog_version)
        );

        CREATE TABLE IF NOT EXISTS agency_task_instances (
            plan_id TEXT NOT NULL REFERENCES agency_framework_plans(plan_id) ON DELETE CASCADE,
            task_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            module_id TEXT NOT NULL,
            stage_gate TEXT NOT NULL,
            applicability TEXT NOT NULL CHECK (applicability IN ('UNASSESSED','REQUIRED','CONDITIONAL','NOT_APPLICABLE')),
            applicability_reason TEXT,
            applicability_by TEXT,
            state TEXT NOT NULL CHECK (state IN ('BACKLOG','READY','ACTIVE','IN_REVIEW','VERIFIED','APPROVED','BLOCKED','INVALIDATED','NOT_APPLICABLE')),
            blocked_from TEXT,
            status_reason TEXT,
            assignee_role TEXT NOT NULL,
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            artifact_refs TEXT NOT NULL DEFAULT '[]',
            decision_refs TEXT NOT NULL DEFAULT '[]',
            submitted_by TEXT,
            verification TEXT,
            approval_ref TEXT,
            version INTEGER NOT NULL DEFAULT 0,
            updated_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (plan_id, task_id)
        );
        CREATE INDEX IF NOT EXISTS idx_agency_task_instances_project ON agency_task_instances(project_id, module_id);
    """),

]


def _ensure_approval_columns(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(approvals)").fetchall()}
    for name in (
        "subject_type",
        "subject_ref",
        "subject_version_ref",
        "subject_hash",
        "authority_ref",
        "policy_version",
        "stale_reason",
        "staled_at",
    ):
        if name not in columns:
            conn.execute(f"ALTER TABLE approvals ADD COLUMN {name} TEXT")


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
        applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()}
        for version, script in _MIGRATIONS:
            if version in applied:
                continue
            conn.executescript(script)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
        _ensure_approval_columns(conn)
        conn.commit()


def current_schema_version() -> int:
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
        return int(row[0])
