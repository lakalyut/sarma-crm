#!/usr/bin/env bash
# stdout is exclusively the archive; called over SSH by backup/deployment workflows.
set -euo pipefail
umask 077
mkdir -p /root/pulse-backups
chmod 700 /root/pulse-backups
work=$(mktemp -d /root/pulse-backups/.pending.XXXXXX)
trap 'rm -rf "$work"' EXIT
[ -s /root/sarma-crm/.env ]
[ "$(docker inspect -f '{{.State.Running}}' sarma-crm-db-1)" = true ]
docker exec sarma-crm-db-1 sh -c \
  'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$work/database.dump"
docker exec -i sarma-crm-db-1 pg_restore --list < "$work/database.dump" > /dev/null
install -m 600 /root/sarma-crm/.env "$work/pulse.env"
if [ -f /root/sarma-crm/.deploy-revision ]; then
  cp /root/sarma-crm/.deploy-revision "$work/revision.txt"
else
  printf 'Recovered source archive; revision not recorded\n' > "$work/revision.txt"
fi
cp /root/guide_proxy/compose.yml "$work/proxy-compose.yml"
cp /root/guide_proxy/conf.d/pulse.conf "$work/pulse-nginx.conf"
if [ -f /root/pulse-current/deploy/selectel/compose.yml ]; then
  cp /root/pulse-current/deploy/selectel/compose.yml "$work/app-compose.yml"
else
  cp /root/sarma-crm/docker-compose.yml "$work/app-compose.yml"
  cp /root/sarma-crm/compose.selectel.yml "$work/app-override.yml"
fi
(cd "$work" && sha256sum database.dump pulse.env > SHA256SUMS)
archive="/root/pulse-backups/pulse_$(date -u +%Y%m%dT%H%M%S)_${work##*.}.tar.gz"
tar -czf "$archive.partial" -C "$work" .
gzip -t "$archive.partial"
mv "$archive.partial" "$archive"
# Remote local backups retained for 14 days; only our named regular files.
find /root/pulse-backups -maxdepth 1 -type f -name 'pulse_*.tar.gz' -mtime +14 -delete
cat "$archive"
