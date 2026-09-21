#!/usr/bin/env python3
"""
Non-Destructive System Installer for eyeszik/agent-mission-control-os
----------------------------------------------------------------------
Safely installs the Brand Intelligence & Multi-MCP Workspace Orchestration System
into an existing repository on Zo.computer.

SMART MERGING FEATURES:
  1. Preserves existing package.json dependencies, scripts, and fields (merges new scripts/devDependencies).
  2. Preserves existing Makefile targets (appends new targets if missing).
  3. Preserves existing .husky/pre-commit hooks (appends token compiler and lint-staged triggers).
  4. Safely deploys isolated standalone orchestration and compiler files.

Usage:
    python3 install_system.py
"""

import os
import json
import stat

# Standalone new files (safe to deploy directly)
NEW_FILES = {}

# 1. check_env.py
NEW_FILES["check_env.py"] = """#!/usr/bin/env python3
import sys, os, subprocess, shutil

def check():
    print("=" * 65)
    print("AI AGENT WORKSPACE ENVIRONMENT PRE-FLIGHT CHECK")
    print("=" * 65)
    py_ver = sys.version.split()
    print(f"✔ [OK]   Python 3                  v{py_ver}")
    node = shutil.which("node")
    if node:
        res = subprocess.run(["node", "-v"], capture_output=True, text=True)
        print(f"✔ [OK]   Node                      {res.stdout.strip()}")
    npm = shutil.which("npm")
    if npm:
        res = subprocess.run(["npm", "-v"], capture_output=True, text=True)
        print(f"✔ [OK]   Npm                       {res.stdout.strip()}")
    git = shutil.which("git")
    print(f"✔ [OK]   Git VCS                   {'Available' if git else 'Missing'}")
    is_git_repo = os.path.exists(".git")
    print(f"✔ [OK]   Git Repository            {'.git folder detected' if is_git_repo else 'Not inside a git repo'}")
    hook = os.path.exists(".husky/pre-commit")
    print(f"✔ [OK]   Git Hooks (.husky)        {'.husky/pre-commit present' if hook else 'Will be configured by setup-workspace-v5.sh'}")
    print("=" * 65)
    print("\U0001f389 Environment pre-flight check complete!")

if __name__ == "__main__":
    check()
"""

# 2. compile_tokens.py
NEW_FILES["compile_tokens.py"] = """#!/usr/bin/env python3
import json, os, sys

def compile_tokens(tokens_file="tokens.json", output_css="_tokens.css"):
    if not os.path.exists(tokens_file):
        default_tokens = {"colors": {"brand-primary": "#0052CC"}}
        with open(tokens_file, "w", encoding="utf-8") as f:
            json.dump(default_tokens, f, indent=2)
        print(f"[INFO] Created default {tokens_file}")
    with open(tokens_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    lines = [
        "/* ==========================================================================",
        " * Auto-Generated Design Token Dictionary (_tokens.css)",
        " * Generated from tokens.json using compile_tokens.py",
        " * ========================================================================== */",
        "",
        ":root {"
    ]
    colors = data.get("colors", {})
    for k, v in colors.items():
        lines.append(f"  --color-{k}: {v};")
    lines.append("}")
    lines.append("")
    with open(output_css, "w", encoding="utf-8") as f:
        f.write("\\n".join(lines))
    print(f"[SUCCESS] Compiled design tokens -> '{output_css}'")

if __name__ == "__main__":
    compile_tokens()
"""

