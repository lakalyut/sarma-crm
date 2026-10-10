import os
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/vps-recover.yml"


@pytest.mark.parametrize("mode", ["cache-prune", "cache-prune-all"])
@pytest.mark.parametrize("fail_health", [False, True])
def test_cache_cleanup_mode(tmp_path, mode, fail_health):
    workflow = yaml.safe_load(WORKFLOW.read_text())
    script = workflow["jobs"]["recover"]["steps"][0]["with"]["script"]
    script = script.replace("${{ github.event.inputs.mode }}", mode)
    script = script.replace("cd /home/ubuntu/sarma-crm", f"cd {tmp_path}")
    mock_path = tmp_path / "bin"
    mock_path.mkdir()
    calls = tmp_path / "calls"
    for command in ("sudo", "curl", "df"):
        mock = mock_path / command
        mock.write_text(
            "#!/bin/bash\n"
            'printf "%s %s\\n" "${0##*/}" "$*" >> "$CACHE_TEST_CALLS"\n'
            'if [[ "${0##*/}" == curl && "$FAIL_HEALTH" == 1 ]]; then exit 60; fi\n'
            'if [[ "${0##*/}" == df ]]; then printf "Avail\\n2000000000\\n"; fi\n'
        )
        mock.chmod(0o755)
    result = subprocess.run(
        ["bash", "-c", script],
        env={
            **os.environ,
            "PATH": f"{mock_path}:{os.environ['PATH']}",
            "CACHE_TEST_CALLS": str(calls),
            "FAIL_HEALTH": str(int(fail_health)),
        },
        text=True,
        capture_output=True,
    )
    commands = calls.read_text().splitlines()
    prune = [command for command in commands if "builder prune" in command]
    if fail_health:
        assert result.returncode == 60
        assert not prune
        return
    assert result.returncode == 0, result.stderr
    expected = "sudo docker builder prune --all --force"
    if mode == "cache-prune":
        expected += " --filter until=168h"
    assert prune == [expected]
    for endpoint in ("https://sarma-crm.ru/ready", "https://guide-crm.ru/"):
        probes = [command for command in commands if endpoint in command]
        assert len(probes) == 2
        assert all("--resolve" in probe and "--fail" in probe for probe in probes)
    assert not any(
        token in command
        for command in commands
        for token in ("system prune", "volume prune", "image prune", "up -d", "restart")
    )
