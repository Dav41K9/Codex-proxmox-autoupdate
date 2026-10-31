# Manutenzione Proxmox — ricostruzione reviewed

Versione: **4-reviewed-reconstructed-20261031**. Baseline di confronto funzionale: v3.1; baseline del diff: i nove file della v4 originale. Il vecchio ZIP reviewed non è stato recuperato. I risultati di vecchi test non sono attribuiti a questa ricostruzione.

## Decisioni implementate

- Job generale lunedì/mercoledì/venerdì alle 05:00; WordPress ogni notte alle 03:30, fuso dell'host Europe/Zurich o Europe/Rome.
- Lock unico, attesa massima sei ore, deduplica persistente per job/giorno. `--retry` autorizza una ripetizione deliberata. Non avviare direttamente i worker.
- LXC200: APT al mattino; Compose, build senza cache con aggiornamento base, standalone e prune nel notturno. Entrambi controllano HTTP e notificano gli errori via Telegram.
- LXC200: **cinque snapshot gestiti totali**, due `pre-update` più tre `pre-web-update`; entrambi i job ripuliscono entrambe le famiglie. Durante creazione/eliminazione può esistere una copia aggiuntiva temporanea. Snapshot manuali e backup estranei non vengono eliminati. Un errore di eliminazione viene segnalato e può lasciare più di cinque copie.
- LXC106: nessuno snapshot; Paperless e CouchDB aggiornati con identità Compose completa. Il timer di importazione viene coordinato temporaneamente; un import già attivo non viene terminato. Se la coordinazione non è verificabile, Paperless viene rinviato con FAIL.
- LXC1000: APT, Hermes come utente `hermes` con comando assoluto e `--yes`, attesa sincrona, reboot completo verificato da boot ID. Nessun comando Docker, incluse interrogazioni. Lo stato della dashboard prima dell'update non è un blocco; il controllo viene effettuato dopo reboot.
- Nodo2: WOL dopo ping e SSH negativi; update SSH; shutdown soltanto se avviato dal job e aggiornamento completato. Un nodo già acceso resta acceso. Ownership dubbia dopo crash: rimane acceso e richiede intervento.
- LXC temporanei: ritorno a spento dopo controllo dei lock POSIX dpkg/APT e del worker. Nessuno stop forzato. Se occupati o non verificabili: FAIL/ACTION nel report e su Telegram, con richiesta di intervento.
- NAS: `/mnt/pve/NAS/proxmox-maintenance/reports`, **60 giorni di storico**, sottocartelle private. Cache host di dieci report; coda locale non ancora consegnata conservata anche oltre dieci per evitare perdita. Nessuna modifica ai permessi globali del NAS.
- Importazione Hermes/Obsidian rinviata alla successiva fase concordata. È incluso un helper da validare, ma non viene installato un bridge NAS→Hermes né creato un cron Hermes. Nessuna manipolazione diretta di CouchDB.

## Installazione deliberata

Il pacchetto non include `/etc/update-guests.conf` reale e non lo sostituisce. Deve già esistere, essere root-owned, non symlink e non scrivibile da altri. Il file contiene codice Bash e viene trattato come configurazione fidata.

Dalla directory estratta, sul nodo Proxmox:

```bash
bash install.sh --check
```

Questo controllo non installa nulla. Se segnala vecchi cron/timer, identifica solo le posizioni: esaminare localmente le righe e disabilitare i vecchi job prima della migrazione, senza pubblicare segreti. Lo scanner è conservativo: non può scoprire scheduler esterni o tutti i wrapper dinamici.

Solo dopo la checklist di REVIEW-IT.md:

```bash
bash install.sh --install
/usr/local/sbin/update-proxmox-guests.sh --dry-run
/usr/local/sbin/update-web.sh --dry-run
```

`--install` copia codice e backup; non esegue l'updater e non crea cron. Il dry-run mostra la policy, **non simula comandi remoti o compatibilità applicativa**. Le esecuzioni reali vanno fatte in una finestra di prova, con recovery verificato. `--enable-cron` è un'azione separata esplicita, documentata ma non eseguita da questa revisione.

