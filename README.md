# Codex Proxmox autoupdate

Manutenzione Proxmox con due job separati: generale (APT nodi/guest, Docker e Hermes) e WordPress (Compose/build e standalone LXC 200).

## Aggiornamento corrente: hotfix NAS 4.1.2

Modalità esplicita `NAS_PERMISSION_MODE=server-acl` per NAS con ACL verificate sul server. La modalità predefinita resta privata. Mount NFS esatto, controllo symlink/collisioni, checksum e conservazione degli arretrati restano attivi.

[Guida NAS e riparazione del conflitto tra servizi Hermes](docs/NAS-ACL-E-HERMES-4.1.2-IT.md) · [Singolo file hotfix](fixes/apply-nas-acl-4.1.2.py).

Si applica alla 4.1.1: conserva release e configurazione, non richiede l'installer e non modifica i cron. Usare `--server-acl` solo dopo aver verificato le ACL del NAS. La riparazione Hermes descritta nella guida è separata e riguarda le due unità concorrenti, non modifica il controllo di stabilità.

## Hotfix avvisi 4.1.1

- Condizioni accettate registrate come NOTE; WARN/FAIL per situazioni su cui intervenire.
- Telegram con motivi sintetici degli avvisi, target senza doppioni e stato finale nodo 2.
- Promemoria mensile dei database che richiedono una migrazione major pianificata.
- Regole immagini coerenti anche con nomi Docker Hub completi.
- Controllo della dashboard Hermes durante una finestra di stabilità.

[Spiegazione e comandi](docs/AVVISI-4.1.1-IT.md) · [Hotfix 4.1.1](fixes/apply-alerts-4.1.1.py).

## Baseline 4.1

[Guida originale](proxmox-maintenance/README-IT.md) · [Validazione baseline](proxmox-maintenance/VALIDAZIONE-4.1.md) · [ZIP 4.1](dist/proxmox-maintenance-v4.1-reviewed.zip) · [Checksum ZIP](dist/SHA256SUMS).

Gli ZIP sono conservati come baseline e **non includono gli hotfix**. I sorgenti in proxmox-maintenance includono la correzione corrente. I report e le configurazioni reali dell'utente non vengono pubblicati nella repository.

## Test

```bash
python3 -m unittest discover -s tests -v
for f in proxmox-maintenance/*.sh; do bash -n "$f"; done
```

Le prove complete dei file hotfix richiedono una checkout Git con le baseline nella storia e un runner root isolato; non eseguirle sul cluster produttivo. Sul nodo usare `--check`: 28 test incorporati nel file 4.1.1 oppure 11 nel file 4.1.2.
