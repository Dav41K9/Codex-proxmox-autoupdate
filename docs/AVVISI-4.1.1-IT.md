# Avvisi operativi e Telegram — hotfix 4.1.1

Questa correzione riguarda quattro file della release 4.1: `coordinator.sh`, `state.py`, `docker-maint.py`, `pve-guest-worker.sh`.

## Comportamento

- NOTE: container running senza healthcheck configurato; ramo DB aggiornabile scelto; canale mobile DB esistente; limiti delle prove funzionali. Restano nel report, senza far diventare WARN una manutenzione altrimenti riuscita.
- WARN: digest/ID immutabile, canale numerico senza regola automatica, standalone numerico da verificare, snapshot fallito, cleanup non completato, inventario mancante e altri problemi recuperabili. Non vengono soppressi globalmente.
- FAIL/ACTION: errori APT/Docker/Hermes, servizio non pronto o in riavvio, guest non ripristinato, sito non verificabile. Il comportamento di prosecuzione fra fasi/guest rimane.
- Telegram: fino a sei motivi distinti, prima ACTION e FAIL poi WARN; conteggio degli ulteriori avvisi; target LXC e nodo 2 normalizzati; stato di alimentazione del nodo 2; un solo riepilogo per reboot richiesto/verificato.
- NAS: l'eventuale motivo di errore viene incluso in breve nella notifica; i report restano in coda. I log di consegna sono separati dal report manutenzione.
- Hermes: dopo reboot la dashboard deve risultare attiva per una finestra di 20 secondi con PID, contatore riavvii e timestamp di avvio invariati. Una transizione fuori da active o un riavvio osservato produce FAIL. Non certifica disponibilità futura o risposta applicativa del gateway.

## Immagini e database

`postgres:18` è un ramo aggiornabile, non un digest immutabile. I pull ricevono le immagini pubblicate per quel tag. PostgreSQL resta nella major corrente; MariaDB nel ramo major.minor corrente. Le patch puntuali vengono allargate al rispettivo ramo già previsto dalla policy. Non viene effettuata una migrazione major dei dati.

Sono riconosciuti anche `docker.io/`, `index.docker.io/`, `registry-1.docker.io/` e `library/`, senza applicare regole Docker Hub a registri privati.

**Cambiamento operativo:** nel LXC 106 i nomi completi di Redis e Gotenberg ora attivano le regole mobili già previste: Redis passa dal riferimento `docker.io/library/redis:8` a `docker.io/library/redis:latest`; Gotenberg da `docker.io/gotenberg/gotenberg:8.25` a `docker.io/gotenberg/gotenberg:latest`. Il cambiamento si applica al prossimo job Docker generale, non durante l'applicazione della patch. PostgreSQL resta su 18. I file Compose e le password originali non sono riscritti: viene usato l'override gestito esistente.

CouchDB su latest mantiene il canale già scelto. NOTE non significa garanzia di compatibilità: viene eliminato l'avviso ripetitivo su una scelta accettata. Non è stato aggiunto un servizio/feed di verifica EOL. Il supporto futuro di un ramo DB non è certificato da questi script; una major può richiedere una migrazione applicativa.

Non aggiungere force-recreate per un mero cambio dell'ID dell'indice multiarch: nel collaudo PostgreSQL il manifest linux/amd64 coincideva.

## Applicazione senza installer

La repository è privata. Scaricare da GitHub, con il browser autenticato, **solo** [apply-alerts-4.1.1.py](../fixes/apply-alerts-4.1.1.py), usando Download raw file. Non salvare la pagina HTML. Non servono token GitHub sul nodo Proxmox.

Dal computer dove è stato scaricato, sostituendo IP_DEL_NODO1:

```bash
scp ./apply-alerts-4.1.1.py root@IP_DEL_NODO1:/root/
```

Sul nodo principale:

```bash
python3 /root/apply-alerts-4.1.1.py --check
python3 /root/apply-alerts-4.1.1.py --apply
```

Eseguire apply solo se check riesce. Apply ripete comunque tutti i controlli. La patch:

1. Usa il lock della manutenzione; se un job è attivo, esce senza interromperlo.
2. Rifiuta versioni locali inattese dei quattro file e controlla gli hash del payload.
3. Verifica sintassi Bash/Python ed esegue 19 test isolati con mock; nessun APT, Docker, SSH o servizio reale viene invocato dai test.
4. Crea una nuova release e cambia atomicamente il puntatore usato dai wrapper.
5. Conserva la vecchia release e i riferimenti in `/var/backups/pve-maintenance-alerts-*/`.
6. Non modifica configurazione, credenziali, cron (inclusi gli orari 05:00/09:00), volumi o stato dei guest; non manda notifiche di prova.

Le esecuzioni successive distribuiscono automaticamente il worker aggiornato ai guest. Non serve rilanciare subito una manutenzione né disabilitare cron. Una seconda applicazione della stessa patch è idempotente.

La vecchia release permette il rollback del codice. Non equivale a un rollback delle immagini o dei database aggiornati da job successivi.

## Collaudo

I test GitHub sono eseguiti su runner isolato, senza credenziali Proxmox, NAS o Telegram: [esecuzioni del ramo di validazione](https://github.com/Dav41K9/Codex-proxmox-autoupdate/actions?query=branch%3Afix%2Factionable-alerts-20261102).
Sono inclusi i test precedenti, 19 regressioni sugli avvisi e 5 prove della patch (check senza switch, applicazione/idempotenza/backup, modifiche locali rifiutate, lock occupato, test fallito che impedisce lo switch).

Il workflow è temporaneo sul ramo di validazione; non introduce servizi o scheduler sull'host. Il collaudo live della nuova notifica e delle nuove immagini resta al primo job successivo. Nessun updater è stato eseguito sul cluster dall'assistente.

Dopo un ciclo riuscito, si può eliminare `/root/apply-alerts-4.1.1.py`; conservare per ora release precedente e riferimenti di rollback. Gli ZIP in dist restano la baseline 4.1 e non includono questo hotfix.
