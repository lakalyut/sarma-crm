"""Exercise deployment failure boundaries with isolated command doubles."""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVISION = "a" * 40


def run_deployment(tmp_path, failure=""):
    root = tmp_path / "root"
    release = root / "pulse-releases" / REVISION
    release.mkdir(parents=True)
    (release / "Dockerfile").touch()
    (root / "sarma-crm").mkdir()
    (root / "sarma-crm/.env").write_text("KEEP_THIS_SECRET=retained\n")
    (release / "deploy/selectel").mkdir(parents=True)
    (release / "deploy/selectel/backup.sh").write_text("#!/bin/bash\nexit 0\n")
    script = tmp_path / "deploy.sh"
    script.write_text(
        (ROOT / "deploy/selectel/deploy.sh")
        .read_text()
        .replace("/root/", str(root) + "/")
    )
    commands = tmp_path / "commands.jsonl"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    mock = bin_dir / "mock"
    mock.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "name=pathlib.Path(sys.argv[0]).name\n"
        "args=sys.argv[1:]\n"
        "with open(os.environ['COMMANDS'], 'a') as f:\n"
        " f.write(json.dumps([name,args,os.environ.get('PULSE_IMAGE')])+'\\n')\n"
        "if name=='docker' and args[:1]==['inspect']: print('sha256:previous')\n"
        "failure=os.environ.get('FAILURE')\n"
        "if failure=='build' and args[:1]==['build']: sys.exit(1)\n"
        "if failure=='migration' and 'upgrade' in args: sys.exit(1)\n"
        "if failure=='readiness' and name=='curl' and 'sarma-crm.ru/ready' in ' '.join(args): sys.exit(1)\n"
    )
    mock.chmod(0o755)
    for command in ("docker", "curl", "sleep"):
        (bin_dir / command).symlink_to(mock)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "COMMANDS": str(commands),
        "FAILURE": failure,
    }
    result = subprocess.run(
        ["bash", str(script), REVISION], env=env, capture_output=True, text=True
    )
    calls = [json.loads(line) for line in commands.read_text().splitlines()]
    assert (root / "sarma-crm/.env").read_text() == "KEEP_THIS_SECRET=retained\n"
    # No database, proxy or other project is stopped, removed or recreated.
    assert not any(call[1][:1] in (["rm"], ["volume"], ["prune"]) for call in calls)
    assert all(
        call[1][-1] == "sarma-crm-web-1" for call in calls if call[1][:1] == ["stop"]
    )
    return root, result, calls


def test_build_failure_keeps_existing_app_running(tmp_path):
    root, result, calls = run_deployment(tmp_path, "build")
    assert result.returncode != 0
    assert not any(call[1][:1] == ["stop"] for call in calls)
    assert not (root / "pulse-current").exists()


def test_migration_failure_attempts_prior_image_without_database_restore(tmp_path):
    root, result, calls = run_deployment(tmp_path, "migration")
    assert result.returncode != 0
    restarts = [call for call in calls if "up" in call[1]]
    assert len(restarts) == 1 and restarts[0][2] == "sha256:previous"
    assert not (root / "pulse-current").exists()


def test_https_failure_returns_to_prior_image(tmp_path):
    root, result, calls = run_deployment(tmp_path, "readiness")
    assert result.returncode != 0
    restarts = [call for call in calls if "up" in call[1]]
    assert [call[2] for call in restarts] == [
        f"pulse-web:{REVISION}",
        "sha256:previous",
    ]
    assert not (root / "sarma-crm/.deploy-revision").exists()


def test_success_records_revision_only_after_https_checks(tmp_path):
    root, result, calls = run_deployment(tmp_path)
    assert result.returncode == 0, result.stderr
    assert (root / "sarma-crm/.deploy-revision").read_text().strip() == REVISION
    assert (root / "pulse-current").resolve() == root / "pulse-releases" / REVISION
    assert any("guide-crm.ru/healthz" in " ".join(call[1]) for call in calls)
