"""Portable launcher contract, with fake executables and no network."""
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[3]


def test_api_launcher_uses_actual_checkout_and_explicit_python(tmp_path):
    repo = tmp_path / 'checkout with spaces'
    scripts = repo / 'infra/run'
    scripts.mkdir(parents=True)
    shutil.copyfile(ROOT / 'infra/run/amc-api.sh', scripts / 'amc-api.sh')
    executable = tmp_path / 'fake-python'
    output = tmp_path / 'observed.json'
    executable.write_text('#!/usr/bin/env python3\nimport json,os,sys\nopen(os.environ["OBSERVED"],"w").write(json.dumps({"cwd":os.getcwd(),"args":sys.argv[1:],"actor":os.environ.get("AMC_LOCAL_USER_ID")}))\n')
    executable.chmod(0o700)
    result = subprocess.run(['bash', str(scripts / 'amc-api.sh')], cwd=tmp_path,
        env={**os.environ, 'AMC_PYTHON_BIN':str(executable), 'OBSERVED':str(output),
             'AMC_LOCAL_USER_ID':'fixture-preserved-owner'}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    observed = json.loads(output.read_text())
    assert observed['cwd'] == str(repo)
    assert observed['args'][:3] == ['-m','uvicorn','services.langgraph.app.main:app']
    assert observed['actor'] == 'fixture-preserved-owner'


def test_web_launcher_never_downloads_next(tmp_path):
    repo = tmp_path / 'relocated repo'
    scripts = repo / 'infra/run'
    scripts.mkdir(parents=True)
    shutil.copyfile(ROOT / 'infra/run/amc-web.sh', scripts / 'amc-web.sh')
    next_bin = repo / 'apps/web/node_modules/.bin/next'
    next_bin.parent.mkdir(parents=True)
    output = tmp_path / 'web-output'
    next_bin.write_text('#!/bin/sh\npwd > "$OBSERVED"\nprintf "%s\\n" "$@" >> "$OBSERVED"\n')
    next_bin.chmod(0o700)
    app_scripts=repo/'apps/web/scripts'
    app_scripts.mkdir()
    shutil.copyfile(ROOT/'apps/web/scripts/start.mjs',app_scripts/'start.mjs')
    (app_scripts/'check-build.mjs').write_text('export function validateBuild() {}')
    next_cli=repo/'apps/web/node_modules/next/dist/bin/next'
    next_cli.parent.mkdir(parents=True)
    next_cli.write_text('const fs=require("node:fs");fs.writeFileSync(process.env.OBSERVED,[process.cwd(),...process.argv.slice(2)].join("\\n"))')
    result = subprocess.run(['bash',str(scripts/'amc-web.sh')], env={**os.environ,'OBSERVED':str(output)}, capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    lines=output.read_text().splitlines()
    assert lines[0]==str(repo/'apps/web')
    assert lines[1]=='start'
    assert '127.0.0.1' in lines
