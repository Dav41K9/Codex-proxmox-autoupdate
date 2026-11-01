# Codex-proxmox — manutenzione 4.1

**[Scarica il pacchetto aggiornato 4.1](https://github.com/Dav41K9/Codex-proxmox/raw/refs/heads/main/dist/proxmox-maintenance-v4.1-reviewed.zip)**

[Guida breve](proxmox-maintenance/README-IT.md) · [Correzioni](proxmox-maintenance/CHANGELOG-4.1.md) · [Test e limiti](proxmox-maintenance/VALIDAZIONE-4.1.md) · [Risultati](tests/results.txt) · [SHA256](dist/SHA256SUMS)

Due job: generale e WordPress. Output a video, report completi, Telegram breve. La4.1 elimina i mask dei timer che avevano causato i guasti del collaudo e include la riparazione dei journal legacy. Nessuna configurazione reale o log privato è pubblicato.

Installazione dal pacchetto estratto, come root sul nodo principale:

```bash
bash install.sh --check
bash install.sh --install
maintenance-recover.sh
```

Leggere l'esito di ciascun comando. Il recupero non esegue aggiornamenti, WOL o spegnimenti. Poi collaudare `update-web.sh` e `update-proxmox-guests.sh` prima di abilitare cron. Non serve --retry per ripetere un lancio manuale. Il cron resta un passo esplicito: `bash install.sh --enable-cron`.

La versione precedente è preservata nella storia Git; le patch in `fixes/` sono storiche e confluite nella4.1. La guida lunga del primo collaudo non va usata come procedura di installazione della nuova versione.

Test riproducibili: `python3 -m unittest discover -s tests -v`. Nessuna esecuzione su Proxmox è stata effettuata dalla revisione.
