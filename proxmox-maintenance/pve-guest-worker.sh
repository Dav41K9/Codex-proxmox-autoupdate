#!/usr/bin/env bash
# PVE Maintenance 4.1 - worker Linux / Docker / Hermes
# Eseguito soltanto dal coordinatore, su host / LXC / nodo2 / VM SSH.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
umask 077
LIB=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
: "${MODE:=full}"
export DEBIAN_FRONTEND=noninteractive
export NEEDRESTART_SUSPEND=1
export NEEDRESTART_MODE=l

: "${RUN_ID:?RUN_ID mancante}"
: "${KIND:?KIND mancante}"
: "${GUEST_ID:=}"
: "${DOCKER_PRUNE:=1}"
: "${DOCKER_IMAGE_PRUNE_AGE:=336h}"
: "${STANDALONE_MODE:=watchtower}"
: "${WATCHTOWER_IMAGE:=ghcr.io/nicholas-fedor/watchtower:latest}"
: "${DOCKER_AUTO_DISCOVER:=1}"
: "${SKIP_DOCKER:=0}"
: "${COMPOSE_WAIT_SECONDS:=240}"
: "${APT_TIMEOUT:=3600}"

[[ "$RUN_ID" =~ ^[A-Za-z0-9_-]+$ ]] || exit 2
STATE=/var/lib/proxmox-maintenance
[[ ! -L "$STATE" && ! -L "$STATE/worker-status" ]] || exit 2
[[ ! -e "$STATE" || ( $(stat -c %u "$STATE") == 0 && -z $(find "$STATE" -maxdepth 0 -perm /022 -print) ) ]] || exit 2
install -d -m0700 -o root -g root "$STATE/worker-status" || exit 2
exec 8>"$STATE/worker.lock" || exit 2
flock -n 8 || exit 75
STATUS="$STATE/worker-status/$RUN_ID.status"
(set -C; : >"$STATUS") || exit 2
WORK=$(mktemp -d /var/tmp/pve-maint-work.XXXXXX) || exit 2
trap 'rm -rf "$WORK"' EXIT
FAILURES=0
WARNINGS=0

note() { printf 'NOTE|%s\n' "$*" >> "$STATUS"; printf '[%s] INFO %s\n' "$(date '+%T')" "$*"; }
warn() { WARNINGS=$((WARNINGS+1)); printf 'WARN|%s\n' "$*" >> "$STATUS"; printf '[%s] WARNING %s\n' "$(date '+%T')" "$*"; }
fail() { FAILURES=$((FAILURES+1)); printf 'FAIL|%s\n' "$*" >> "$STATUS"; printf '[%s] ERROR %s\n' "$(date '+%T')" "$*"; }
reboot_needed() { printf 'REBOOT|%s\n' "$*" >> "$STATUS"; note "Riavvio LXC richiesto: $*"; }

run_cmd() {
    local label="$1"; shift
    local rc=0
    note "INIZIO: $label"
    "$@" || rc=$?
    if (( rc )); then fail "$label (rc=$rc)"; else note "OK: $label"; fi
    return 0
}

