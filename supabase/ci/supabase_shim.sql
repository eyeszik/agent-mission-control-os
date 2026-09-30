-- CI/test-only stand-ins for objects a Supabase project provides.
-- Applied before supabase/migrations/*.sql against a plain PostgreSQL service
-- so the production schema can be exercised in CI. Never apply to Supabase.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin; end if;
end
$$;
create schema if not exists auth;
create table if not exists auth.users (id uuid primary key);
