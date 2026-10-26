#!/usr/bin/env bash
# Executed on the GitHub runner; plaintext never uploaded as an artifact.
set -euo pipefail
umask 077
: "${PULSE_BACKUP_PASSPHRASE:?Add PULSE_BACKUP_PASSPHRASE repository secret}"
[ "${#PULSE_BACKUP_PASSPHRASE}" -ge 32 ] || { echo 'Backup password must contain at least 32 characters'; exit 1; }
work=$(mktemp -d "$RUNNER_TEMP/pulse-export.XXXXXX")
check_container="pulse-backup-check-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
cleanup() {
  docker rm -f "$check_container" >/dev/null 2>&1 || true
  gpgconf --homedir "$work/gnupg" --kill all >/dev/null 2>&1 || true
  rm -rf "$work"
}
trap cleanup EXIT
ssh -F "$RUNNER_TEMP/pulse-ssh/config" pulse-selectel 'bash -s' \
  < deploy/selectel/backup.sh > "$work/backup.tar.gz"
gzip -t "$work/backup.tar.gz"
mkdir "$work/unpacked" "$work/gnupg"
tar -xzf "$work/backup.tar.gz" -C "$work/unpacked"
(cd "$work/unpacked" && sha256sum --check --status SHA256SUMS)
# Restore into a disposable isolated PostgreSQL on the runner, not production.
docker run -d --name "$check_container" --network none \
  -e POSTGRES_HOST_AUTH_METHOD=trust postgres:16 > /dev/null
ready=0
for attempt in $(seq 1 60); do
  if docker exec "$check_container" pg_isready -U postgres >/dev/null 2>&1; then ready=1; break; fi
  sleep 2
done
[ "$ready" = 1 ] || { echo 'Backup restore PostgreSQL failed to start'; exit 1; }
docker exec "$check_container" createdb -U postgres pulse_check
if ! docker exec -i "$check_container" pg_restore -U postgres -d pulse_check \
  --no-owner --no-acl --exit-on-error --single-transaction < "$work/unpacked/database.dump" \
  > "$work/restore.log" 2>&1; then
  echo 'Backup restore failed; database contents and credentials are not printed.' >&2
  exit 1
fi
echo 'PostgreSQL backup restored successfully in isolated verification database.'
printf '%s' "$PULSE_BACKUP_PASSPHRASE" | gpg --homedir "$work/gnupg" \
  --batch --yes --pinentry-mode loopback --passphrase-fd 0 --no-symkey-cache \
  --symmetric --cipher-algo AES256 --output "$work/backup.gpg" "$work/backup.tar.gz"
printf '%s' "$PULSE_BACKUP_PASSPHRASE" | gpg --homedir "$work/gnupg" \
  --batch --yes --pinentry-mode loopback --passphrase-fd 0 --no-symkey-cache \
  --decrypt --output "$work/roundtrip.tar.gz" "$work/backup.gpg"
cmp "$work/backup.tar.gz" "$work/roundtrip.tar.gz"
install -m 600 "$work/backup.gpg" "$RUNNER_TEMP/pulse-backup.tar.gz.gpg"
echo 'Encrypted backup verified and ready for artifact upload.'
