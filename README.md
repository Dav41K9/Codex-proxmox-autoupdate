# Codex Proxmox autoupdate

Manutenzione Proxmox con due job separati: generale (APT nodi/guest, Docker e Hermes) e WordPress (Compose/build e standalone LXC 200).

## Aggiornamento corrente: hotfix avvisi 4.1.1

- Condizioni accettate registrate come NOTE; WARN/FAIL per situazioni su cui intervenire.
- Telegram con motivi sintetici degli avvisi, target senza doppioni e stato finale nodo 2.
- Promemoria mensile dei database che richiedono una migrazione major pianificata.
- Regole immagini coerenti anche con nomi Docker Hub completi.
- Controllo della dashboard Hermes durante una finestra di stabilità.

[Spiegazione, limiti e comandi](docs/AVVISI-4.1.1-IT.md).

[Singolo file da scaricare e applicare](fixes/apply-alerts-4.1.1.py): non richiede l'installer, non modifica cron/configurazione e conserva la release precedente. Repository pubblica: scaricare il singolo file con curl sul nodo principale, preferibilmente dal commit indicato nella guida di consegna.

## Baseline 4.1

[Guida originale](proxmox-maintenance/README-IT.md) · [Validazione baseline](proxmox-maintenance/VALIDAZIONE-4.1.md) · [ZIP 4.1](dist/proxmox-maintenance-v4.1-reviewed.zip) · [Checksum ZIP](dist/SHA256SUMS).

Gli ZIP sono conservati come baseline e **non includono il nuovo hotfix**. I sorgenti in proxmox-maintenance includono la correzione corrente. I report e le configurazioni reali dell'utente non vengono pubblicati nella repository.

## Test

```bash
python3 -m unittest discover -s tests -v
for f in proxmox-maintenance/*.sh; do bash -n "$f"; done
```

Le prove del file hotfix richiedono una checkout Git con la baseline nella storia e un runner root isolato; non eseguirle per curiosità sul cluster produttivo. Sul nodo, usare i 28 test incorporati nella modalità --check del file hotfix.
