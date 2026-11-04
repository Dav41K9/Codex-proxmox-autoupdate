#!/usr/bin/env bash
set -uo pipefail
umask 077
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
LIB=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
STATE=/var/lib/proxmox-maintenance
CONFIG=/etc/update-guests.conf
RUN_ID=$(date -u +%Y%m%d-%H%M%S)-$$
SCOPE=${1:?scope};shift
DRY=0;RETRY=0;SCHEDULED=0;NO_TELEGRAM=0;CLAIMED=0;FINAL=0
for arg in "$@";do case "$arg" in --dry-run) DRY=1;;--retry) RETRY=1;;--scheduled) SCHEDULED=1;;--no-telegram) NO_TELEGRAM=1;;*) exit 2;;esac;done
((EUID==0)) || exit 2
[[ -f "$CONFIG" && ! -L "$CONFIG" && $(stat -c %u "$CONFIG") == 0 && -z $(find "$CONFIG" -perm /022 -print) ]] || { echo 'Configurazione mancante/non privata';exit 2; }
# shellcheck disable=SC1090
source "$CONFIG"
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
: "${UPDATE_HOST:=1}" "${UPDATE_NODE2:=0}" "${NODE2_IP:=}" "${NODE2_MAC:=}" "${NODE2_WOL_BROADCAST:=255.255.255.255}"
: "${NODE2_STOP_AFTER:=1}" "${START_STOPPED_LXC:=1}" "${STOP_LXC_STARTED_BY_SCRIPT:=1}" "${CREATE_SNAPSHOTS:=1}"
: "${WEB_COMPOSE_DIR:=/home/3dft/3dft-wordpress}" "${WEB_HTTP_HOST:=3dfactoryticino.ch}" "${NAS_MOUNT:=/mnt/pve/NAS}"
: "${NAS_PERMISSION_MODE:=private}"
: "${SEND_TELEGRAM:=0}" "${COMPOSE_WAIT_SECONDS:=240}" "${APT_TIMEOUT:=3600}" "${DOCKER_PRUNE:=1}" "${STANDALONE_MODE:=watchtower}"
declare -p DOCKER_SKIP_IDS >/dev/null 2>&1 || DOCKER_SKIP_IDS=(1000)
declare -p SNAPSHOT_SKIP_IDS >/dev/null 2>&1 || SNAPSHOT_SKIP_IDS=(106)
declare -p LXC_IDS >/dev/null 2>&1 || LXC_IDS=()
declare -p VM_SSH_TARGETS >/dev/null 2>&1 || VM_SSH_TARGETS=()
declare -p SSH_OPTS >/dev/null 2>&1 || SSH_OPTS=(-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o StrictHostKeyChecking=accept-new)
declare -p LXC_COMPOSE_DIRS >/dev/null 2>&1 || declare -A LXC_COMPOSE_DIRS=()
[[ "$SCOPE" == proxmox || "$SCOPE" == wordpress ]] || exit 2
[[ "$COMPOSE_WAIT_SECONDS" =~ ^[1-9][0-9]{0,4}$ && "$APT_TIMEOUT" =~ ^[1-9][0-9]{0,5}$ ]] || exit 2
for id in "${LXC_IDS[@]}";do [[ "$id" =~ ^[0-9]+$ ]] || exit 2;done
[[ "$NAS_MOUNT" == /* && "$NAS_MOUNT" != / ]] || exit 2
case "$NAS_PERMISSION_MODE" in private|server-acl) ;;*) echo 'NAS_PERMISSION_MODE non valido';exit 2;;esac
if ((DRY)) || [[ ${DRY_RUN:-0} == 1 ]];then echo "DRY RUN $SCOPE: nessuna modifica; snapshot200=2+3; NAS=60giorni; Hermes import rinviato";exit 0;fi
LOG=/var/log/pve-maintenance.log
store(){ python3 "$LIB/state.py" "$STATE" "$@"; }
event(){ store event "$RUN_ID" "$1" "$2" "$3" || exit 1;printf '%s %s %s\n' "$1" "$2" "$3" | tee -a "$LOG"; }
action(){ event ACTION "$1" "$2 - INTERVENTO MANUALE RICHIESTO"; }
telegram(){
    [[ "$SEND_TELEGRAM" == 1 && "$NO_TELEGRAM" == 0 ]] || return 0
    [[ -n ${TELEGRAM_BOT_TOKEN:-} && -n ${TELEGRAM_CHAT_ID:-} ]] || return 1
    local chunks chunk encoded response
    chunks=$(printf '%s' "$1" | python3 -c 'import sys,base64;s=sys.stdin.read();print("\n".join(base64.b64encode(s[i:i+1800].encode()).decode() for i in range(0,len(s),1800)))') || return 1
    while IFS= read -r encoded;do
        [[ -n "$encoded" ]] || continue
        chunk=$(printf '%s' "$encoded" | base64 -d && printf '.');chunk=${chunk%.}
        response=$(curl -fsS --connect-timeout 10 --max-time 30 -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" --data-urlencode "text=$chunk" 2>/dev/null) || return 1
        printf '%s' "$response" | python3 -c 'import json,sys;sys.exit(json.load(sys.stdin).get("ok") is not True)' || return 1
    done <<< "$chunks"
}
state(){ local s;s=$(pct status "$1" 2>/dev/null) || s=unknown;case "$s" in 'status: running') echo running;;'status: stopped') echo stopped;;*) echo unknown;;esac; }
remote(){ local kind=$1 target=$2;shift 2;case "$kind" in lxc) pct exec "$target" -- "$@";;host) "$@";;*) local cmd;printf -v cmd '%q ' "$@";ssh -n "${SSH_OPTS[@]}" "$target" "$cmd";;esac; }
node_online(){ ping -c 2 -W 2 "$1" >/dev/null 2>&1 || remote ssh "root@$1" true >/dev/null 2>&1; }
parse(){
    local target=$1 data=$2 expected=${3:-$RUN_ID} historical=${4:-0} line type msg runs=0 complete=0 failures=0 warnings=0 valid=1
    STATUS_COMPLETE=0;STATUS_REBOOT=0;STATUS_FAIL=0
    while IFS= read -r line;do
        [[ -n "$line" ]] || continue
        ((complete==0)) || valid=0
        type=${line%%|*};msg=${line#*|}
        case "$type" in
          RUN) runs=$((runs+1));[[ "$msg" == "$expected" ]] || valid=0;;
          COMPLETE) complete=$((complete+1));[[ "$msg" == "failures=$failures warnings=$warnings" ]] || valid=0;;
          FAIL) failures=$((failures+1));((historical)) || event FAIL "$target" "$msg";;
          WARN) warnings=$((warnings+1));((historical)) || event WARN "$target" "$msg";;
          NOTE) ((historical)) || event NOTE "$target" "$msg";;
          REBOOT) STATUS_REBOOT=1;((historical)) || event REBOOT "$target" "$msg";;
          REBOOT_ADVICE) ((historical)) || event REBOOT "$target" "$msg (host/VM: nessun reboot automatico)";;
          *) valid=0;;
        esac
    done <<< "$data"
    if ((runs==1 && complete==1 && valid));then STATUS_COMPLETE=1;elif ((historical));then event WARN "$target" 'Run precedente incompleto: recupero stato, non ripetizione degli aggiornamenti';else event FAIL "$target" 'Status incompleto/non valido';fi
    ((STATUS_COMPLETE && failures==0)) || STATUS_FAIL=1
}
deploy(){
    remote "$1" "$2" bash -c 'set -e;umask 077;for d in /var/lib/proxmox-maintenance /var/lib/proxmox-maintenance/runtime "$1";do test ! -L "$d";if test -e "$d";then test "$(stat -c %u "$d")" = 0;test -z "$(find "$d" -maxdepth 0 -perm /022 -print)";else install -d -m0700 -o root -g root "$d";fi;done;printf %s "$2" | base64 -d | tar -xzf - -C "$1"' bash "$DIR" "$BUNDLE" >>"$LOG" 2>&1
}
worker(){
    local kind=$1 id=$2 mode=$3 dirs='' encoded envline rc=0 worker_run=$RUN_ID skip=0 x
    STATUS_COMPLETE=0;STATUS_REBOOT=0;STATUS_FAIL=1
    for x in "${DOCKER_SKIP_IDS[@]}";do [[ "$x" != "$id" ]] || skip=1;done
    [[ "$id" != 200 || "$mode" != docker ]] || skip=0
    [[ "$mode" != health ]] || worker_run="$RUN_ID-health"
    if [[ "$kind" == lxc ]];then dirs=${LXC_COMPOSE_DIRS[$id]:-};[[ "$id" != 200 ]] || dirs=$WEB_COMPOSE_DIR;fi
    encoded=$(printf '%s' "$dirs" | python3 -c 'import sys,shlex,base64;s=sys.stdin.read();v=s.splitlines() if "\n" in s else shlex.split(s);print(base64.b64encode("\n".join(v).encode()).decode())') || return 1
    printf -v envline 'RUN_ID=%q KIND=%q GUEST_ID=%q MODE=%q COMPOSE_DIRS_B64=%q WEB_COMPOSE_DIR=%q APT_TIMEOUT=%q COMPOSE_WAIT_SECONDS=%q DOCKER_PRUNE=%q STANDALONE_MODE=%q SKIP_DOCKER=%q bash %q' "$worker_run" "$kind" "$id" "$mode" "$encoded" "$WEB_COMPOSE_DIR" "$APT_TIMEOUT" "$COMPOSE_WAIT_SECONDS" "$DOCKER_PRUNE" "$STANDALONE_MODE" "$skip" "$DIR/pve-guest-worker.sh"
    event NOTE "$kind $id" "Avvio fase $mode; attendo il completamento"
    remote "$kind" "$id" bash -c "$envline </dev/null" 2>&1 | tee -a "$LOG" || rc=$?
    local data;data=$(remote "$kind" "$id" cat "$STATE/worker-status/$worker_run.status" 2>/dev/null) || data=''
    parse "$kind $id" "$data" "$worker_run"
    ((rc==0)) || event FAIL "$kind $id" "Worker rc=$rc"
    ((rc==0 && STATUS_COMPLETE && !STATUS_FAIL))
}
wait_guest(){
    local id=$1 boot_state attempt
    for ((attempt=0;attempt<40;attempt++));do
        boot_state=$(remote lxc "$id" systemctl is-system-running 2>/dev/null) || true
        case "$boot_state" in running|degraded) return 0;;esac
        sleep 3
    done
    return 1
}
power(){
    local id=$1 mode=$2 token="$RUN_ID-$RANDOM" pid ready=0 before after result=0
    before=$(remote lxc "$id" cat /proc/sys/kernel/random/boot_id 2>/dev/null) || return 1
    remote lxc "$id" python3 "$DIR/guard.py" hold "$token" 9>&- >>"$LOG" 2>&1 & pid=$!
    for ((n=0;n<15;n++));do
        if remote lxc "$id" python3 "$DIR/guard.py" ready "$token" >/dev/null 2>&1;then ready=1;break;fi
        kill -0 "$pid" 2>/dev/null || break;sleep 1
    done
    if ((ready));then
        if ! pct "$mode" "$id" --timeout 120 >>"$LOG" 2>&1;then result=1;fi
        if [[ "$mode" == reboot && "$result" == 0 ]];then
            result=1
            for ((n=0;n<40;n++));do
                after=$(remote lxc "$id" cat /proc/sys/kernel/random/boot_id 2>/dev/null) || after=''
                if [[ -n "$after" && "$after" != "$before" ]];then if wait_guest "$id";then result=0;fi;break;fi;sleep 3
            done
        elif [[ "$mode" == shutdown && $(state "$id") != stopped ]];then result=1;fi
    else result=1;fi
    # Kill only the bounded helper/client, never worker or package transactions.
    remote lxc "$id" python3 -c 'import json,os,signal,sys,pathlib;p=pathlib.Path(sys.argv[1]);s=json.loads(p.read_text());raw=pathlib.Path("/proc/"+str(s["pid"])+"/cmdline").read_bytes();assert sys.argv[2].encode() in raw.split(b"\0") and b"hold" in raw.split(b"\0");os.kill(s["pid"],signal.SIGTERM)' "$STATE/ready-$token" "$token" >/dev/null 2>&1 || true
    kill "$pid" 2>/dev/null || true;wait "$pid" 2>/dev/null || true
    return "$result"
}
restore_guest(){
    local id=$1 initial=$2 owned=$3
    if [[ $(state "$id") == stopped ]];then store close "$id";return;fi
    if ! deploy lxc "$id";then action "LXC $id" 'Stato non ripristinato: guest non accessibile';return 1;fi
    if [[ "$initial" == stopped && "$owned" != 1 ]];then
        remote lxc "$id" python3 "$DIR/guard.py" restore || true
        action "LXC $id" 'Acceso ma ownership avvio incerta';return 1
    fi
    if [[ "$initial" == stopped && "$STOP_LXC_STARTED_BY_SCRIPT" == 1 ]];then
        if ! remote lxc "$id" python3 "$DIR/guard.py" idle >/dev/null 2>&1;then
            remote lxc "$id" python3 "$DIR/guard.py" restore || true
            action "LXC $id" 'Rimane acceso: transazione, worker o import attivo';return 1
        fi
        if ! power "$id" shutdown;then
            remote lxc "$id" python3 "$DIR/guard.py" restore || true
            action "LXC $id" 'Rimane acceso: shutdown non confermato';return 1
        fi
    else remote lxc "$id" python3 "$DIR/guard.py" restore || { action "LXC $id" 'Ripristino timer fallito';return 1; };fi
    if [[ "$id" == 1000 && $(state "$id") == running ]];then remote lxc "$id" rm -f /var/lib/proxmox-maintenance-import/maintenance.active || return 1;fi
    store close "$id"
}

snapshots(){
    local op=$1 id=$2 prefix=pre-update raw name keep skipid
    for skipid in "${SNAPSHOT_SKIP_IDS[@]}";do [[ "$skipid" != "$id" ]] || return 0;done
    [[ "$id" != 106 && "$CREATE_SNAPSHOTS" == 1 ]] || return 0
    [[ "$SCOPE" != wordpress ]] || prefix=pre-web-update
    if [[ "$op" == create ]];then
        pct snapshot "$id" "$prefix-$(date +%Y%m%d-%H%M%S)" >>"$LOG" 2>&1 || event WARN "LXC $id" 'Snapshot fallito; update prosegue'
    fi
    raw=$(pct listsnapshot "$id" 2>/dev/null) || { event WARN "LXC $id" 'Elenco snapshot fallito';return; }
    local -a names=() prefixes=(pre-update)
    [[ "$id" != 200 ]] || prefixes+=(pre-web-update)
    for prefix in "${prefixes[@]}";do
        keep=2;[[ "$prefix" != pre-web-update ]] || keep=3
        mapfile -t names < <(printf '%s\n' "$raw" | grep -oE "$prefix-[0-9]{8}-[0-9]{6}" | sort -u)
        for ((n=0;n<${#names[@]}-keep;n++));do name=${names[n]};pct delsnapshot "$id" "$name" >>"$LOG" 2>&1 || event WARN "LXC $id" "Cancellazione $name fallita";done
    done
}
update_lxc(){
    local id=$1 initial owned=0 mode=full
    if [[ -n ${BLOCKED[$id]:-} ]];then action "LXC $id" 'Recupero precedente irrisolto';return;fi
    initial=$(state "$id")
    [[ "$initial" == running || "$initial" == stopped ]] || { event FAIL "LXC $id" 'Stato sconosciuto';return; }
    [[ "$initial" != stopped || "$START_STOPPED_LXC" == 1 ]] || { event WARN "LXC $id" 'Spento: escluso';return; }
    store guest "$id" "$RUN_ID" "$initial" 0 intent || exit 1
    if [[ "$initial" == stopped ]];then
        if pct start "$id" >>"$LOG" 2>&1;then owned=1;store guest "$id" "$RUN_ID" "$initial" 1 started || exit 1
        else event FAIL "LXC $id" 'Start fallito';restore_guest "$id" "$initial" 0 || true;return;fi
        if ! wait_guest "$id";then event FAIL "LXC $id" 'Avvio non pronto entro attesa';restore_guest "$id" "$initial" "$owned" || true;return;fi
    fi
    if ! deploy lxc "$id";then event FAIL "LXC $id" 'Deploy fallito';restore_guest "$id" "$initial" "$owned" || true;return;fi
    event NOTE "LXC $id" "Inizio manutenzione; stato iniziale $initial"
    snapshots create "$id"
    [[ "$id" != 200 ]] || mode=apt
    [[ "$SCOPE" != wordpress ]] || mode=docker
    store guest "$id" "$RUN_ID" "$initial" "$owned" worker || exit 1
    worker lxc "$id" "$mode" || true
    if ((STATUS_COMPLETE && STATUS_REBOOT));then
        if power "$id" reboot;then
            store guest "$id" "$RUN_ID" "$initial" "$owned" rebooted || exit 1
            event REBOOT "LXC $id" 'Reboot completo verificato da boot_id'
            worker lxc "$id" health || true
        else action "LXC $id" 'Reboot non confermato';fi
    fi
    snapshots cleanup "$id"
    restore_guest "$id" "$initial" "$owned" || true
}
web_health(){
    local code=000 public=000 i
    event NOTE WordPress 'Verifica homepage locale e HTTPS pubblico'
    for ((i=0;i<18;i++));do
        code=$(remote lxc 200 curl -sS -o /dev/null -w '%{http_code}' --connect-timeout 4 --max-time 10 -H "Host: $WEB_HTTP_HOST" http://127.0.0.1:8080/ 2>/dev/null) || code=000
        if [[ "$code" == 200 ]];then
            public=$(curl -sS -L --max-redirs 5 --proto '=https' --proto-redir '=https' --connect-timeout 5 --max-time 20 -o /dev/null -w '%{http_code}' "https://$WEB_HTTP_HOST/" 2>/dev/null) || public=000
            [[ "$public" != 200 ]] || { event NOTE WordPress 'Homepage locale200 e HTTPS pubblico200; checkout non certificato';return; }
        fi
        sleep 5
    done
    action WordPress "Check homepage fallito: locale=$code pubblico=$public; disponibilita sito non confermata"
}

finish(){
    local result body pid done=0 archive_reason
    result=$(store finish "$RUN_ID") || return 1
    FINAL=1
    body=$(store summary "$RUN_ID") || body='FAIL lettura riepilogo'
    store archive "$NAS_MOUNT" "${NAS_PERMISSION_MODE:-private}" 9>&- >"$STATE/archive.log" 2>&1 & pid=$!
    for ((i=0;i<45;i++));do kill -0 "$pid" 2>/dev/null || { done=1;break; };sleep 1;done
    if ((done)) && wait "$pid";then :;else
        kill "$pid" 2>/dev/null || true
        [[ "$result" == FAIL\|* ]] || result="WARN|${result#*|}"
        archive_reason=$(tail -n 1 "$STATE/archive.log" 2>/dev/null) || archive_reason=''
        archive_reason=${archive_reason//$'\r'/ }
        body+=$'\nWARN archivio NAS: report in coda locale. '
        body+="${archive_reason:0:160}"
        [[ -n "$archive_reason" ]] || body+='Attesa scaduta; verificare mount e archive.log'
        printf '%s ARCHIVE_PENDING\n' "$RUN_ID" >>"$STATE/delivery.log"
    fi
    printf 'Report: %s/reports/%s\n' "$STATE" "${result#*|}"
    telegram "[$SCOPE] ${result%%|*}"$'\n'"$body"$'\n'"Run: $RUN_ID" || { printf '%s TELEGRAM_FAILED\n' "$RUN_ID" >>"$STATE/delivery.log";echo 'FAIL invio Telegram; report conservato su host';return 1; }
    if [[ "$SEND_TELEGRAM" == 1 && "$NO_TELEGRAM" == 0 ]];then
        store reminder-delivered "$RUN_ID" || { echo 'WARN ricevuta promemoria non salvata: potrebbe ripetersi';return 1; }
    fi
    printf 'FINE %s: %s (run %s)\n' "$SCOPE" "${result%%|*}" "$RUN_ID"
    [[ "$result" != FAIL\|* ]]
}
on_exit(){
    local rc=$1 pending id owner initial owned phase
    trap - EXIT TERM INT HUP
    if ((CLAIMED && !FINAL));then
        event FAIL orchestratore "Uscita anticipata rc=$rc"
        if [[ ${node_owned:-0} == 1 ]];then action nodo2 'Run interrotto: nodo avviato dal job, stato da verificare';fi
        pending=$(store pending) || pending=''
        while IFS='|' read -r id owner initial owned phase;do [[ -n "$id" && "$owner" == "$RUN_ID" ]] || continue;restore_guest "$id" "$initial" "$owned" || true;done <<< "$pending"
        finish || true
    fi
    exit "$rc"
}
for bin in python3 pct ssh ping flock tar base64 curl findmnt;do command -v "$bin" >/dev/null || exit 2;done
[[ ! -L /var/lock/update-guests.lock ]] || exit 2
exec 9>/var/lock/update-guests.lock
if ((SCHEDULED));then
    flock -w 21600 9 || { telegram 'FAIL lock manutenzione occupato oltre 6 ore';exit 75; }
else
    flock -n 9 || { echo 'Manutenzione gia in corso: nessun secondo job avviato';exit 75; }
fi
rc=0;store begin "$RUN_ID" "$SCOPE" "$(date +%F)" "$(( !SCHEDULED || RETRY ))" || rc=$?
((rc!=75)) || { echo 'Job cron gia registrato oggi: duplicato evitato. Per una nuova prova eseguire lo script manualmente senza --scheduled';exit 0; }
((rc==0)) || exit 1
CLAIMED=1;trap 'on_exit $?' EXIT;trap 'exit 143' TERM HUP;trap 'exit 130' INT
printf 'INIZIO %s - run %s\n' "$SCOPE" "$RUN_ID" | tee -a "$LOG"
DIR="$STATE/runtime/$RUN_ID"
BUNDLE=$(tar -C "$LIB" -czf - pve-guest-worker.sh guard.py docker-maint.py agent-migrate.py | base64 -w0) || exit 1
declare -A BLOCKED=()
pending=$(store pending) || exit 1
while IFS='|' read -r id owner initial owned phase;do
    [[ -n "$id" ]] || continue
    if [[ "$SCOPE" == wordpress && "$id" != 200 ]];then
        event WARN "LXC $id" 'Recupero pendente lasciato al job generale; nessuna azione su questo guest'
        continue
    fi
    event WARN "LXC $id" "Recupero stato iniziale della run $owner (non nuovi update)"
    if [[ "$phase" != rebooted && $(state "$id") == running ]] && deploy lxc "$id";then
        previous=$(remote lxc "$id" cat "$STATE/worker-status/$owner.status" 2>/dev/null) || previous=''
        parse "LXC $id recupero" "$previous" "$owner" 1
        if ((STATUS_COMPLETE && STATUS_REBOOT));then
            if ! power "$id" reboot;then action "LXC $id" 'Reboot pendente non completato';BLOCKED[$id]=1;continue;fi
        fi
    fi
    restore_guest "$id" "$initial" "$owned" || BLOCKED[$id]=1
done <<< "$pending"
unfinished=$(store unfinished "$RUN_ID" "$SCOPE") || exit 1
while IFS= read -r owner;do [[ -n "$owner" ]] || continue;store event "$owner" FAIL orchestratore 'Run interrotto; recupero nel report successivo';store finish "$owner" >/dev/null || exit 1;done <<< "$unfinished"
oldnodes=''
if [[ "$SCOPE" == proxmox ]];then oldnodes=$(store nodes) || exit 1;fi
while IFS='|' read -r owner ip;do
    [[ -n "$owner" ]] || continue
    if ping -c 2 -W 2 "$ip" >/dev/null 2>&1 || remote ssh "root@$ip" true >/dev/null 2>&1;then action nodo2 'Nodo acceso dopo job interrotto: lasciato acceso per verifica manuale';fi
    store node "$owner" "$ip" manual || exit 1
done <<< "$oldnodes"
node_ready=0;node_owned=0
if [[ "$SCOPE" == proxmox && "$UPDATE_NODE2" == 1 && -z "$NODE2_IP" ]];then
    event FAIL nodo2 'NODE2_IP mancante: nessun contatto o WOL';UPDATE_NODE2=0
fi
if [[ "$SCOPE" == proxmox && "$UPDATE_NODE2" == 1 ]];then
    if node_online "$NODE2_IP";then event NOTE nodo2 'Gia acceso: non verra spento'
    elif store node "$RUN_ID" "$NODE2_IP" wol-intent && [[ -n "$NODE2_MAC" ]] && wakeonlan -i "$NODE2_WOL_BROADCAST" "$NODE2_MAC" >>"$LOG" 2>&1;then node_owned=1;store node "$RUN_ID" "$NODE2_IP" owned || exit 1;event NOTE nodo2 'WOL inviato dopo ping/SSH negativi'
    else event FAIL nodo2 'WOL fallito/non configurato';store node "$RUN_ID" "$NODE2_IP" manual || exit 1;fi
    for ((i=0;i<24;i++));do if remote ssh "root@$NODE2_IP" true >/dev/null 2>&1;then node_ready=1;break;fi;sleep 5;done
    ((node_ready)) || action nodo2 'SSH non disponibile; controllare stato'
fi
if [[ "$SCOPE" == proxmox ]];then
    if [[ "$UPDATE_HOST" == 1 ]];then if deploy host '';then worker host '' full || true;else event FAIL host 'Deploy fallito';fi;fi
    if ((node_ready));then
        if deploy ssh "root@$NODE2_IP" && worker node2 "root@$NODE2_IP" full;then
            if ((node_owned)) && [[ "$NODE2_STOP_AFTER" == 1 ]];then
                remote ssh "root@$NODE2_IP" python3 "$DIR/guard.py" shutdown "$RUN_ID" >>"$LOG" 2>&1 || true
                off=0
                for ((i=0;i<24;i++));do if ! ping -c 2 -W 2 "$NODE2_IP" >/dev/null 2>&1 && ! remote ssh "root@$NODE2_IP" true >/dev/null 2>&1;then off=1;break;fi;sleep 5;done
                if ((off));then store node "$RUN_ID" "$NODE2_IP" closed || exit 1;event NOTE nodo2 "Aggiornato e spento dopo WOL";else action nodo2 'Ancora acceso dopo richiesta shutdown';store node "$RUN_ID" "$NODE2_IP" manual || exit 1;fi
            elif ((node_owned));then store node "$RUN_ID" "$NODE2_IP" closed || exit 1;event NOTE nodo2 'Lasciato acceso come configurato';fi
        else action nodo2 'Una fase del worker e fallita (vedere errori precedenti); lasciato acceso';store node "$RUN_ID" "$NODE2_IP" manual || exit 1;fi
    fi
    for id in "${LXC_IDS[@]}";do update_lxc "$id";done
    for target in "${VM_SSH_TARGETS[@]}";do if deploy ssh "$target";then worker vm "$target" full || true;else event FAIL vm 'Deploy fallito';fi;done
else update_lxc 200;fi
web_health
finish
