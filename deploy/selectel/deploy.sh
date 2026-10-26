#!/usr/bin/env bash
# Runs on Selectel, from an immutable release directory delivered by Actions.
set -euo pipefail
umask 077
revision=${1:?Expected source revision}
[[ "$revision" =~ ^[0-9a-f]{40}$ ]]
release="/root/pulse-releases/$revision"
[ -f "$release/Dockerfile" ]
[ -s /root/sarma-crm/.env ]
cd "$release"
export PULSE_IMAGE="pulse-web:$revision"
compose=(docker compose -p sarma-crm --env-file /root/sarma-crm/.env -f "$release/deploy/selectel/compose.yml")
"${compose[@]}" config --quiet
# Exact old image retained for recovery; never prune shared Docker resources.
previous_image=$(docker inspect -f '{{.Image}}' sarma-crm-web-1)
docker image inspect "$previous_image" > /dev/null
printf '%s\n' "$previous_image" > "$release/previous-image"
docker build -t "$PULSE_IMAGE" .
docker run --rm --network none "$PULSE_IMAGE" pip check
# Validate ORM connectivity before stopping the live application.
"${compose[@]}" run --rm --no-deps -e TELEGRAM_POLLING_ENABLED=0 web alembic current
cutover=0
rollback() {
  status=$?
  trap - EXIT
  if [ "$status" -ne 0 ] && [ "$cutover" = 1 ]; then
    echo 'Deployment failed; attempting previous application image. Database is not rolled back.' >&2
    export PULSE_IMAGE="$previous_image"
    "${compose[@]}" up -d --no-deps --force-recreate --wait --wait-timeout 180 web || true
  fi
  exit "$status"
}
trap rollback EXIT
cutover=1
docker stop --time 45 sarma-crm-web-1 > /dev/null
# Second local restore point after writes/polling stop, before migrations.
bash deploy/selectel/backup.sh > /dev/null
"${compose[@]}" run --rm --no-deps -e TELEGRAM_POLLING_ENABLED=0 web alembic upgrade head
"${compose[@]}" up -d --no-deps --force-recreate --wait --wait-timeout 180 web
healthy=0
for attempt in $(seq 1 12); do
  if curl --fail --silent --show-error --max-time 10 \
    --resolve sarma-crm.ru:443:127.0.0.1 https://sarma-crm.ru/ready > /dev/null; then
    healthy=1; break
  fi
  sleep 5
done
[ "$healthy" = 1 ]
curl --fail --silent --show-error --max-time 15 \
  --resolve guide-crm.ru:443:127.0.0.1 https://guide-crm.ru/healthz > /dev/null
# Move current pointer only after readiness and shared proxy checks succeeded.
rm -f /root/pulse-current.pending
ln -s "$release" /root/pulse-current.pending
mv -Tf /root/pulse-current.pending /root/pulse-current
printf '%s\n' "$revision" > /root/sarma-crm/.deploy-revision
"${compose[@]}" exec -T web python -m app.publish_recovery_update
cutover=0
echo "Pulse deployment healthy: $revision"
