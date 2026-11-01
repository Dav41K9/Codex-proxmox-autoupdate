> **Documento storico della ricostruzione4.0.** Per la4.1 usare README-IT.md, CHANGELOG-4.1.md e VALIDAZIONE-4.1.md. Le limitazioni e i meccanismi qui descritti non costituiscono la procedura corrente.

# Revisione della ricostruzione

## A. Verdetto

**PRONTO SOLO DOPO TEST LIVE controllati; nessun via libera per cron.** La consegna è un nuovo pacchetto recuperabile, non una copia certificata dell'archivio perso. La ricostruzione implementa le decisioni successive alla v4 originale; le prove qui dichiarate sono quelle eseguite in questa sessione. Nessun updater eseguito su host/guest reali.

Le verifiche locali confermano numerose correzioni, ma non dimostrano consistenza dei database, rollback, riavvio reale PVE, ricreazione Docker API sul runtime installato, comportamento dei timer custom o disponibilità del NAS. Le prove applicative di WordPress/Paperless/CouchDB/RustDesk e l'importazione E2EE rimangono distinte dai test di processo.

## B. Findings confermati e limiti residui

Le righe della v4 si riferiscono ai file originali nello ZIP ricevuto. Il diff allegato consente di ricostruire le modifiche senza confondere v3.1 e v2.4.

| Gravità | File/riga o funzione | Prova | Impatto e correzione | Stato |
|---|---|---|---|---|
| P1 | v4 `update-proxmox-guests.sh:317` | Fallback `pct stop` dopo timeout di shutdown | Possibile interruzione dpkg; eliminato. Guard POSIX reale e lock worker, guest lasciato acceso con ACTION se occupato. Test lock reale + mock ripristino. | CONFIRMED, corretto |
| P1 | v4 `update-proxmox-guests.sh:290`, `:299`, `:302` | Return prima dello spegnimento dei guest temporanei | Mancato ripristino. Journal persistente, cleanup EXIT e recovery successivo; non forza stato dubbio. SIGKILL richiede recupero successivo. | CONFIRMED, corretto nei percorsi coperti |
| P1 | v4 `pve-guest-worker.sh:140`, `:191` | Discovery centrata sulla directory, identità completa e profili non garantiti | Rischio aggiornare stack diverso o avviare pma. Ora project name, insieme completo file/envfile, servizi espliciti, verifica mount prima/dopo. | CONFIRMED, corretto; runtime NEEDS-LIVE-TEST |
| P1 | ricostruzione `agent-migrate.py:migrate` | Ricreazione tramite Docker API: stop/rename/create/start con journal e rollback del solo agent | Mock coprono fallimenti e preservazione config/volume; API/versione/config effettiva da verificare. Se non ricostruibile, FAIL e nessuna migrazione. | NEEDS-LIVE-TEST |
| P1 | `docker-maint.py:project`, snapshot | Aggiornare un DB può migrare il formato/schema | Snapshot LXC non dimostra consistenza applicativa né copertura mount esterni. Nessun rollback automatico DB. Verificare restore e dump prima di cron; cinque snapshot non equivalgono a cinque backup validati. | NEEDS-LIVE-TEST; rischio automazione accettato, recovery non provato |
| P2 | v4 `pve-guest-worker.sh:57` | `apt-get update` senza Error-Mode=any può dare rc0 con repository parzialmente falliti | Indici vecchi e falso successo: aggiunto Error-Mode=any, full-upgrade saltato dopo errore, altre fasi proseguono. | CONFIRMED, corretto |
| P2 | v4 `pve-guest-worker.sh:106`, `:110`, `:119` | Return prerequisiti prima del marker reboot Hermes | Reboot obbligatorio omesso. Marker prima dei prerequisiti, errore mantenuto, reboot solo dopo worker concluso e guard. | CONFIRMED, corretto |
| P2 | v4 cron + discovery generale WP | Entrambi i job includono Docker200 lun/mer/ven | Doppio aggiornamento: APT al generico, Docker/build completo al notturno. Inventario Docker di sola lettura può restare al mattino per verificare il reboot. | CONFIRMED, corretto |
| P2 | `guard.py:prepare` | Runtime masking di unit custom può non essere effettivo | Ora verificato LoadState; coordinazione incompleta produce FAIL. L'import Paperless corrente non viene terminato. | CONFIRMED difesa nel codice; NEEDS-LIVE-TEST unit custom |
| P2 | `state.py:archive` | NAS assente, collisione, readback, retry e scadenza simulati | Report prima in outbox locale; cancellazione solo dopo ricevuta e readback. Processo NFS in D può restare bloccato: segnalazione e coda conservata. | CONFIRMED test; mount reale NEEDS-LIVE-TEST |
| P2 | `coordinator.sh:telegram`, `finish` | Stub API ok=false e Unicode suddiviso in messaggi | Errori non ignorati; fallimento trasporto nel delivery.log/exitcode. Report manutenzione immutabile, stato trasporto separato. | CONFIRMED test; consegna reale NOT TESTED |
| P2 | `audit-schedulers.py` | Scanner file/wrapper limitato, lock comune e dedup giornaliera | Non scopre qualsiasi scheduler esterno né comandi dinamici. Prima di cron controllare manualmente scheduler esterni e job legacy. | CONFIRMED limite |
| P3 | `docker-maint.py:health`, `coordinator.sh:web_health` | Running senza healthcheck genera WARN, HTTP200 login annotato come parziale | Non certifica checkout, pagamento, ingestione Paperless, sync E2EE o sessione RustDesk. Necessarie prove applicative. | CONFIRMED limite |

