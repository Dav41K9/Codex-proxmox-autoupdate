# Correzioni candidate — 1 novembre 2026

**Non è una nuova release approvata per cron. Il ZIP in dist resta quello precedente.**

Il codice sorgente della release pubblicata resta invariato; le modifiche sono salvate nella patch separata `2026-11-01-candidate.patch`. Nessuna modifica è stata applicata su Proxmox. Non sono pubblicati log reali o configurazioni utente.

Correzioni implementate nella candidata:

- Guard: rimuovere tutti i mask temporanei di propria competenza prima di riavviare qualunque timer; mantenere journal e non riavviare timer se un unmask fallisce. Il vecchio ordine poteva tentare lo start del timer con servizio dipendente ancora mascherato. Confermato da test mirato, causa specifica dei guasti live ancora da confrontare con diagnostica.
- Console: eventi visibili e output worker inoltrato tramite tee, conservando pipefail e il codice di errore. Progresso delle fasi Compose visibile; nessuna necessità di tail per seguire il job. Questo non rende il processo indipendente da SSH: interrupt/disconnessioni restano possibili.
- Telegram: due emoji, conteggi OK/FAIL/WARN per target, priorità alle richieste d'intervento e fino a otto errori sintetici; dettagli nel report. Non viene ridotto il report Markdown.
- HTTP404: messaggio corretto a «check fallito; disponibilità sito non accertata». Non viene cambiato endpoint né accettato404 come successo. URL corretto da confermare dall'utente.
- Paperless: un fallimento del guard non viene più etichettato automaticamente come «import attivo»; può essere coordinamento incompleto.
- Deduplica: messaggio spiega che anche una run fallita/interrotta occupa il giorno; nessun retry automatico o cancellazione del journal.

Prove locali: **58 test passati**, sintassi Bash verificata. Output in `2026-11-01-tests.txt`. `test_candidate.py` è la suite completa aggiornata, da usare sulla copia candidata. Per riprodurre in una checkout di laboratorio della release originale, non sull'host installato:

```bash
patch --dry-run -p1 < fixes/2026-11-01-candidate.patch
patch -p1 < fixes/2026-11-01-candidate.patch
python3 -m unittest discover -s fixes -p test_candidate.py -v
```

Restano da chiarire con l'utente: origine dell'interruzione rc130, endpoint WordPress corretto e causa esatta della preparazione/ripristino timer di LXC106. L'assenza di perdita dati non è dimostrata soltanto da container running o nomi volume invariati.

## Diagnostica prima del recupero

`diagnose-timers.sh` legge journal, stato systemd e poche classi di errori. Non legge la configurazione privata, non esegue Docker, non avvia guest e non modifica timer. Eseguirlo come root sul nodo principale e condividere l'output nella conversazione; non pubblicare gli output nella repo.

Fino alla diagnosi: niente attivazione cron o ulteriori retry a catena. Non cancellare state.sqlite/quarantine.json/worker status e non fare unmask globale. Il codice130 è compatibile con SIGINT, non prova chi o cosa abbia interrotto il processo. Il mantenimento del nodo secondario acceso dopo errore è la policy conservativa prevista.