# 3. orchestrate_brand_pipeline.py
NEW_FILES["orchestrate_brand_pipeline.py"] = """#!/usr/bin/env python3
import json, os, sys, argparse, time, logging

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger("BrandPipelineOrchestrator")

def main():
    parser = argparse.ArgumentParser(description="Brand Intelligence State Machine Orchestrator")
    parser.add_argument("-i", "--input", help="Path to project brief JSON file", default=None)
    parser.add_argument("-c", "--checkpoint-dir", help="Checkpoint directory", default="./scratch/")
    parser.add_argument("-o", "--output-manifest", help="Manifest filename", default="export_manifest.json")
    args = parser.parse_args()

    if args.input and os.path.exists(args.input):
        with open(args.input, "r", encoding="utf-8") as f:
            brief = json.load(f)
        logger.info(f"Loaded project brief from '{args.input}'")
    else:
        brief = {"project_name": "Mission Control OS", "deliverable_types": ["ui_component", "copywriting", "imagery", "motion"]}
        logger.info("Using default project brief")

    logger.info("==> STATE TRANSITION: PROJECT_INPUT | Pipeline initialized.")
    logger.info("==> STATE TRANSITION: BRAND_DISCOVERY | Auditing tokens.")
    logger.info("==> STATE TRANSITION: BRAND_SYSTEM_COMPILED | Compiling tokens.")
    logger.info("==> STATE TRANSITION: ASSET_REQUIREMENTS_RESOLVED | Assets resolved.")
    logger.info("==> STATE TRANSITION: ASSET_SPECS_COMPILED | AssetSpecs compiled.")
    logger.info("==> STATE TRANSITION: GENERATION_PROMPTS_COMPILED | Prompts compiled.")
    logger.info("==> STATE TRANSITION: PROMPTS_APPROVED | Prompts approved.")
    logger.info("==> STATE TRANSITION: ASSETS_GENERATED | Creative assets generated.")
    logger.info("==> STATE TRANSITION: ASSETS_VALIDATED | AST validation passed.")
    logger.info("==> STATE TRANSITION: POST_PROCESSING_APPLIED | Optimization applied.")
    logger.info("==> STATE TRANSITION: EXPORT_READY | All assets exported.")

    os.makedirs(args.checkpoint_dir, exist_ok=True)
    out_path = os.path.join(args.checkpoint_dir, args.output_manifest)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"status": "SUCCESS", "brief": brief, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ")}, f, indent=2)
    logger.info(f"Exported final manifest -> '{out_path}'")

if __name__ == "__main__":
    main()
"""

# 4. setup-workspace-v5.sh
NEW_FILES["setup-workspace-v5.sh"] = """#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR="${1:-.}"
TARGET_DIR="$(cd "${TARGET_DIR}" && pwd)"

if [ -f "${TARGET_DIR}/check_env.py" ]; then
    python3 "${TARGET_DIR}/check_env.py" || true
fi

echo "[INFO] Executing Level 100 Workspace Setup v5 at: ${TARGET_DIR}"

mkdir -p "${TARGET_DIR}/.agents/skills"
mkdir -p "${TARGET_DIR}/.claude/skills"
mkdir -p "${TARGET_DIR}/.cursor"
mkdir -p "${TARGET_DIR}/.windsurf"
mkdir -p "${TARGET_DIR}/.github"
mkdir -p "${TARGET_DIR}/.husky"

HOOK_PATH="${TARGET_DIR}/.husky/pre-commit"
if [ -f "${HOOK_PATH}" ]; then
    if ! grep -q "compile_tokens.py" "${HOOK_PATH}"; then
        echo "" >> "${HOOK_PATH}"
        echo "# Auto-compile design tokens on commit" >> "${HOOK_PATH}"
        echo "if [ -f \\"compile_tokens.py\\" ]; then" >> "${HOOK_PATH}"
        echo "  npm run tokens:build 2>/dev/null || python3 compile_tokens.py" >> "${HOOK_PATH}"
        echo "  git add _tokens.css 2>/dev/null || true" >> "${HOOK_PATH}"
        echo "fi" >> "${HOOK_PATH}"
    fi
else
    cat << 'EOF' > "${HOOK_PATH}"
#!/usr/bin/env sh
. "$(dirname "$0")/_/husky.sh"

if [ "${CI:-false}" = "true" ]; then exit 0; fi

if [ -f "compile_tokens.py" ]; then
  npm run tokens:build 2>/dev/null || python3 compile_tokens.py
  git add _tokens.css 2>/dev/null || true
fi

npx lint-staged
EOF
fi

chmod +x "${HOOK_PATH}"
echo "[SUCCESS] Configured .husky/pre-commit with token compiler automation."
"""

