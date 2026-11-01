# Validazione4.1 — 1 novembre2026

**80 test passati nella nuova esecuzione**, non risultati attribuiti al vecchio ambiente. Log completo: `tests/results.txt`.

Controlli statici: `bash -n` su6 script e parsing AST su6 Python. ShellCheck non disponibile in questo ambiente: non viene dichiarato eseguito.

Comandi riproducibili dalla radice estratta/repository:

```bash
python3 -m unittest discover -s tests -v
for f in proxmox-maintenance/*.sh; do bash -n "$f"; done
```

Copertura significativa:

- errori APT che non impediscono Docker, nessun full-upgrade dopo errore indici, attesa/riprova solo dell'errore lock indici;
- Hermes eseguito e atteso anche quando fallisce, marker reboot, zero comandi Docker1000;
- timer custom Paperless fermato/ripristinato senza mask; timer originariamente inattivo non avviato; import attivo mai terminato;
- ripristino legacy: tutti gli unmask prima di ogni start timer; journal conservato in caso di errore;
- lock POSIX dpkg realmente conteso con un secondo processo; descriptor ereditato dal worker per il ripristino;
- attesa boot guest (running/degraded, con limite) prima del worker e dopo reboot;
- guest temporaneo ripristinato, guest occupato lasciato acceso con ACTION, guest inizialmente acceso non spento;
- recupero WordPress limitato a200, generale su tutti i pendenti, nessun replay di vecchi aggiornamenti nel report;
- lanci manuali ripetibili nello stesso giorno, cron deduplicato, lock occupato senza avviare un secondo job;
- HTTP homepage locale+HTTPS pubblico: successo di entrambi richiesto; errore pubblico non nascosto da locale200; login non interrogato;
- identità Compose/file/envfile, profili WP, volumi persistenti, prosecuzione fra progetti, standalone esclusivi Watchtower, stderr errori non scartato;
- Portainer agent: config/volumi preservati nei mock e rollback del solo agent se stop/rename/create/start falliscono;
- report immutabili, recupero dopo errore di scrittura, cache10, outbox preservata, NAS readback/collisioni/retention60giorni;
- Telegram JSON.ok=false non accettato, Unicode, riepilogo raggruppato con priorità agli interventi;
- installer eseguito in filesystem di prova: check senza installazione, installazione non bloccata da warning scanner, cron bloccato dai conflitti prima delle modifiche, esattamente due righe --scheduled;
- utility di recupero con pct/ssh fittizi: nessun APT/Docker/WOL/reboot/shutdown e nessun avvio dei guest spenti.

I test dell'installer modificano solo una directory temporanea, sostituendo i percorsi assoluti e simulando scanner/comandi esterni. Non sono installazioni su Proxmox. Timer/systemd, Docker Engine/Compose, SSH/WOL, NAS e Telegram sono mock dove indicato; non dimostrano disponibilità rete, rollback DB o compatibilità di ogni configurazione reale.

Non sono stati eseguiti i due updater o il recupero sul cluster dell'utente. Prima dei cron servono un ciclo manuale WordPress, uno generale, controllo timer/stato iniziale e prove applicative. Lo stato live noto ha confermato HTTP200 delle due homepage e i difetti dei vecchi mask; non certifica questa release finché non viene collaudata.
