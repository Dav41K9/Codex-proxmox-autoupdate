#!/usr/bin/env bash
set -euo pipefail
umask 077
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
MODE=${1:---check}
case "$MODE" in --check|--install|--enable-cron) ;;*) echo 'Uso: install.sh [--check|--install|--enable-cron]';exit 2;;esac
((EUID==0)) || { echo 'Eseguire su host Proxmox come root';exit 2; }
for f in "$HERE"/*.sh;do bash -n "$f";done
python3 - "$HERE" <<'PY'
import ast,pathlib,sys
for p in pathlib.Path(sys.argv[1]).glob('*.py'):ast.parse(p.read_text(),filename=str(p))
PY
config=/etc/update-guests.conf
[[ -f "$config" && ! -L "$config" && $(stat -c %u "$config") == 0 && -z $(find "$config" -perm /022 -print) ]] || { echo 'Configurazione mancante/non privata';exit 2; }
bash -n "$config"
for bin in python3 pct ssh ping flock tar base64 curl findmnt tee sha256sum;do
    command -v "$bin" >/dev/null || { echo "Dipendenza mancante: $bin";exit 2; }
done
scan=()
[[ ! -L /usr/local/libexec/pve-maintenance-current ]] || scan+=(--allow-managed)
scan_rc=0
python3 "$HERE/audit-schedulers.py" "${scan[@]}" || scan_rc=$?
if ((scan_rc));then
    if [[ "$MODE" == --enable-cron ]];then echo 'Cron non attivato: risolvere prima i conflitti/segnalazioni scanner';exit 2;fi
    echo 'WARN scheduler: installazione del codice consentita; cron da verificare prima dell attivazione'
fi
if [[ "$MODE" == --enable-cron ]];then
    zone=$(timedatectl show -p Timezone --value)
    [[ "$zone" == Europe/Zurich || "$zone" == Europe/Rome ]] || { echo 'Fuso non previsto';exit 2; }
    bash -c 'source "$1";[[ ${DRY_RUN:-0} == 0 && ${SEND_TELEGRAM:-0} == 1 && -n ${TELEGRAM_BOT_TOKEN:-} && -n ${TELEGRAM_CHAT_ID:-} ]]' bash "$config"
fi
if [[ "$MODE" == --check ]];then echo 'Preflight completato: nessuna modifica';exit;fi
[[ ! -L /var/lock/update-guests.lock ]] || exit 2
exec 9>/var/lock/update-guests.lock
flock -w 60 9 || exit 75
backup=/var/backups/pve-maintenance-$(date -u +%Y%m%d-%H%M%S)-$$
install -d -m0700 "$backup"
for f in "$config" /usr/local/sbin/update-proxmox-guests.sh /usr/local/sbin/update-web.sh /usr/local/sbin/maintenance-recover.sh /etc/cron.d/pve-maintenance /etc/logrotate.d/pve-maintenance;do [[ ! -e "$f" ]] || cp -p "$f" "$backup/${f//\//_}";done
[[ ! -L /usr/local/libexec/pve-maintenance-current ]] || readlink /usr/local/libexec/pve-maintenance-current >"$backup/previous-release"
if [[ -d /usr/local/libexec/pve-maintenance && ! -L /usr/local/libexec/pve-maintenance ]];then cp -a /usr/local/libexec/pve-maintenance "$backup/legacy-libexec";fi
if [[ -d /usr/local/lib/pve-maintenance && ! -L /usr/local/lib/pve-maintenance ]];then cp -a /usr/local/lib/pve-maintenance "$backup/legacy-lib";fi
release_id=$(cat "$HERE"/*.py "$HERE"/*.sh | sha256sum | cut -c1-20)
release=/usr/local/libexec/pve-maintenance-releases/$release_id
[[ ! -L /usr/local/libexec/pve-maintenance-releases && ! -L "$release" ]] || exit 2
install -d -m0750 "$release"
for f in "$HERE"/*.sh "$HERE"/*.py "$HERE"/*.md;do install -m0750 -o root -g root "$f" "$release/";done
install -d -m0755 /usr/local/sbin
for name in update-proxmox-guests.sh update-web.sh maintenance-recover.sh;do
    tmp=$(mktemp /usr/local/sbin/.pve-wrapper.XXXXXX)
    cat >"$tmp" <<'WRAP'
#!/usr/bin/env bash
set -euo pipefail
release=$(readlink -f /usr/local/libexec/pve-maintenance-current)
exec bash "$release/${0##*/}" "$@"
WRAP
    chmod 0750 "$tmp";mv "$tmp" "/usr/local/sbin/$name"
done
link=/usr/local/libexec/.pve-next-$$
ln -s "$release" "$link";mv -Tf "$link" /usr/local/libexec/pve-maintenance-current
for log in /var/log/pve-maintenance.log /var/log/update-guests-cron.log /var/log/update-web-cron.log;do [[ ! -L "$log" ]] || exit 2;touch "$log";chown root:root "$log";chmod 0600 "$log";done
install -m0644 "$HERE/pve-maintenance.logrotate" /etc/logrotate.d/pve-maintenance
if [[ "$MODE" == --enable-cron ]];then
    tmp=$(mktemp /etc/cron.d/.pve-cron.XXXXXX);install -m0644 "$HERE/pve-maintenance.cron" "$tmp";mv "$tmp" /etc/cron.d/pve-maintenance
fi
echo 'Per riparare i timer della versione precedente: maintenance-recover.sh (nessun update o spegnimento)'
printf 'Installato %s; backup %s. Nessun updater eseguito.\n' "$release" "$backup"
