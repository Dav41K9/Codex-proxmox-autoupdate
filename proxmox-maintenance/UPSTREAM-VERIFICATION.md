# Verifiche upstream — 31 ottobre 2026

Sono state lette le fonti seguenti durante questa ricostruzione. Verifica documentale/sorgente, non esecuzione dei binari né pull dal registry. I riferimenti main/master sono mobili; la compatibilità con il runtime installato resta una prova live.

- **Hermes update --yes**: VERIFIED nella fonte. [Fonte](https://raw.githubusercontent.com/NousResearch/hermes-agent/main/hermes_cli/subcommands/update.py).
- **Watchtower registry GHCR**: VERIFIED nella fonte. [Fonte](https://raw.githubusercontent.com/nicholas-fedor/watchtower/main/build/goreleaser/stable.yaml).
- **Watchtower LogFmt/no-color**: VERIFIED nella fonte. [Fonte](https://raw.githubusercontent.com/nicholas-fedor/watchtower/main/docs/configuration/logging-and-output/index.md).
- **Watchtower run-once**: VERIFIED nella fonte. [Fonte](https://raw.githubusercontent.com/nicholas-fedor/watchtower/main/docs/configuration/scheduling/index.md).

- **docker compose up --wait / --wait-timeout**: VERIFIED, [riferimento CLI ufficiale](https://github.com/docker/compose/blob/main/docs/reference/compose_up.md). Attende running oppure healthy, non necessariamente un test applicativo.
- **pct reboot --timeout**: VERIFIED, [binding CLI pct](https://github.com/proxmox/pve-container/blob/master/src/PVE/CLI/pct.pm) e [schema vm_reboot](https://github.com/proxmox/pve-container/blob/master/src/PVE/API2/LXC/Status.pm). Il timeout riguarda lo shutdown, non certifica la disponibilità applicativa successiva; il coordinatore controlla separatamente boot ID e health.
- **ghcr.io/nicholas-fedor/watchtower**: pubblicazione prevista dal file GoReleaser stable ufficiale. Disponibilità del manifest per architettura/versione e aggiornamento reale: NOT VERIFIED, nessun Docker reale eseguito.
- **obsidian-vault write/list formato effettivo**: NOT VERIFIED. L'help generale fornito dall'utente conferma i comandi, ma non il formato di listing né una scrittura E2EE con rilettura. Integrazione rinviata.

