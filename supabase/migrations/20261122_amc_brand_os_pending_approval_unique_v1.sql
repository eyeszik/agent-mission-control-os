-- At most one pending Brand OS approval per (tenant, project, artifact, purpose).
--
-- Two concurrent adoption requests for the same SOP in the same project used to be able to
-- open two pending approvals: open_artifact_approval reads before it writes and takes no lock.
-- This partial unique index makes the database the arbiter; the loser of the race gets a unique
-- violation and re-reads the winner's approval (agency/intake/release.py).
--
-- Scoped to the two Brand OS subject types only. Other approval purposes keep their existing
-- semantics. Any duplicate pending rows already present are marked stale (never approved,
-- never deleted) so the index can be built; the earliest request keeps its approval.
with ranked as (
    select approval_id,
           row_number() over (partition by tenant_id, project_id, subject_ref, subject_type
                              order by created_at, approval_id) as rn
    from amc.approvals
    where status = 'pending' and subject_type in ('BRAND_OS_SOP_ADOPTION', 'BRAND_OS_SOURCE')
)
update amc.approvals a
   set status = 'stale',
       stale_reason = 'superseded: duplicate pending Brand OS approval',
       staled_at = now()
  from ranked r
 where a.approval_id = r.approval_id and r.rn > 1;

create unique index if not exists idx_amc_approvals_brand_os_pending
    on amc.approvals (tenant_id, project_id, subject_ref, subject_type)
    where status = 'pending' and subject_type in ('BRAND_OS_SOP_ADOPTION', 'BRAND_OS_SOURCE');
