create index if not exists idx_amc_runs_project_id on amc.runs(project_id);
create index if not exists idx_amc_spend_run_id on amc.spend_authorizations(run_id) where run_id is not null;
