#!/usr/bin/env bash
set -euo pipefail
umask 077
: "${SELECTEL_SSH_PRIVATE_KEY:?Add SELECTEL_SSH_PRIVATE_KEY repository secret}"
mkdir -p "$RUNNER_TEMP/pulse-ssh"
printf '%s\n' "$SELECTEL_SSH_PRIVATE_KEY" > "$RUNNER_TEMP/pulse-ssh/key"
ssh-keyscan -T 15 -t ecdsa 135.106.211.53 > "$RUNNER_TEMP/pulse-ssh/known_hosts" 2>/dev/null
fingerprint=$(ssh-keygen -lf "$RUNNER_TEMP/pulse-ssh/known_hosts" | awk '{print $2}')
[ "$fingerprint" = SHA256:JVg5F7iyL5xpQ6mJMJhX/zQCWxONtKK/QKx9XYucLYA ] || {
  echo 'Selectel SSH host fingerprint mismatch' >&2; exit 1;
}
cat > "$RUNNER_TEMP/pulse-ssh/config" <<CONFIG
Host pulse-selectel
    HostName 135.106.211.53
    User root
    IdentityFile $RUNNER_TEMP/pulse-ssh/key
    UserKnownHostsFile $RUNNER_TEMP/pulse-ssh/known_hosts
    HostKeyAlgorithms ecdsa-sha2-nistp256
    StrictHostKeyChecking yes
    IdentitiesOnly yes
    BatchMode yes
    ConnectTimeout 20
    ServerAliveInterval 15
    ServerAliveCountMax 4
CONFIG
