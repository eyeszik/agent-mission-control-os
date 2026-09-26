#!/usr/bin/env python3
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
        f.write("\n".join(lines))
    print(f"[SUCCESS] Compiled design tokens -> '{output_css}'")

if __name__ == "__main__":
    compile_tokens()
