# 4.1 — correzioni del collaudo e semplificazione

Baseline funzionale: v3.1, con v2.4 solo come riferimento storico. Conservata la separazione originale generale/WordPress; recuperata la visibilità diretta delle fasi e una notifica breve. Non vengono riproposti errori mascherati, pull senza ricreazione, esclusione mancata di Docker1000 o stop forzati delle vecchie versioni.

1. Eliminata la quarantena tramite nuovi mask systemd. La compatibilità con i vecchi journal resta solo per riparare i blocchi già lasciati in giro.
2. Ripristino legacy in due passaggi: prima tutti gli unmask di propria competenza, poi i timer originariamente attivi. Nessun riavvio di timer se un unmask fallisce.
3. Paperless: stop/start del solo timer, compatibile con unit custom in /etc; nessuna interruzione del servizio import. Stato originario preservato.
4. APT usa l'attesa del lock nativa, lasciando i normali timer APT intatti.
5. Output live via tee con pipefail; fasi Compose visibili e stderr dei fallimenti nel log privato. Status e exit code non diventano OK perché tee riesce.
6. Telegram sintetico: due emoji, conteggi per target, priorità agli interventi manuali, warning/riavvii rimandati al report completo. Report invariato nella completezza.
7. Health WordPress basato sulla homepage locale/pubblica verificata dall'utente; niente dipendenza da wp-login.php. Redirect non etichettato da solo come sito down.
8. Recupero del notturno confinato a200; nessun replay nel report di APT/Docker eseguiti da vecchi worker sugli altri guest.
9. Niente obbligo --retry per i lanci manuali. Dedup giornaliera riservata al cron --scheduled; lock comune sempre presente.
10. Installer: conflitti scheduler segnalati ma non bloccanti per installare il fix; rimangono bloccanti per abilitare cron. Controlli di abilitazione prima delle modifiche. Configurazione reale non riscritta, backup esistenti conservati.
11. Attesa esplicita del boot dei guest avviati temporaneamente e dopo reboot, prima dei controlli applicativi.
12. Utility di riparazione una tantum maintenance-recover.sh, senza aggiornamenti o azioni di power. Non è un terzo job periodico.

Restano: APT/Docker indipendenti fra fasi e guest, Hermes atteso e riavviato, zero Docker1000, no snapshot106, cinque snapshot200 totali gestiti, WOL/shutdown condizionale nodo2, avvisi su guest non ripristinati, cache10/NAS60giorni, nessun nuovo servizio residente.

Non viene dichiarato che i dati siano consistenti soltanto perché un container è running. Non sono stati effettuati test live o operazioni sul server dell'utente.