Nessun P0 identificato dai test svolti; questo non prova l'assenza di difetti non esercitati. I rischi live P1 elencati impediscono di qualificare il pacchetto come IDONEO PER CRON.

## C. Matrice R01–R20

PASS significa criterio locale indicato, non certificazione live. Dove il criterio originario richiede un risultato sul sistema vero rimane NOT TESTED. Le decisioni successive dell'utente prevalgono sui requisiti iniziali.

| Requisito | Esito | Evidenza/limite |
|---|---|---|
| R01 prosecuzione fasi/guest | PASS | Worker APT fallito continua Docker; progetto fallito continua successivo; loop guest senza exit su errore worker. |
| R02 niente falso OK | PASS | Status con run identity e conteggi/finale verificati; errore mantiene FAIL. |
| R03 zero Docker1000 | PASS | Test worker Hermes e difesa helper prima di inventory. |
| R04 attesa Hermes prima reboot | PASS | Comando sincrono --yes, mock errore e marker finale; processo reale da provare. |
| R05 reboot Hermes sempre | NOT TESTED | Marker anche su errore/prerequisiti; reboot reale e check dashboard non eseguiti. Worker incompleto/occupato richiede recupero, non reboot forzato. |
| R06 no snapshot106 | PASS | Esclusione hard e mock pct. |
| R07 guest inizialmente spenti | PASS | Mock ritorno spento e eccezione approvata: lasciare acceso con ACTION quando non sicuro. |
| R08 nodo2 | NOT TESTED | Test ping-only/SSH-only/entrambi negativi; WOL, SSH update e poweroff reali non provati. |
| R09 retention snapshot | PASS | Test due generali e tre WP, totale gestito cinque200; altri due. |
| R10 Compose aggiornato | NOT TESTED | Mock identità/envfile/mount/profili/failure; pull/build/up reali da verificare. |
| R11 standalone aggiornato | NOT TESTED | Mock Watchtower e transizione agent; efficacia runtime reale non provata. |
| R12 Watchtower esclude Compose | PASS | Mock argomenti: solo nomi standalone attivi. |
| R13 prune14giorni | PASS | Ispezione codice image prune until336h, nessun volume prune; soppressa dopo FAIL. |
| R14 WordPress update/health | NOT TESTED | Test esclusione profili e HTTP503; build, volumi reali e checkout da provare. |
| R15 password intatte | PASS | Nessuna scrittura .env, ALTER USER, rotazione account; API agent preserva Env in memoria. |
| R16 Telegram | NOT TESTED | Mock API false/Unicode passati; invio reale e rete non verificati. |
| R17 cache report10 | PASS | Test13 report: cache10, outbox pendente13; eccezione approvata anti-perdita, NAS60giorni. |
| R18 Hermes E2EE | NOT APPLICABLE | Rinviato nella policy attuale; helper incluso e mock idempotenza, bridge e cron non implementati/attivati. |
| R19 nessun duplicato cron | NOT TESTED | Dedup persistente testata e scanner conservativo; inventario completo runtime/scheduler esterni da verificare. |
| R20 MWF mattina | PASS | Cron 05:00 MWF e WP03:30 quotidiano, timezone controllata prima dell'attivazione. |

## D. Cambiamenti rispetto alle baseline

v3.1 rimane la baseline funzionale, non v2.4: separazione worker, errori APT/Docker non mascherati, build effettiva, Docker escluso da Hermes, report strutturati e cron distinti sono miglioramenti della linea v4 ulteriormente corretti qui. La precedente logica di pull standalone senza ricreazione non viene riproposta.

