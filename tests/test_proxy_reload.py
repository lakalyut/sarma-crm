import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "reload_proxy.sh"


def run_reload(tmp_path, fail_preflight=False, fail_guide=False):
    bin_path = tmp_path / "bin"
    bin_path.mkdir()
    log = tmp_path / "calls"
    for command in ("sudo", "curl"):
        executable = bin_path / command
        executable.write_text(
            "#!/bin/bash\n"
            'printf "%s\\n" "$*" >> "$PROXY_TEST_LOG"\n'
            'if [[ "$FAIL_PREFLIGHT" == 1 && "$*" == *"run --rm --no-deps nginx nginx -t"* ]]; then exit 1; fi\n'
            'if [[ "$FAIL_GUIDE" == 1 && "$*" == *"https://guide-crm.ru/"* ]]; then exit 60; fi\n'
        )
        executable.chmod(0o755)
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env={
            **os.environ,
            "PATH": f"{bin_path}:{os.environ['PATH']}",
            "PROXY_TEST_LOG": str(log),
            "FAIL_PREFLIGHT": str(int(fail_preflight)),
            "FAIL_GUIDE": str(int(fail_guide)),
        },
        capture_output=True,
        text=True,
    )
    return result, log.read_text().splitlines()


def test_invalid_preflight_preserves_running_proxy(tmp_path):
    result, calls = run_reload(tmp_path, fail_preflight=True)
    assert result.returncode != 0
    assert not any("up -d" in call or "-s reload" in call for call in calls)


def test_reload_updates_only_proxy_and_verifies_both_domains(tmp_path):
    result, calls = run_reload(tmp_path)
    assert result.returncode == 0
    updates = [call for call in calls if "up -d" in call]
    assert updates == ["docker compose up -d --no-deps nginx"]
    assert not any("down" in call or "build" in call for call in calls)
    for url in ("https://sarma-crm.ru/ready", "https://guide-crm.ru/"):
        probe = next(call for call in calls if url in call)
        assert "--retry-all-errors" in probe
        assert "--resolve" in probe
        assert "--insecure" not in probe and " -k" not in probe


def test_guide_tls_failure_fails_recovery(tmp_path):
    result, _ = run_reload(tmp_path, fail_guide=True)
    assert result.returncode == 60
    assert "HTTPS verified: guide-crm.ru/" not in result.stdout
