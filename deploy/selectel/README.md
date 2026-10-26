# Pulse on Selectel

Production: `135.106.211.53`, HTTPS `sarma-crm.ru`. Guide shares this host.

## GitHub configuration

In **lakalyut/sarma-crm → Settings → Secrets and variables → Actions**:

- `SELECTEL_SSH_PRIVATE_KEY`: the dedicated unencrypted Actions key already used
  by Guide on Selectel. Do not use the old Yandex key or paste any key in chat.
- `PULSE_BACKUP_PASSPHRASE`: at least 32 characters; generate a random password
  (on Mac: `openssl rand -base64 48 | pbcopy`) and save it in a password manager
  as well as GitHub. Losing it makes encrypted backups unusable.

No production `.env` belongs in Git. Existing `/root/sarma-crm/.env` is retained.
SSH verifies the ECDSA fingerprint previously confirmed on the host.

Before enabling, run **Pulse encrypted backup** on the setup branch and download
its encrypted artifact. After merging to main, successful CI triggers deployment.
Manual **Deploy (sarma-crm)** accepts main only; use it after a successful CI run.
Old VPS secrets are no longer used by deploy/storage schedules. Legacy manual
VPS recover workflows still target the old host and must not be used for Selectel.

## Deploy behavior

All Pulse operations share the `pulse-selectel` GitHub concurrency group.
An encrypted off-server backup must be successfully restore-tested and uploaded
before production deployment starts. The checked CI SHA is archived and delivered
to `/root/pulse-releases/<sha>`; server Git credentials are unnecessary.
The image builds while the previous app runs. After stopping the old app, a
second local backup is made before Alembic migrations. Only `web` is recreated.
The existing PostgreSQL container, volume and shared nginx are not recreated.
The proxy reaches the app using the `pulse-web` alias on `guide_bot_default`.
Pulse and Guide HTTPS readiness checks must both succeed.

Successful deployments update `/root/pulse-current` and
`/root/sarma-crm/.deploy-revision`. `/root/sarma-crm` contains the original recovery
checkout and the live `.env`; do not deploy using its old Compose configuration.
To run commands against current code:

```bash
cd /root/pulse-current
export PULSE_IMAGE="pulse-web:$(cat /root/sarma-crm/.deploy-revision)"
docker compose -p sarma-crm --env-file /root/sarma-crm/.env \
  -f deploy/selectel/compose.yml ps
```

If cutover fails, the script attempts to restart the prior image. It never
restores an older database automatically: schema-incompatible migrations can
require manual recovery. Both old images and release directories are retained;
monitor storage through **Selectel storage diagnostics**. No global Docker prune
runs on this shared host. The recovery announcement `pulse-restored-2026-10-26` is imported and queued once after HTTPS checks pass. The existing update sender respects user opt-outs; delivery status appears in `/admin/updates`.

## Backups and restore

**Pulse encrypted backup** runs daily at 03:40 Asia/Irkutsk (19:40 UTC previous
day); GitHub schedules can be delayed. It can also be run manually. Both this
workflow and every deployment upload `pulse-backup-<run>-<attempt>` artifacts,
retained for 30 days. Download and retain additional copies for longer history.
Local root-only archives in `/root/pulse-backups` are retained for at least 14 days.
Their SQL dump uses a consistent PostgreSQL snapshot. `.env`, source revision
when recorded, and proxy/app Compose settings are included.

Every external backup is restored into a disposable PostgreSQL 16 container on
the GitHub runner, then encrypted with GPG AES256. An actual decryption and byte
comparison verifies encryption before upload. Only ciphertext becomes an artifact.
Plaintext and SSH files are removed from the runner even on failure. Check Actions
failures/notification settings: missing secrets, SSH or artifact failures block
backup/deployment; a schedule alone does not prove a backup was created.

On a trusted machine with GPG installed, decrypt (enter password interactively):

```bash
umask 077
gpg --output pulse-backup.tar.gz --decrypt pulse-backup.tar.gz.gpg
mkdir pulse-backup
tar -xzf pulse-backup.tar.gz -C pulse-backup
(cd pulse-backup && shasum -a 256 -c SHA256SUMS)
```

Restore `database.dump` first into an empty **separate** PostgreSQL 16 database:
`pg_restore --no-owner --no-acl --exit-on-error --single-transaction -U <role> -d <database> database.dump`.
The environment file contains real secrets: do not print it or upload it to issues.
Do not overwrite the live database without a tested recovery plan and a fresh backup.
