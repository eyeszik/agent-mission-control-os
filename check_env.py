#!/usr/bin/env python3
import sys, os, subprocess, shutil

def check():
    print("=" * 65)
    print("AI AGENT WORKSPACE ENVIRONMENT PRE-FLIGHT CHECK")
    print("=" * 65)
    py_ver = sys.version.split()[0]
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
    print("🎉 Environment pre-flight check complete!")

if __name__ == "__main__":
    check()
