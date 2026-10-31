# Codex-proxmox

Ricostruzione verificabile del pacchetto di manutenzione Proxmox, 31 ottobre 2026.

**[Scarica proxmox-maintenance-v4-reviewed.zip](https://github.com/Dav41K9/Codex-proxmox/raw/refs/heads/main/dist/proxmox-maintenance-v4-reviewed.zip)**

[Sorgenti e istruzioni](proxmox-maintenance/README-IT.md) · [Revisione e limiti](proxmox-maintenance/REVIEW-IT.md) · [Test](tests/results.txt) · [SHA256](dist/SHA256SUMS)

Il precedente ambiente e il suo ZIP non sono recuperabili: questa è una nuova ricostruzione dagli allegati originali e dalle decisioni della conversazione, non una copia bit per bit. Test locali con mock, nessuna esecuzione su Proxmox e nessun cron attivato. Non contiene la configurazione reale, credenziali, dossier privato o output del server.

Il pacchetto è una **candidata per prove live controllate**, non una certificazione per avvio unattended. La pubblicazione su GitHub conserva sorgenti, prove e archivio oltre la durata della sessione.

Riproduzione test: `python3 -m unittest discover -s tests -v`.
