#!/usr/bin/env python3
import sys, os, subprocess, shutil, platform

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

    # Capability assurance fingerprint (CARS)
    try:
        from services.langgraph.agency.capability_assurance import environment_fingerprint, check_all  # noqa: E402
        fp = environment_fingerprint()
        caps = check_all()
        print("-" * 65)
        print("Capability Assurance (CARS)")
        for name, cap in caps.items():
            status = cap.get("health", "UNKNOWN")
            icon = "✔" if cap.get("available") else "✘"
            reason = cap.get("reason") or ""
            print(f"  {icon} {name:20s} {status:25s} {reason[:60]}")
        print(f"  fingerprint: {fp.get('operating_system')} | py {fp.get('runtime_versions', {}).get('python')} | db {fp.get('database_engine')}:{fp.get('database_version')}")
        if fp.get("ffprobe_version"):
            print(f"  ffprobe: {fp['ffprobe_version']}")
        else:
            print(f"  ffprobe: NOT FOUND — sudo apt-get install -y ffmpeg")
        if fp.get("tts_engine"):
            print(f"  tts: {fp['tts_engine']} ({fp.get('tts_model')})")
        else:
            print(f"  tts: NOT FOUND — sudo apt-get install -y espeak-ng")
        if fp.get("browser_version"):
            print(f"  browser: {fp['browser_version']}")
        else:
            print(f"  browser: NOT FOUND — pnpm --filter @amc/web exec playwright install chromium")
    except Exception as exc:
        print(f"  (capability fingerprint unavailable: {exc})")

    print("=" * 65)
    print("🎉 Environment pre-flight check complete!")

if __name__ == "__main__":
    check()
