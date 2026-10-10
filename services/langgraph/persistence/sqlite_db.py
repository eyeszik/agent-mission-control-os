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