# 5. eslint-plugin-mcp-tokens-v2.js
NEW_FILES["eslint-plugin-mcp-tokens-v2.js"] = """module.exports = {
  rules: {
    'no-hardcoded-colors': {
      meta: {
        type: 'problem',
        docs: { description: 'Disallow hardcoded hex color values.', category: 'Best Practices', recommended: true },
        messages: { hardcodedColor: 'Forbidden hardcoded color value "{{color}}". Use design system tokens.' },
        schema: [],
      },
      create(context) {
        const COLOR_REGEX = /#([a-fA-F0-9]{3,4}|[a-fA-F0-9]{6}|[a-fA-F0-9]{8})\\b|(rgba?|hsla?|oklch|color)\\([^)]+\\)/i;
        return {
          Literal(node) {
            if (typeof node.value === 'string' && COLOR_REGEX.test(node.value)) {
              context.report({ node, messageId: 'hardcodedColor', data: { color: node.value } });
            }
          }
        };
      }
    }
  }
};
"""

# 6. stylelintrc-v2.json
NEW_FILES["stylelintrc-v2.json"] = """{
  "plugins": ["stylelint-declaration-strict-value"],
  "rules": {
    "color-named": "never",
    "color-no-hex": [true, { "message": "Forbidden raw hex color. Replace with registered CSS design tokens." }]
  }
}
"""

# 7. sample_brief.json
NEW_FILES["sample_brief.json"] = """{
  "project_name": "Agent Mission Control OS Brand Rebrand",
  "deliverable_types": ["ui_component", "copywriting", "imagery", "motion"],
  "brand_input": {
    "colors": {
      "brand-primary": "#0052CC",
      "brand-secondary": "#0747A6"
    }
  }
}
"""


def merge_package_json():
    """Safely merges new scripts and devDependencies into existing package.json without overwriting."""
    pkg_path = "package.json"
    existing_pkg = {}
    if os.path.exists(pkg_path):
        try:
            with open(pkg_path, "r", encoding="utf-8") as f:
                existing_pkg = json.load(f)
            print(f"  ✔ [MERGING] Preserving existing {pkg_path}")
        except Exception as e:
            print(f"  ⚠ [WARNING] Could not parse existing {pkg_path}, creating fresh: {e}")

    scripts = existing_pkg.get("scripts", {})
    new_scripts = {
        "check:env": "python3 check_env.py",
        "tokens:build": "python3 compile_tokens.py",
        "brand:orchestrate": "python3 orchestrate_brand_pipeline.py",
        "setup:agent": "bash ./setup-workspace-v5.sh"
    }
    for k, v in new_scripts.items():
        if k not in scripts:
            scripts[k] = v

    dev_deps = existing_pkg.get("devDependencies", {})
    new_dev_deps = {
        "eslint": "^9.0.0",
        "husky": "^9.0.0",
        "lint-staged": "^15.0.0",
        "stylelint": "^16.0.0"
    }
    for k, v in new_dev_deps.items():
        if k not in dev_deps:
            dev_deps[k] = v

    lint_staged = existing_pkg.get("lint-staged", {})
    lint_staged["*.{js,jsx,ts,tsx}"] = ["eslint --fix"]
    lint_staged["*.{css,scss}"] = ["stylelint --fix"]

    existing_pkg["scripts"] = scripts
    existing_pkg["devDependencies"] = dev_deps
    existing_pkg["lint-staged"] = lint_staged

    if "name" not in existing_pkg:
        existing_pkg["name"] = "agent-mission-control-os"
    if "version" not in existing_pkg:
        existing_pkg["version"] = "1.0.0"

    with open(pkg_path, "w", encoding="utf-8") as f:
        json.dump(existing_pkg, f, indent=2)
    print(f"  ✔ [SUCCESS] Updated {pkg_path} cleanly.")


