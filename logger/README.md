# Selco Logger

Applicazione per il PC Windows della sezionatrice Selco (SEZ1). Legge il log degli eventi della macchina
(`Event.log`) e manda a Odoo:

- le registrazioni di **lavoro** e di **fermo** (`mrp.workcenter.productivity`) con i pannelli prodotti;
- gli **stati macchina** dovuti agli allarmi OSI monitorati (`mrp.workcenter.state`);
- la richiesta di **stampa dei bindelli** al primo pezzo finito di ogni programma.

È l'evoluzione di [antexsrl/loggerselco](https://github.com/antexsrl/loggerselco). Le regole sono descritte in
[`docs/progetto.md`](../docs/progetto.md): lettura del log §9, registrazioni §10.

## Come funziona

```mermaid
flowchart LR
    LOG[Event.log] -->|ogni 2 s, solo i byte nuovi| R[eventlog.py]
    R -->|righe| P[events.py]
    P -->|eventi| E[productivity.py<br/>regole R1-R10]
    E -->|operazioni| Q[(coda in state.json)]
    Q -->|quando Odoo risponde| S[odoo_sync.py]
    S -->|JSON-RPC| O[Odoo]
```

| File | Compito |
|---|---|
| `main.py` | icona nella barra di sistema, finestra di configurazione, timer (log ogni 2 s, Odoo ogni `interval` s) |
| `selco.py` | collega i pezzi e salva lo stato in `state.json` dopo ogni passo |
| `eventlog.py` | lettura incrementale di `Event.log`: non tiene aperto il file, legge solo i byte nuovi, riprende dalla posizione salvata, recupera le righe da `EvtBack.log` quando OSI ruota il log |
| `events.py` | trasforma le righe del log in eventi |
| `productivity.py` | regole R1–R10: il tempo va al programma che produce pannelli, fermi sotto i 3 minuti restano lavoro, allarmi sotto `max_time` ignorati |
| `odoo_sync.py` | coda delle operazioni verso Odoo, in ordine; con Odoo irraggiungibile la coda resta in `state.json` e riparte al ciclo successivo |

La richiesta di stampa dei bindelli viene inviata subito, senza aspettare il ciclo di `interval` secondi.

## Stato (`state.json`)

Contiene la posizione nel log, lo stato delle registrazioni aperte e la coda verso Odoo. Viene scritto su un
file temporaneo e poi rinominato, quindi uno spegnimento improvviso non lo lascia a metà. Al riavvio il logger
riprende esattamente da dove era rimasto, anche dopo giorni di VPN non disponibile.

**Primo avvio:** senza `state.json` il logger parte dalla fine del log attuale; gli eventi precedenti non
vengono inviati. Nel passaggio dal vecchio logger, fermare il vecchio e avviare subito il nuovo. Il vecchio
`activeprogram.json` non viene letto.

## Configurazione (`configuration.json`)

Invariata rispetto al vecchio logger: `file`, `filebkp`, `server`, `port`, `db_name`, `user`, `password`,
`workcenter_code`, `interval`, `logfile`. `interval` è ora l'intervallo di invio a Odoo; il log viene letto
ogni 2 secondi in ogni caso.

## Installazione

Python 3.8 o successivo.

```bash
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python main.py
```

## Test

```bash
cd tests
python -m unittest -v
```

`test_replay` e `test_selco` usano i log reali della macchina: cartella indicata da `SELCO_LOGS`
(predefinita `/home/odoo-dev/loggerselco/log`), altrimenti vengono saltati. `test_odoo_sync` richiede
`odoorpc` e `pytz`.
