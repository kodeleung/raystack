#!/usr/bin/env bash
set -euo pipefail
# Invoked by the installer with settings in a private temporary JSON file.
config="$1"
project="$2"
if [[ ${EUID} -eq 0 ]]; then SUDO=""; else SUDO="sudo"; fi
${SUDO} install -d -m 700 /etc/raystack /var/lib/raystack/vnstat
${SUDO} install -d -m 755 /usr/local/lib/raystack
${SUDO} install -m 644 "${project}/scripts/traffic.py" "${project}/scripts/client_config.py" "${project}/scripts/subscription_server.py" /usr/local/lib/raystack/
${SUDO} install -m 600 "$config" /etc/raystack/traffic.json
${SUDO} tee /etc/raystack/vnstat.conf >/dev/null <<'CONFIG'
DatabaseDir "/var/lib/raystack/vnstat"
DailyDays 400
PidFile "/run/raystack-vnstat.pid"
TrafficlessEntries 1
CONFIG
zone="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["traffic"]["timezone"])' "$config")"
iface="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["traffic"]["interface"])' "$config")"
${SUDO} tee /etc/systemd/system/raystack-vnstat.service >/dev/null <<UNIT
[Unit]
Description=Raystack traffic accounting
After=network-online.target
[Service]
Environment=TZ=${zone}
ExecStart=/usr/sbin/vnstatd --nodaemon --config /etc/raystack/vnstat.conf
Restart=on-failure
[Install]
WantedBy=multi-user.target
UNIT
${SUDO} tee /etc/systemd/system/raystack-subscription.service >/dev/null <<'UNIT'
[Unit]
Description=Raystack subscription endpoint
After=network.target raystack-vnstat.service
[Service]
ExecStart=/usr/bin/python3 /usr/local/lib/raystack/subscription_server.py /etc/raystack/traffic.json
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
[Install]
WantedBy=multi-user.target
UNIT
# Initialize a fresh database before adding an interface; preserve existing data.
if [[ ! -f /var/lib/raystack/vnstat/vnstat.db ]]; then
  ${SUDO} env TZ="${zone}" vnstatd --config /etc/raystack/vnstat.conf --initdb --noadd
fi
if ! ${SUDO} vnstat --config /etc/raystack/vnstat.conf --iflist 1 2>/dev/null | grep -Fxq "${iface}"; then
  echo "Network interface not found: ${iface}" >&2
  exit 1
fi
if ! ${SUDO} vnstat --config /etc/raystack/vnstat.conf --dbiflist 1 2>/dev/null | grep -Fxq "${iface}"; then
  ${SUDO} vnstat --config /etc/raystack/vnstat.conf --add -i "$iface"
fi
${SUDO} systemctl daemon-reload
${SUDO} systemctl enable --now raystack-vnstat raystack-subscription
${SUDO} systemctl restart raystack-vnstat raystack-subscription
