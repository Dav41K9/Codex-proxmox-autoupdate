#!/usr/bin/env bash
# Repair only timer state recorded by this updater. No APT/Docker/WOL/power actions.
set -uo pipefail
umask 077
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
LIB=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
CONFIG=/etc/update-guests.conf
((EUID==0)) || exit 2
[[ -f "$CONFIG" && ! -L "$CONFIG" && $(stat -c %u "$CONFIG") == 0 && -z $(find "$CONFIG" -perm /022 -print) ]] || exit 2
source "$CONFIG"
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
declare -p SSH_OPTS >/dev/null 2>&1 || SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)
declare -p VM_SSH_TARGETS >/dev/null 2>&1 || VM_SSH_TARGETS=()
[[ ! -L /var/lock/update-guests.lock ]] || exit 2
exec 9>/var/lock/update-guests.lock
flock -n 9 || { echo 'Un job e ancora in corso: recupero rinviato, nessun processo interrotto';exit 75; }
payload=$(base64 -w0 "$LIB/guard.py") || exit 1
code="import base64;exec(compile(base64.b64decode('$payload'),'<maintenance-guard>','exec'))"
failed=0
repair_host(){
    if [[ -f /var/lib/proxmox-maintenance/quarantine.json ]];then
        python3 "$LIB/guard.py" restore && echo 'host: timer ripristinati' || { echo 'FAIL host: recupero timer';failed=1; }
    else echo 'host: nessun timer da recuperare';fi
}
repair_ssh(){
    local target=$1 command rc=0
    # Exact argument quoting; no config/credential contents emitted.
    printf -v command 'test ! -f /var/lib/proxmox-maintenance/quarantine.json || python3 -c %q restore' "$code"
    ssh -n "${SSH_OPTS[@]}" "$target" "$command" || rc=$?
    if ((rc));then echo "FAIL $target: recupero non confermato (SSH/worker/timer)";failed=1
    else echo "$target: controllo/ripristino timer completato";fi
}
repair_host
rows=$(pct list) || exit 1
while read -r id status _;do
    [[ "$id" =~ ^[0-9]+$ ]] || continue
    if [[ "$status" != running ]];then echo "LXC $id: spento, non avviato";continue;fi
    if pct exec "$id" -- test -f /var/lib/proxmox-maintenance/quarantine.json;then
        pct exec "$id" -- python3 -c "$code" restore && echo "LXC $id: timer ripristinati" || { echo "FAIL LXC $id: recupero timer";failed=1; }
    else
        # Distinguish an absent file from an inaccessible guest.
        pct exec "$id" -- true || { echo "FAIL LXC $id: non accessibile";failed=1;continue; }
        echo "LXC $id: nessun timer da recuperare"
    fi
done <<< "$rows"
if [[ ${UPDATE_NODE2:-0} == 1 && -n ${NODE2_IP:-} ]];then
    if ssh -n "${SSH_OPTS[@]}" "root@$NODE2_IP" true >/dev/null 2>&1;then repair_ssh "root@$NODE2_IP"
    elif ping -c 2 -W 2 "$NODE2_IP" >/dev/null 2>&1;then echo 'FAIL nodo2 acceso ma SSH indisponibile';failed=1
    else echo 'nodo2 non raggiungibile: nessun WOL, verifica al prossimo avvio';fi
fi
for target in "${VM_SSH_TARGETS[@]}";do repair_ssh "$target";done
echo 'Recupero concluso: nessun update, reboot o spegnimento. I journal dei guest restano per il recupero del loro stato iniziale.'
exit "$failed"
