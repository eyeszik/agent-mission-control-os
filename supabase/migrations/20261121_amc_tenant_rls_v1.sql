-- AMC tenant row-level security, v1 (WO-04).
--
-- Layers, from outermost in (docs/migrations/tenant-rls.md):
--   1. Schema REVOKE: anon/authenticated still have no USAGE on schema amc (unchanged).
--   2. RLS on every amc table. Tables with tenant_id get one policy that admits a row only
--      when it matches the transaction's tenant context; tables without tenant_id get no
--      policy, so any role subject to RLS is denied every row.
--   3. Tenant context: the backend sets amc.tenant_id per transaction (set_config(..., true))
--      when AMC_DB_RLS_MODE=scoped and a tenant scope is active.
--
-- RLS is ENABLED, not FORCED. The migrating/owning role is exempt, so the current backend
-- (which connects as the owner) behaves exactly as before. Isolation is enforced against any
-- non-owner role, e.g. the dedicated application role an owner may deploy in front of the
-- backend. No tenant context means no rows (fail closed): amc.current_tenant_id() is NULL and
-- NULL never equals a tenant_id.

create or replace function amc.current_tenant_id() returns text
    language sql stable
    set search_path = pg_catalog
as $$ select nullif(current_setting('amc.tenant_id', true), '') $$;

comment on function amc.current_tenant_id() is
    'Tenant context of the current transaction (amc.tenant_id GUC); NULL when unset, which no row matches.';

do $$
declare
    t record;
begin
    for t in
        select c.relname,
               exists (select 1 from pg_attribute a
                        where a.attrelid = c.oid and a.attname = 'tenant_id' and a.attnum > 0 and not a.attisdropped) as tenant_scoped
          from pg_class c
          join pg_namespace n on n.oid = c.relnamespace
         where n.nspname = 'amc' and c.relkind = 'r'
         order by c.relname
    loop
        execute format('alter table amc.%I enable row level security', t.relname);
        if t.tenant_scoped then
            execute format(
                'create policy amc_tenant_isolation on amc.%I as permissive for all '
                'using (tenant_id::text = amc.current_tenant_id()) '
                'with check (tenant_id::text = amc.current_tenant_id())',
                t.relname);
        end if;
    end loop;
end
$$;