apt_stage() {
    note "Pacchetti Linux: $(hostname) ($KIND ${GUEST_ID:-})"
    if ! command -v apt-get >/dev/null 2>&1; then
        fail "apt-get non disponibile"
        return 0
    fi
    if command -v dpkg-query >/dev/null 2>&1; then
        dpkg-query -W -f='${Package}\t${Version}\n' >"$WORK/dpkg.before" 2>/dev/null || : >"$WORK/dpkg.before"
    else
        : >"$WORK/dpkg.before"
    fi
    # Non eseguire full-upgrade se l'aggiornamento indici fallisce: proseguire con altre fasi.
    local rc=0
    note "APT: aggiornamento indici in corso"
    local attempt
    for ((attempt=0;attempt<=30;attempt++));do
        rc=0
        if command -v timeout >/dev/null 2>&1; then
            LC_ALL=C timeout --kill-after=60s "${APT_TIMEOUT}s" apt-get -o APT::Update::Error-Mode=any update 2>&1 | tee "$WORK/apt-update.log" || rc=$?
        else
            LC_ALL=C apt-get -o APT::Update::Error-Mode=any update 2>&1 | tee "$WORK/apt-update.log" || rc=$?
        fi
        if ((rc==100 && attempt<30)) && grep -Eq 'Could not get lock|Unable to lock directory' "$WORK/apt-update.log";then
            note 'APT: lock indici occupato, nuovo tentativo tra 10 secondi'
            sleep 10
        else break;fi
    done
    if ((rc)); then
        fail "apt-get update (rc=$rc); full-upgrade saltato per non usare indici obsoleti"

    else
        note "OK: apt-get update"
        local up_rc=0
        # Non uccidere mai dpkg a meta transazione: niente timeout per full-upgrade.
        note "APT: full-upgrade in corso (attesa lock fino a 300 secondi)"
        apt-get -y -o DPkg::Lock::Timeout=300 -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold \
            full-upgrade 2>&1 | tee "$WORK/apt-upgrade.log" || up_rc=$?

        if ((up_rc)); then
            fail "apt-get full-upgrade (rc=$up_rc)"
        else
            note "OK: apt-get full-upgrade"
            local clean_rc=0
            apt-get -y -o DPkg::Lock::Timeout=300 autoremove --purge 2>&1 | tee "$WORK/apt-autoremove.log" || clean_rc=$?
            if ((clean_rc)); then warn "apt autoremove non completato (rc=$clean_rc)"; fi
        fi
    fi
    if [[ -s "$WORK/dpkg.before" ]] && command -v dpkg-query >/dev/null 2>&1; then
        dpkg-query -W -f='${Package}\t${Version}\n' >"$WORK/dpkg.after" 2>/dev/null || : >"$WORK/dpkg.after"
        awk -F '\t' 'NR==FNR {v[$1]=$2; next} !($1 in v) || v[$1]!=$2 {print $1}' \
            "$WORK/dpkg.before" "$WORK/dpkg.after" >"$WORK/changed.list"
        local n
        n=$(wc -l <"$WORK/changed.list")
        note "Pacchetti Linux aggiornati: $n"
        local critical_re='^(libc6|libc-bin|systemd|systemd-sysv|libsystemd0|dbus|udev|util-linux|libssl3|libssl3t64|openssl)$'
        local critical
        critical=$(grep -E "$critical_re" "$WORK/changed.list" | paste -sd, - || true)
        if [[ "$KIND" == lxc && -n "$critical" ]]; then reboot_needed "pacchetti di sistema: $critical"; fi
        if [[ "$KIND" != lxc && -n "$critical" ]]; then
            printf 'REBOOT_ADVICE|pacchetti di sistema modificati: %s\n' "$critical" >> "$STATUS"
        fi
        if [[ "$KIND" != lxc ]] && grep -Eq '^(pve-kernel|proxmox-kernel|linux-image-)' "$WORK/changed.list"; then
            printf 'REBOOT_ADVICE|aggiornato pacchetto kernel: verificare riavvio host/VM\n' >> "$STATUS"
        fi
    fi
    if [[ "$KIND" != lxc ]];then
        running=$(uname -r)
        newest=$(find /usr/lib/modules -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | sort -V | tail -n1)
        if [[ -n "$newest" && "$newest" != "$running" && $(printf '%s\n%s\n' "$running" "$newest" | sort -V | head -n1) == "$running" ]];then printf 'REBOOT_ADVICE|Kernel installato piu recente di quello in uso\n' >>"$STATUS";fi
    fi
    if [[ -f /run/reboot-required || -f /var/run/reboot-required ]]; then
        if [[ "$KIND" == lxc ]]; then reboot_needed "flag Debian reboot-required presente"
        else printf 'REBOOT_ADVICE|flag Debian reboot-required presente\n' >> "$STATUS"; fi
    fi
}

hermes_stage() {
    reboot_needed "reboot obbligatorio dopo fase Hermes anche su FAIL"
    note "LXC 1000: esecuzione hermes update --yes come utente hermes; attendo la fine"
    if ! id hermes >/dev/null 2>&1; then
        fail "Utente hermes mancante"
        return 0
    fi
    if [[ ! -x /home/hermes/.local/bin/hermes ]]; then
        fail "Comando /home/hermes/.local/bin/hermes mancante o non eseguibile"
        return 0
    fi
    local rc=0
    # Nessun timeout: lasciare terminare hermes update autonomamente.
    # --yes rende prevedibile l'esecuzione da cron senza prompt bloccanti.
    su - hermes -c '/home/hermes/.local/bin/hermes update --yes' || rc=$?
    if ((rc)); then fail "hermes update fallito (rc=$rc)"; else note "OK: hermes update completato"; fi

}

