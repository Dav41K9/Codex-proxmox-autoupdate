# Import Hermes — fase futura, non attiva

Non creare ancora un cron da questo documento. La consegna NAS→inbox Hermes è rinviata per scelta utente. L'helper incluso non rende questa integrazione già operativa.

Nella futura configurazione, Hermes dovrà usare la propria skill **obsidian-vault E2EE**, leggere `Friday/INDEX.md`, verificare il percorso canonico e la sintassi runtime di `obsidian-vault list/read/write`. L'helper assume `write PATH` con stdin e lettura esatta: confermare con help e una nota di prova, senza stampare credenziali.

Una nota viene archiviata localmente solo dopo rilettura identica; una collisione con contenuto diverso interrompe senza sovrascrivere. Elaborare gli arretrati, usare il lock condiviso con la manutenzione, niente accessi diretti a database, file, API grezze o dati CouchDB. Nessuna password o modifica della cifratura.

La provenienza dei report trasferiti dal NAS va verificata tramite manifest/ricevute prima della futura importazione. Il bridge, il cron Hermes e la verifica E2EE completa restano NOT TESTED / non installati.
