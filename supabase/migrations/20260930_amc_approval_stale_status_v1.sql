-- Allow the 'stale' approval status the runtime writes when a protected
-- subject changes after review (persistence/approvals.py mark_approval_stale).
-- The original constraint only allowed ('pending','resolved'), so staling an
-- approval raised a CheckViolation on PostgreSQL.
alter table amc.approvals drop constraint if exists approvals_status_check;
alter table amc.approvals
    add constraint approvals_status_check check (status in ('pending', 'resolved', 'stale'));
