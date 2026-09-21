
# === Added by Brand Orchestration System ===
check-env:
	@python3 check_env.py

tokens-build:
	@python3 compile_tokens.py

brand-orchestrate:
	@python3 orchestrate_brand_pipeline.py $(if $(BRIEF),--input $(BRIEF),)

setup-agent:
	@bash ./setup-workspace-v5.sh