Questa ricostruzione aggiunge Python3 standardlib per metadata Docker, lock POSIX, journal SQLite e archiviazione. Non aggiunge daemon, pip package o servizio da mantenere. Aumenta il numero dei file rispetto ai nove originali: la separazione permette di testare recupero e invarianti, ma comporta più codice da mantenere. Una semplificazione futura possibile è sostituire la migrazione agent una tantum con Compose gestito; richiede prima la migrazione della configurazione runtime e non è applicata automaticamente qui.

Differenze operative, fallback conservativi, parametri non più letti e attivazione esplicita dell'installer sono documentati in README-IT.md. Import Hermes rinviato come richiesto. Nessuna nuova approvazione è richiesta per generare questo pacchetto: aggiornamenti automatici e policy concordate sono già autorizzati. Le migrazioni major di database non vengono inventate né applicate.

## E. Test realmente eseguiti

Risultati completi in `tests/results.txt` e `tests/static-results.txt`:

```bash
python3 -m unittest discover -s tests -v
for f in proxmox-maintenance/*.sh; do bash -n "$f"; done
```

Parsing AST di tutti i Python tramite `ast.parse`. ShellCheck non disponibile in questo ambiente: NOT VERIFIED, non viene attribuito al pacchetto un controllo ShellCheck mai eseguito. Lo ZIP viene verificato con `zipfile.testzip()` e checksum SHA256.

Mock: pct/ssh/curl e funzioni Bash, apt-get/su/docker, Docker inspect/Compose/API, findmnt e vault CLI. Il test dei lock usa **un altro processo reale con fcntl POSIX**, non un lock simulato. Nessun mock dimostra comportamento kernel/PVE, consistenza DB, protocolli di rete, funzionamento dei timer installati o CLI E2EE reale. Questi test non equivalgono ai risultati del vecchio ambiente perso.

### Checklist live, senza segreti

1. Non attivare cron. Usare `bash install.sh --check`; controllare localmente scheduler segnalati, con `systemctl list-timers --all --no-pager --full` e lista dei cron legacy. Non pubblicare interi crontab/config se contengono credenziali.
2. Verificare CLI di sola lettura: `pct help reboot`, `pct help shutdown`; nei guest interessati `docker compose up --help`, `docker compose version`. Non richiedere di nuovo help Hermes già fornito.
3. Per il masking custom leggere `pct exec 106 -- systemctl show paperless-import.timer paperless-import.service -p FragmentPath -p LoadState -p ActiveState`. Durante una prova verificare che timer venga ripristinato e import attivo non terminato. Se unit custom non mascherabile, correggere coordinazione prima di cron.
4. Verificare mount WordPress senza ambiente: `pct exec 200 -- docker inspect --format '{{json .Mounts}}' wp_db wp_app`. Confrontare nomi volume con il Compose locale; non inviare `docker inspect` completo o `docker compose config` completo.
5. Su clone o finestra concordata provare guest inizialmente spento, APT fallito, SSH perso, worker interrotto, nodo2 già acceso e nodo2 svegliato. Confermare ACTION e nessuno stop durante dpkg. SIGKILL e crash host richiedono recupero al run successivo.
6. Provare restore snapshot **su clone**, verificare dati MariaDB/WordPress e coerenza dump. I mount NAS106 non sono protetti da snapshot LXC. Non promettere rollback in pochi secondi prima della prova.
7. Verificare login, lettura prodotti, carrello/checkout in modalità test, persistenza file e DB; Paperless ingestione/ricerca, CouchDB sync E2EE, RustDesk connessione relay. Non basta HTTP200 o running.
8. Provare NAS disponibile/indisponibile, permessi privati della sola sottocartella, readback/retention, Telegram reale. Se NFS è in D, gestire il mount prima di aspettarsi lo svuotamento della coda.
9. Un ciclo manuale generale e uno notturno devono terminare con report attendibile, stato guest ripristinato e warning spiegati. Solo successivamente valutare `bash install.sh --enable-cron`.

## F. Artefatto e diff

`dist/proxmox-maintenance-v4-reviewed.zip`, SHA256 in `dist/SHA256SUMS`. Il diff preciso da v4 originale è in `diff/v4-to-reviewed.diff`; include file nuovi e i nove file originali modificati. Gli originali ricevuti non sono sovrascritti. Nel repository pubblico sono esclusi dossier privato, output runtime e configurazione reale. Il ZIP contiene sorgenti, istruzioni, test e diff; nessun installer è stato eseguito su Proxmox.
