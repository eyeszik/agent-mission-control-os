.PHONY: help check-env tokens-build brand-plan brand-roles brand-validate setup-agent gates

help:
	@echo "Available commands:"
	@echo "  make check-env                  - Environment pre-flight check"
	@echo "  make tokens-build               - Compile tokens.json into _tokens.css"
	@echo "  make brand-plan [BRIEF=f.json]  - Plan a brief against the agency kernel"
	@echo "  make brand-roles [DEPT=brand]   - List N3 role contracts"
	@echo "  make brand-validate             - Run the kernel's structural self-checks"
	@echo "  make setup-agent                - Run workspace setup script"
	@echo "  make gates                      - Run every CI verifier gate"

# === Added by Brand Orchestration System ===
check-env:
	@python3 check_env.py

tokens-build:
	@python3 compile_tokens.py

# Plans only; generates nothing. Exits non-zero when the kernel blocks the run.
brand-plan:
	@python3 orchestrate_brand_pipeline.py plan --input $(if $(BRIEF),$(BRIEF),sample_brief.json)

brand-roles:
	@python3 orchestrate_brand_pipeline.py roles $(if $(DEPT),--department $(DEPT),)

brand-validate:
	@python3 orchestrate_brand_pipeline.py validate

setup-agent:
	@bash ./setup-workspace-v5.sh

gates:
	@python3 scripts/verify_repository_invariants.py
	@python3 scripts/verify_production_readiness.py
	@python3 scripts/verify_auth_bindings.py
	@python3 scripts/verify_ontology_parity.py
	@python3 scripts/verify_design_tokens.py
	@python3 scripts/verify_manifest.py
