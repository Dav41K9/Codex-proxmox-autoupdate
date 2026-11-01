# Manutenzione Proxmox 4.1 — uso pratico

Due job, come nelle versioni iniziali:

- `update-proxmox-guests.sh`: APT sui nodi/LXC/VM configurati, Docker negli altri guest, Hermes nel1000. Su200 fa APT, non pull/build/up Docker.
- `update-web.sh`: Docker completo del200, Compose/build e standalone, snapshot e controlli WordPress. Non aggiorna altri guest.

Entrambi mostrano l'avanzamento direttamente a video, scrivono un report Markdown completo e inviano un riepilogo breve Telegram. Nessun nuovo servizio residente, nessun pacchetto Python esterno.

## Installazione e recupero della versione precedente

Conserva `/etc/update-guests.conf` esistente: l'installer non cambia credenziali, password, `.env`, elenco guest o directory Compose. Eseguire come root sul nodo principale, dalla directory `proxmox-maintenance` del nuovo ZIP:

```bash
bash install.sh --check
bash install.sh --install
maintenance-recover.sh
```

Controllare l'esito di ogni comando prima di passare al successivo. `--install` non crea cron e non avvia aggiornamenti. Lo scanner dei vecchi scheduler segnala eventuali conflitti ma non impedisce l'installazione del codice correttivo. I conflitti continuano a bloccare `--enable-cron`.

**`maintenance-recover.sh` serve una volta per il difetto della versione precedente:** ripristina soltanto i timer registrati dal nostro journal, sull'host, nei LXC accesi e sui target SSH configurati/raggiungibili. Non esegue APT, Docker, WOL, reboot o shutdown; non avvia guest spenti. Usa il lock comune e si rifiuta di intervenire mentre un worker è ancora attivo. Non cancella il journal che serve a riportare i guest allo stato iniziale. Se termina con FAIL, leggere il target e l'errore; non cancellare lock o stato per aggirarlo.

Se un vecchio cron è già attivo, metterlo in pausa prima della migrazione: l'installer non ferma job in esecuzione e non rimuove automaticamente schedulazioni amministrative. Nel collaudo comunicato dall'utente il cron di questo updater era assente.

## Collaudo manuale

In `/etc/update-guests.conf`, verificare `DRY_RUN=0` e `SEND_TELEGRAM=1` per un'esecuzione reale con notifiche; non riscrivere il file con un esempio incompleto.

```bash
update-web.sh
```

Attendere la fine e controllare il report indicato a video, Telegram, homepage, carrello/checkout di test e volumi. Il comando fa aggiornamenti reali: usare una finestra di manutenzione con backup verificato. Non serve `--retry` per un secondo lancio manuale nello stesso giorno. Se un altro job è in corso, il nuovo lancio manuale si ferma con un messaggio, senza accodare un altro aggiornamento.

Dopo un collaudo WordPress soddisfacente:

```bash
update-proxmox-guests.sh
```

Verificare timer ripristinati, guest al loro stato iniziale, Hermes aggiornato e reboot completato, applicazioni disponibili. Un nodo2 già acceso resta acceso. Il nodo2 svegliato da questa esecuzione viene spento dopo il successo del worker e il controllo dei lock; errori reali lo lasciano acceso con alert. Un nodo rimasto acceso da una precedente esecuzione fallita è ora «già acceso»: non viene spento presumendo che nessuno ci stia lavorando.

I comandi sono in primo piano: non occorre tail/tmux per vedere l'avanzamento. Chiudere SSH o premere Ctrl-C nell'updater può comunque interrompere il coordinatore. Ctrl-C in una diversa sessione `tail -F` ferma soltanto quel tail. La notifica finale e il ritorno del prompt identificano la fine del job; non interromperlo mentre aggiorna.

## Attivazione cron

Solo dopo il collaudo live, senza FAIL/ACTION irrisolti:

```bash
bash install.sh --enable-cron
systemctl is-active cron
```

L'installer verifica configurazione notifiche, DRY_RUN disattivo, fuso Europe/Zurich/Europe/Rome e assenza di scheduler concorrenti rilevati. Non installare gli stessi comandi anche nel crontab root. La scansione non scopre ogni scheduler esterno o wrapper dinamico: controllare eventuali aggiornamenti Portainer/Watchtower/Hermes aggiuntivi.

- WordPress ogni giorno03:30.
- Generale lunedì/mercoledì/venerdì05:00.
- Solo il cron usa `--scheduled`, che mantiene deduplica giornaliera e attesa del lock fino a sei ore. I lanci manuali sono ripetibili, sempre senza sovrapposizione. `--retry` resta compatibile per un retry esplicito con `--scheduled`, ma non è necessario nell'uso normale.

