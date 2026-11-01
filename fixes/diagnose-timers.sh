#!/usr/bin/env bash
# Read-only diagnostic: no source of config, no update, no unmask/start/stop.
set -uo pipefail
probe='python3 - <<'"'"'PY'"'"'
import json,pathlib,subprocess
p=pathlib.Path("/var/lib/proxmox-maintenance/quarantine.json")
print("QUARANTINE")
if p.exists():
    s=json.loads(p.read_text())
    print(json.dumps({k:s.get(k) for k in ("boot","run","complete","units")},indent=2))
else:print("absent")
units=["apt-daily.timer","apt-daily.service","apt-daily-upgrade.timer","apt-daily-upgrade.service","pve-daily-update.timer","pve-daily-update.service","paperless-import.timer","paperless-import.service"]
for u in units:
    print("UNIT",u,flush=True)
    subprocess.run(["systemctl","show",u,"-p","LoadState","-p","ActiveState","-p","SubState","-p","UnitFileState","-p","FragmentPath","-p","Result"])
PY'
printf '\nHOST\n'
bash -c "$probe"
for id in 200 106; do
    printf '\nLXC %s\n' "$id"
    if [[ $(pct status "$id" 2>/dev/null) == 'status: running' ]]; then
        pct exec "$id" -- bash -c "$probe"
    else
        echo 'Guest non running/non accessibile: nessun avvio richiesto'
    fi
done
printf '\nERRORI GUARD NEL LOG HOST (ultimi 40)\n'
if [[ -f /var/log/pve-maintenance.log ]]; then
    grep -E '^(RuntimeError|TimeoutExpired|PermissionError|FileNotFoundError):|Failed to start [A-Za-z0-9_.@-]+\.timer|Unit [A-Za-z0-9_.@-]+ is masked' /var/log/pve-maintenance.log | tail -n 40 || true
fi
printf '\nCRON UPDATER\n'
if [[ -e /etc/cron.d/pve-maintenance ]]; then echo PRESENTE;else echo ASSENTE;fi