Un cron già installato da questa stessa versione resta presente durante l'aggiornamento del codice: fermare la schedulazione se si vuole una finestra senza nuovi job. L'installazione usa il lock comune.

## Configurazione compatibile e differenze

Sono letti: `UPDATE_HOST`, `UPDATE_NODE2`, `NODE2_IP`, `NODE2_MAC`, `NODE2_WOL_BROADCAST`, `NODE2_STOP_AFTER`, `LXC_IDS`, `VM_SSH_TARGETS`, array `SSH_OPTS`, `START_STOPPED_LXC`, `STOP_LXC_STARTED_BY_SCRIPT`, `CREATE_SNAPSHOTS`, `SNAPSHOT_SKIP_IDS`, `DOCKER_SKIP_IDS`, array associativo `LXC_COMPOSE_DIRS`, `WEB_COMPOSE_DIR`, `WEB_HTTP_HOST`, `NAS_MOUNT`, `SEND_TELEGRAM`, le credenziali Telegram esistenti, `COMPOSE_WAIT_SECONDS`, `APT_TIMEOUT`, `DOCKER_PRUNE`, `STANDALONE_MODE`, `DRY_RUN`.

Per ogni directory Compose con spazi usare un elemento quotato shell nella stringa di `LXC_COMPOSE_DIRS`, oppure directory separate da newline. Nessuna esecuzione della stringa: parsing shlex e trasporto base64. I file Compose/envfile rilevati dalle label devono tutti esistere.

La ricostruzione applica direttamente le decisioni concordate: snapshot200=2+3, altri=2, esclusione106, zeroDocker1000, NAS60giorni, cache10. I precedenti parametri di retention/prefisso, timeout di startup/shutdown e consegna Hermes non vengono applicati. Non viene aggiunto automaticamente un blocco di configurazione. Timeout reboot/shutdown=120s; attesa iniziale SSH nodo2=120s oltre i tempi delle singole chiamate. Questo è un cambiamento rispetto alla v4 originale.

I canali immagini sono applicati tramite un piccolo override Compose root-only, senza scrivere `.env` o il Compose originale. WordPress conserva la build; MariaDB segue il ramo major.minor, PostgreSQL il major; Redis/nginx e componenti applicativi noti seguono canali mobili. I major database non vengono migrati automaticamente da un tag numerico. CouchDB già su `latest` resta tale e produce un avviso. Portainer agent noto passa a `latest` con ricreazione conservativa e recupero dedicato. Immagini ID sconosciute, digest e tag fissi non riconosciuti vengono segnalati.

## Operatività e recupero

Stato persistente root-only in `/var/lib/proxmox-maintenance`: database SQLite standardlib, worker status, quarantena temporanea timer, outbox, cache, ricevute NAS e `delivery.log`. Nessun servizio residente aggiunto. Gli helper remoti Python3 e il lock del worker permettono il recupero di un coordinatore interrotto; non cancellare questi file per sbloccare il job.

Un'interruzione non garantisce il cleanup immediato. Il job successivo tenta il recupero; se un worker/APT è ancora attivo non lo termina e non spegne il guest. Con SIGKILL, crash host o Telegram irraggiungibile non è possibile garantire una notifica immediata. Gli errori Telegram restano in `delivery.log` e danno exit code non zero. Il report di manutenzione viene congelato prima del trasporto: NAS/Telegram hanno ricevute separate.

NFS bloccato in stato kernel D non è eliminabile con un timeout userspace: dopo 45s il coordinatore prosegue, mantiene la coda e segnala la consegna pendente; un processo archiviatore può restare bloccato con il suo lock. Non riavviare alla cieca mentre esistono transazioni.

I backup di installazione sono in `/var/backups/pve-maintenance-*`; le release in `/usr/local/libexec/pve-maintenance-releases`. Conservare la precedente release per rollback del codice. Questo **non** effettua rollback di database o immagini applicative. Verificare sempre dati e stato servizi prima di riattivare cron.
