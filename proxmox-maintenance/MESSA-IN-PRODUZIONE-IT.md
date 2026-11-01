- Backup e restore dati verificati; volumi WordPress identici; pma non avviato.
- Un nuovo ciclo notturno e un nuovo ciclo generale completati; nessun FAIL/ACTION aperto.
- WARN classificati: «running senza healthcheck» o «ramo DB da monitorare» non certificano l'app, ma possono essere accettati dopo test funzionali; NAS non consegnato, sito non verificabile o timer non ripristinati non sono avvisi da ignorare.
- Guest temporanei ripristinati; nodo2 provato sia inizialmente acceso sia spento; Hermes aggiornato e riavviato, dashboard/gateway verificati.
- Telegram realmente ricevuto; report nuovi identici sul NAS; outbox non bloccata.
- Eventuali reboot host/VM pianificati separatamente; cluster in salute e quorum disponibile.

Controlla data, fuso e quorum:

```bash
timedatectl status
pvecm status
```

Il fuso previsto è `Europe/Zurich` oppure `Europe/Rome`. Solo se devi correggere il fuso, questa è un'azione esplicita che cambia gli orari locali dei job:

```bash
timedatectl set-timezone Europe/Zurich
```

Con DST il cron segue l'ora locale. Entrambi gli orari scelti sono dopo l'ora ambigua tipica europea; la deduplica per job/giorno rimane comunque attiva.

Attivazione finale:

```bash
bash <<'SH'
set -euo pipefail
cd /root/pve-maintenance-deploy-20261031/release/proxmox-maintenance
bash install.sh --check
bash install.sh --enable-cron
systemctl enable --now cron
cat /etc/cron.d/pve-maintenance
systemctl is-active cron
python3 audit-schedulers.py --allow-managed
SH
```

La configurazione deve avere `DRY_RUN=0`, `SEND_TELEGRAM=1` e credenziali presenti: l'installer lo verifica. Questo passaggio reinstalla anche la release e crea un nuovo backup. Non aggiungere gli stessi job con `crontab -e`.

Gli unici due nuovi job sono:

| Job | Orario locale | Responsabilità |
|---|---|---|
| WordPress | ogni giorno 03:30 | Docker200 completo: Compose/build/standalone, snapshot, health/report |
| Proxmox | lun/mer/ven 05:00 | host/nodo2/guest abilitati; APT200, Hermes, Docker altri guest |

Se il notturno è ancora in corso, il generale attende il lock fino a sei ore: non significa avvio garantito esattamente alle05:00. Un job manuale già eseguito nello stesso giorno può far saltare quello schedulato per deduplica: è previsto, non manca un report nuovo per errore.

## 16. Verifica il giorno dopo e dopo la prima settimana

```bash
journalctl -u cron --since yesterday --no-pager
tail -n 80 /var/log/update-web-cron.log
tail -n 80 /var/log/update-guests-cron.log
cat /var/lib/proxmox-maintenance/latest.md
```

La disponibilità dei log cron dipende dalla configurazione journald/syslog. Gli script possono scrivere poco su stdout: un file cron log vuoto non prova che il job non sia partito. Controlla anche `runs` nel database, timestamp dei nuovi report e Telegram. Nessuna notifica inattesa, sito raggiungibile, nodo2/guest allo stato previsto.

Ripeti i controlli di sezione14 dopo il primo job automatico generale e dopo una settimana: report NAS, outbox, snapshot, timer e spazio. La deduplica non elimina il bisogno di verificare che il job parta almeno una volta nel giorno previsto.

## 17. Se qualcosa non va

### Fermare le prossime esecuzioni

Questo mette in pausa solo i **nuovi avvii**, senza interrompere il job/APT già in corso:

```bash
bash <<'SH'
set -euo pipefail
umask 077
if [ -e /etc/cron.d/pve-maintenance ] || [ -L /etc/cron.d/pve-maintenance ]; then
    pause_dir=$(mktemp -d /root/pve-maintenance-cron-paused.XXXXXX)
    mv /etc/cron.d/pve-maintenance "$pause_dir/"
    printf 'Cron messo in pausa in %s\n' "$pause_dir"
fi
SH
```

Lascia terminare le transazioni; raccogli report, worker status e delivery.log. Non cancellare database, lock, quarantine.json o worker status; servono al recupero. Un LXC lasciato acceso con ACTION è un comportamento di sicurezza, non un invito a `pct stop`.

### Errori frequenti e risposta

| Segnale | Azione |
|---|---|
| `Coordinamento timer fallito`, `mask not effective` | Cron in pausa; verificare FragmentPath/LoadState e timer del target; serve correggere la compatibilità prima di riattivare. |
| Docker/file Compose mancante o mount mismatch | Non creare/rinominare volumi; controllare metadata/file/envfile e mounts. Nessun `down -v`. |
| NAS pending | Controllare mount e permessi; preservare outbox. Dopo il ripristino il prossimo job ritenta la consegna. |
| Telegram failed | Verificare rete e destinazione usando il test dedicato; il report da solo non prova la consegna. |
| LXC ancora acceso | Verificare transazioni/worker/import; non forzare stop. Dopo la risoluzione il successivo job tenta il recupero. |
| Dashboard Hermes non attiva dopo reboot | Guasto post-update da risolvere; non confonderlo con lo stato pre-update già noto. |
| `Duplicato giornaliero evitato` | Il job non ha aggiornato nulla. `--retry` solo se vuoi realmente una nuova esecuzione. |
| Sito down / DB in errore | Pausa nuovi job, preserva i dati e valuta recovery con backup e ordini recenti; niente rollback DB automatico. |

### Ripristino del solo codice

Dopo avere messo in pausa i cron, attendi che il lock host sia libero. Individua il backup dell'installer corretto:

```bash
ls -dt /var/backups/pve-maintenance-*
```

Se quel backup contiene `previous-release`, puoi tornare alla release precedente **senza riattivare cron**. Sostituisci il percorso segnaposto con quello verificato:

```bash
bash <<'SH'
set -euo pipefail
backup_dir=/var/backups/PERCORSO_DEL_BACKUP_VERIFICATO
exec 9>/var/lock/update-guests.lock
flock -n 9
previous=$(cat "$backup_dir/previous-release")
case "$previous" in
  /usr/local/libexec/pve-maintenance-releases/*) ;;
  *) echo 'Percorso release inatteso'; exit 1 ;;
esac
[ -d "$previous" ]
[ -f "$previous/coordinator.sh" ]
new_link=/usr/local/libexec/.pve-rollback-$$
ln -s "$previous" "$new_link"
mv -Tf "$new_link" /usr/local/libexec/pve-maintenance-current
printf 'Codice ripristinato a %s; cron resta in pausa\n' "$previous"
SH
```

Se era la prima installazione e non c'è una precedente release, usa le copie dei vecchi wrapper nel backup per un ripristino manuale consapevole: non riattivare automaticamente v3/v4 perché avevano difetti già identificati. Il rollback del codice non ripristina database, immagini, kernel o dati applicativi e non deve cancellare il journal. Dopo ogni correzione ricollauda, poi riattiva con la sezione15.
