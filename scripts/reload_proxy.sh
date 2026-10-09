#!/usr/bin/env bash
# Run from the Sarma checkout on the VPS. Only the shared proxy is reconciled.
set -euo pipefail

sudo docker network inspect guide_bot_default >/dev/null
curl --fail --silent --show-error --connect-timeout 5 --max-time 10 \
  http://127.0.0.1:8000/ >/dev/null

# Validate both domains' certificates and upstream DNS before changing nginx.
# Compose run does not publish ports or start/recreate either application's backend.
sudo docker compose run --rm --no-deps nginx nginx -t
sudo docker compose up -d --no-deps nginx
sudo docker compose exec -T nginx nginx -t
sudo docker compose exec -T nginx nginx -s reload

for endpoint in sarma-crm.ru/ready guide-crm.ru/; do
  domain=${endpoint%%/*}
  curl --fail --silent --show-error --retry 12 --retry-all-errors --retry-delay 2 \
    --connect-timeout 5 --max-time 10 \
    --resolve "${domain}:443:127.0.0.1" "https://${endpoint}" >/dev/null
  printf 'HTTPS verified: %s\n' "$endpoint"
done