docker_phase() {
    [[ "$GUEST_ID" != 1000 && "$SKIP_DOCKER" != 1 && ( "$KIND" == lxc || "$KIND" == vm ) ]] || return 0
    command -v docker >/dev/null || { note 'Docker non installato';return 0; }
    local rc=0 line
    local -a args=()
    [[ "$MODE" != health ]] || args+=(--health)
    python3 "$LIB/docker-maint.py" "${args[@]}" 2>&1 | tee "$WORK/docker.log" || rc=$?
    while IFS= read -r line;do case "$line" in FAIL\|*) fail "${line#*|}";;WARN\|*) warn "${line#*|}";;NOTE\|*) note "${line#*|}";;*) printf '%s\n' "$line";;esac;done <"$WORK/docker.log"
    ((rc==0)) || fail "Docker helper rc=$rc"
    if [[ "$MODE" != health && "$DOCKER_PRUNE" == 1 ]] && ((FAILURES==0));then run_cmd 'Prune immagini create prima di 14 giorni, nessun volume' docker image prune -af --filter "until=$DOCKER_IMAGE_PRUNE_AGE";fi
}
export RUN_ID KIND GUEST_ID COMPOSE_DIRS_B64=${COMPOSE_DIRS_B64:-} COMPOSE_WAIT_SECONDS STANDALONE_MODE WATCHTOWER_IMAGE
printf 'RUN|%s\n' "$RUN_ID" >>"$STATUS"
if [[ "$MODE" == health ]];then
    if [[ "$GUEST_ID" == 1000 ]];then
        ready=0
        for ((i=0;i<120;i++));do if systemctl is-active --quiet hermes-dashboard.service;then ready=1;break;fi;sleep 2;done
        ((ready)) || fail 'Dashboard Hermes non attiva dopo reboot'
        warn 'Gateway/checkout non verificati funzionalmente'
    else docker_phase;fi
else
    if [[ ( "$KIND" == lxc || "$KIND" == vm ) && "$GUEST_ID" != 1000 ]] && command -v docker >/dev/null;then
        python3 "$LIB/docker-maint.py" --record >/dev/null 2>&1 || fail 'Inventario pre-manutenzione fallito'
    fi
    if [[ "$KIND" == lxc && "$GUEST_ID" == 1000 ]];then
        importdir=/var/lib/proxmox-maintenance-import
        [[ ! -L "$importdir" ]] || exit 2
        [[ ! -e "$importdir" || ( $(stat -c %u "$importdir") == 0 && -z $(find "$importdir" -maxdepth 0 -perm /022 -print) ) ]] || exit 2
        install -d -m0755 -o root -g root "$importdir" || exit 2
        [[ ! -L "$importdir/import.lock" && ! -L "$importdir/maintenance.active" ]] || exit 2
        touch "$importdir/import.lock";chmod 0644 "$importdir/import.lock"
        cat /proc/sys/kernel/random/boot_id >"$importdir/maintenance.active";chmod 0644 "$importdir/maintenance.active"
        exec 7<"$importdir/import.lock";flock -x 7 || exit 2
    fi
    prepared=1
    python3 "$LIB/guard.py" prepare "$RUN_ID" || { fail 'Coordinamento timer fallito';prepared=0; }
    if [[ "$MODE" != docker ]];then if ((prepared));then apt_stage;else fail 'APT rinviato: coordinamento incompleto';fi;fi
    if [[ "$GUEST_ID" == 1000 && "$KIND" == lxc ]];then hermes_stage
    elif [[ "$MODE" != apt ]];then docker_phase;fi
    if [[ "$KIND" != lxc ]];then python3 "$LIB/guard.py" restore-worker || fail 'Ripristino timer fallito';fi
fi
printf 'COMPLETE|failures=%d warnings=%d\n' "$FAILURES" "$WARNINGS" >>"$STATUS"
((FAILURES==0))