Un job manuale già completato quel giorno può far saltare quello schedulato per la deduplica. Il lock serializza i due job se il notturno dura oltre le05:00.

## Cosa resta semplice e cosa viene protetto

- **APT:** niente più mask di timer o servizi. Full-upgrade/autoremove attendono il lock APT fino a300s; nessun timeout che uccide dpkg durante la transazione. Indici APT incompleti impediscono il full-upgrade, ma le altre fasi/guest proseguono e il report conserva FAIL.
- **Paperless106:** stop temporaneo del solo `paperless-import.timer`, conservandone lo stato precedente; nessun mask, drop-in o modifica del file unit. Non si termina un import in corso. Se è attivo, le fasi che richiedono coordinazione vengono rinviate e segnalate; gli altri progetti possono proseguire. Il timer viene ripristinato anche se il guest rimane acceso per un problema. Attività lanciate manualmente o da scheduler esterni non sono coordinate automaticamente: evitare avvii concorrenti durante la manutenzione.
- **Power:** worker lock e lock POSIX APT/dpkg controllati prima di reboot/shutdown; niente `pct stop` forzato. Se una transazione o import è attivo, LXC lasciato acceso con ACTION.
- **Hermes1000:** APT → `hermes update --yes` come hermes, atteso senza timeout → reboot completo. Zero comandi Docker, incluse interrogazioni. Dashboard verificata dopo reboot; gateway da verificare anche funzionalmente.
- **WordPress:** homepage locale con Host corretto più homepage HTTPS pubblica, redirect HTTPS limitati e certificato verificato. Nessun controllo su login privato. HTTP200 non certifica checkout o consistenza DB. Il job WordPress recupera solo200; i pendenti degli altri guest sono segnalati e lasciati al generale. I risultati dei vecchi worker non vengono ripubblicati come nuovi aggiornamenti.
- **Dati:** identità Compose completa, file/envfile e volumi verificati, niente `down -v`, niente volume prune, pma escluso, password intatte. Prune immagini solo dopo assenza di FAIL.
- **Snapshot:**200 al massimo2 generali+3 WordPress al termine del cleanup riuscito;106 escluso; altri2 generali. Snapshot manuali estranei non cancellati. Snapshot falliti segnalati. Un errore di eliminazione può lasciare copie oltre il limite; nessun rollback DB automatico.
- **Report:** cache host10, NAS60giorni, outbox non consegnata preservata. Report dettagliato; Telegram conteggi per target e problemi prioritari, non il report integrale. I log tecnici sono privati e possono contenere output dei programmi: non pubblicarli automaticamente.
- **Hermes/Obsidian:** import dei report ancora rinviato come concordato; nessun nuovo cron/bridge e nessun accesso diretto ai dati CouchDB.

## Dove leggere i risultati

- Report recente: `/var/lib/proxmox-maintenance/latest.md`.
- Report per run: `/var/lib/proxmox-maintenance/reports/`.
- Debug completo: `/var/log/pve-maintenance.log`.
- Consegne NAS/Telegram: `/var/lib/proxmox-maintenance/delivery.log`.
- Archivio NAS: `/mnt/pve/NAS/proxmox-maintenance/reports/` per impostazione predefinita.

Il report distingue la manutenzione dalla consegna: controllare che arrivi Telegram e che il file sia effettivamente sul NAS. Un NAS irraggiungibile conserva i report in outbox e genera un avviso. Non è possibile garantire una notifica Telegram quando Telegram/rete sono indisponibili: l'errore rimane nel log e nell'exit code.

## Parametri e limiti

Rimangono quelli già documentati per l'inventario, SSH/WOL, directory Compose, notifiche, `WEB_HTTP_HOST`, `NAS_MOUNT`, start/stop LXC, snapshot e timeout APT/Compose. La configurazione viene trattata come codice Bash root fidato. Nessun nuovo parametro è necessario per la migrazione.

I rami database numerici restano sulla linea scelta; immagini applicative note seguono i canali mobili concordati. Una immagine `latest` può includere cambiamenti incompatibili: cinque snapshot non sostituiscono un backup applicativo e una prova di restore, soprattutto per mount esterni/NAS. Gli aggiornamenti major DB non vengono inventati tramite cambio automatico di un tag numerico.

Questa release è verificata staticamente e con simulazioni, non è stata eseguita sul cluster dell'utente. I test e i loro limiti sono in `VALIDAZIONE-4.1.md`.
