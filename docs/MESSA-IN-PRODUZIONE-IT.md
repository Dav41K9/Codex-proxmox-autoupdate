# Procedura attuale — versione4.1

La vecchia guida di collaudo è conservata nella storia Git. La nuova procedura, più breve, è in [README-IT.md](../proxmox-maintenance/README-IT.md).

1. Scaricare [il ZIP4.1](https://github.com/Dav41K9/Codex-proxmox/raw/refs/heads/main/dist/proxmox-maintenance-v4.1-reviewed.zip) e verificare [SHA256SUMS](../dist/SHA256SUMS).
2. Estrarre in una directory nuova; entrare in `proxmox-maintenance`.
3. Tenere i cron del nostro updater in pausa durante il collaudo. Non fermare transazioni APT/dpkg in corso.
4. Eseguire `bash install.sh --check`, quindi `bash install.sh --install`; verificare l'esito di ogni comando.
5. Eseguire una volta `maintenance-recover.sh`: ripara i timer lasciati dalla versione precedente, senza aggiornamenti o power. Non cancellare il journal per aggirare errori.
6. Confermare nella configurazione esistente `DRY_RUN=0` e `SEND_TELEGRAM=1`, senza cambiare credenziali, inventario o directory.
7. Con backup verificato e nella finestra di manutenzione, eseguire `update-web.sh`; avanzamento direttamente sul terminale. Verificare sito/dati, report, NAS e Telegram.
8. Eseguire `update-proxmox-guests.sh`; verificare stato guest/nodo2, applicazioni, Hermes e timer. Il nodo2 già acceso resta acceso.
9. Solo dopo un collaudo soddisfacente, `bash install.sh --enable-cron`. Il file cron contiene esattamente i due job con --scheduled; non duplicarli nel crontab root.

Non occorre --retry per una nuova prova manuale. Non è richiesto tail/tmux per seguire il job; chiudere SSH può comunque interrompere il coordinatore. Le simulazioni non sostituiscono il controllo sul cluster reale.
