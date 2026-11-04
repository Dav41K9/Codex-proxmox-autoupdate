# Hotfix 4.1.2: archivio NAS con ACL e conflitto dashboard Hermes

La correzione NAS si applica alla release 4.1.1 verificata. Il controllo precedente rifiutava directory con bit POSIX di gruppo/altri anche quando l'accesso era governato dalle ACL del NAS. Il valore 777 e il ctime non dimostrano chi abbia cambiato la configurazione né quali autorizzazioni effettive conceda Synology.

## Archivio

Il valore predefinito resta `NAS_PERMISSION_MODE=private`. La modalità esplicita `server-acl` affida la protezione degli accessi alle ACL del server, che l'amministratore deve verificare per entrambe le directory e per gli accessi NFS. Non permette al client di certificare da solo tali ACL. Restano richiesti il mount NFS esatto, directory/file senza symlink, assenza di collisioni, copia atomica e verifica del contenuto riletto. Un errore conserva il report nell'outbox. La ricevuta registra la modalità. La retention resta 60 giorni.

Per il caso diagnosticato sono state verificate le ACL Synology della directory `proxmox-maintenance` e della sottodirectory `reports`: le autorizzazioni mostrate sono riservate all'utente previsto e agli amministratori. Non occorre cambiare chmod, squash o ACL per applicare questo hotfix.

Scaricare `fixes/apply-nas-acl-4.1.2.py` dal commit pubblicato ed eseguire sul nodo principale:
```bash
python3 /root/apply-nas-acl-4.1.2.py --check --server-acl
python3 /root/apply-nas-acl-4.1.2.py --apply --server-acl
```

Il file incorpora i due sorgenti aggiornati e 11 test offline. Verifica hash della base installata, prende il lock della manutenzione e conserva vecchia release e configurazione. Se trova modifiche locali sconosciute si ferma. Il controllo non modifica release/configurazione. L'applicazione aggiunge solo la policy NAS alla configurazione, senza stamparne il contenuto. Non esegue manutenzione dei guest, non cambia cron e non modifica permessi NAS.

Per ritentare solo i report arretrati, senza avviare aggiornamenti:
```bash
flock -n /var/lock/update-guests.lock \
  python3 /usr/local/libexec/pve-maintenance-current/state.py \
  /var/lib/proxmox-maintenance archive /mnt/pve/NAS server-acl
find /var/lib/proxmox-maintenance/outbox -maxdepth 1 -type f -name '*.md' -printf '%f\n'
```
Un ritorno zero e outbox vuota confermano la consegna degli arretrati. Il vecchio `archive.log` non viene sovrascritto da questo comando manuale: non usarlo come esito della nuova prova. Il prossimo cron userà la policy configurata. Se il lock è occupato, attendere la fine del job.

Per rollback, il percorso di backup stampato contiene `previous-release`, `new-release` e `config-before`. Ripristinare configurazione e collegamento alla vecchia release con il medesimo lock; non eliminare le release prima del collaudo.

## Hermes: due unità distinte sulla stessa porta

Nel caso diagnosticato `hermes-dash.service` avvia il processo che occupa la porta della dashboard. `hermes-dashboard.service` tenta di servire lo stesso profilo e viene rifiutato con codice 78. Non è un falso positivo del controllo di stabilità. Il log contiene anche errori di import/update senza timestamp: non bastano per concludere che siano ancora attuali dopo la rimozione del conflitto.

Mantenere `hermes-dashboard.service`, già usata dal controllo di manutenzione. Con nessun update Hermes in esecuzione, eseguire dal nodo principale:
```bash
pct exec 1000 -- bash -c '
set -e
umask 077
backup=/var/backups/hermes-dashboard-$(date +%Y%m%d-%H%M%S)
mkdir -p "$backup"
systemctl cat hermes-dashboard.service hermes-dash.service >"$backup/units.txt"
systemctl is-enabled hermes-dashboard.service hermes-dash.service >"$backup/enabled.txt" || true
systemctl disable --now hermes-dash.service
systemctl enable hermes-dashboard.service
systemctl restart hermes-dashboard.service
printf "Backup delle definizioni: %s\n" "$backup"
'
```
Si preservano i comandi di avvio e la configurazione applicativa delle unità. Non si cancellano file di servizio né dati e non si cambiano credenziali o opzioni di autenticazione. Non occorre ripetere l'aggiornamento generale.

Verificare:
```bash
pct exec 1000 -- bash -c '
for n in 1 2; do
  date -Is
  systemctl show hermes-dashboard.service -p ActiveState -p SubState -p MainPID -p NRestarts -p ExecMainStatus
  [ "$n" = 2 ] || sleep 20
done
systemctl show hermes-dash.service -p ActiveState -p UnitFileState
'
```
Atteso: dashboard active/running, PID e NRestarts stabili; duplicata inactive/disabled. Il totale storico dei riavvii può essere elevato: conta che non aumenti. Aprire anche la dashboard e verificare una risposta del gateway.

Se la dashboard canonica resta guasta, esaminare le nuove righe del log dopo questa prova. Per tornare temporaneamente alla precedente unità senza ricreare il conflitto:
```bash
pct exec 1000 -- systemctl disable --now hermes-dashboard.service
pct exec 1000 -- systemctl enable --now hermes-dash.service
```
In quel caso il controllo attuale continuerà correttamente a segnalare l'assenza della dashboard canonica.

Upstream descrive il rifiuto permanente con exit 78 e l'opzione systemd `RestartPreventExitStatus=78`: https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/web-dashboard.md . Qui la riparazione minima elimina l'unità concorrente senza introdurre altri componenti.

## Limiti della verifica
I test offline simulano mount NFS ed errori di copia; non verificano il server Synology reale. La stabilità della dashboard e l'archiviazione effettiva devono essere confermate con i comandi sopra. Nessun comando è stato eseguito sul Proxmox dell'utente durante lo sviluppo.
