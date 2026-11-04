# Validazione hotfix 4.1.2

Commit testato: `6610af67dc7cd1b5b8d2d6d6510a15cf6c9f9b13`.

[GitHub Actions: 131 test superati](https://github.com/Dav41K9/Codex-proxmox-autoupdate/actions/runs/41905141488), 2026-11-04. Sintassi Bash e Python superata. Test eseguiti come root in runner Ubuntu isolato, senza accesso al cluster, al NAS o a credenziali utente.

Comandi:
```bash
find proxmox-maintenance scripts -type f -name '*.sh' -exec bash -n {} +
python3 -m compileall -q proxmox-maintenance tests fixes
sudo python3 -m unittest discover -s tests -v
```

Risultato: `Ran 131 tests in 5.576s — OK`.

Aggiunti 11 test di archiviazione/policy e 7 del file di applicazione. Verificati: default privato, opt-in ACL, mount NFS esatto, symlink, collisioni, contenuto corrotto in rilettura, errori di scrittura, coda conservata, retention, passaggio policy dal coordinatore, check senza modifiche, applicazione ripetibile, backup, lock occupato, modifiche locali sconosciute, test fallito e rollback della configurazione se fallisce il cambio release.

Il test del vecchio hotfix 4.1.1 confronta ora il risultato con il proprio payload storico, anziché con i sorgenti correnti che includono 4.1.2. Il vecchio hotfix non è stato modificato.

Dopo questa esecuzione sono aggiornati solo documentazione/README e rimosso il workflow temporaneo da main. Il workflow rimane nel ramo `fix/nas-acl-20261104`. Codice applicativo, hotfix e test coincidono con il commit verificato.

Non eseguiti: collaudo su NFS Synology reale, verifica dell'effettiva policy NFS/ACL, riparazione dei servizi Hermes, update o reboot dei guest. I comandi di collaudo sono nella [guida](NAS-ACL-E-HERMES-4.1.2-IT.md).