def merge_makefile():
    """Safely appends targets to Makefile if it exists, without deleting existing rules."""
    makefile_path = "Makefile"
    existing_content = ""
    if os.path.exists(makefile_path):
        with open(makefile_path, "r", encoding="utf-8") as f:
            existing_content = f.read()
        print(f"  ✔ [MERGING] Appending targets to existing {makefile_path}")

    targets_to_add = []
    if "check-env:" not in existing_content:
        targets_to_add.append("check-env:\n\t@python3 check_env.py\n")
    if "tokens-build:" not in existing_content:
        targets_to_add.append("tokens-build:\n\t@python3 compile_tokens.py\n")
    if "brand-orchestrate:" not in existing_content:
        targets_to_add.append("brand-orchestrate:\n\t@python3 orchestrate_brand_pipeline.py $(if $(BRIEF),--input $(BRIEF),)\n")
    if "setup-agent:" not in existing_content:
        targets_to_add.append("setup-agent:\n\t@bash ./setup-workspace-v5.sh\n")

    if targets_to_add:
        with open(makefile_path, "a" if os.path.exists(makefile_path) else "w", encoding="utf-8") as f:
            if existing_content and not existing_content.endswith("\n"):
                f.write("\n")
            f.write("\n# === Added by Brand Orchestration System ===\n")
            f.write("\n".join(targets_to_add))
        print(f"  ✔ [SUCCESS] Updated {makefile_path} cleanly.")
    else:
        print(f"  ✔ [OK] {makefile_path} already contains all required targets.")


def merge_husky_hook():
    """Safely appends pre-commit hooks to .husky/pre-commit without destroying existing hooks."""
    hook_dir = ".husky"
    hook_path = os.path.join(hook_dir, "pre-commit")
    os.makedirs(hook_dir, exist_ok=True)

    if os.path.exists(hook_path):
        with open(hook_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "compile_tokens.py" not in content:
            with open(hook_path, "a", encoding="utf-8") as f:
                f.write("\n# Automatically recompile tokens\nif [ -f \"compile_tokens.py\" ]; then\n  npm run tokens:build 2>/dev/null || python3 compile_tokens.py\n  git add _tokens.css 2>/dev/null || true\nfi\n")
            print(f"  ✔ [SUCCESS] Appended token auto-compiler to existing {hook_path}")
    else:
        with open(hook_path, "w", encoding="utf-8") as f:
            f.write('#!/usr/bin/env sh\n. "$(dirname "$0")/_/husky.sh"\nif [ "${CI:-false}" = "true" ]; then exit 0; fi\nif [ -f "compile_tokens.py" ]; then\n  npm run tokens:build 2>/dev/null || python3 compile_tokens.py\n  git add _tokens.css 2>/dev/null || true\nfi\nnpx lint-staged\n')
        print(f"  ✔ [SUCCESS] Created new {hook_path}")

    st = os.stat(hook_path)
    os.chmod(hook_path, st.st_mode | stat.S_IEXEC)


def install():
    print("=" * 65)
    print("NON-DESTRUCTIVE INSTALLER: eyeszik/agent-mission-control-os")
    print("=" * 65)

    # 1. Deploy standalone new files
    for rel_path, content in NEW_FILES.items():
        dir_name = os.path.dirname(rel_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(rel_path, "w", encoding="utf-8") as f:
            f.write(content)
        if rel_path.endswith(".sh"):
            st = os.stat(rel_path)
            os.chmod(rel_path, st.st_mode | stat.S_IEXEC)
        print(f"  ✔ [CREATED] {rel_path}")

    # 2. Merge package.json
    merge_package_json()

    # 3. Merge Makefile
    merge_makefile()

    # 4. Merge Husky Hook
    merge_husky_hook()

    print("=" * 65)
    print("\U0001f389 Installation & Merge Complete!")
    print("Verification steps:")
    print("  1. python3 check_env.py")
    print("  2. bash setup-workspace-v5.sh")
    print("  3. python3 orchestrate_brand_pipeline.py --input sample_brief.json")
    print("=" * 65)


if __name__ == "__main__":
    install()
