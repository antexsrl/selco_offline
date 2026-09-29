# Stampa bindelli SEZ1 con VPN non disponibile — documento di progetto

Stato: **bozza per revisione** · Ultimo aggiornamento: 30/09/2026

## 1. Contesto e problema

Il PC della sezionatrice Selco (SEZ1) e le sue stampanti si trovano in un sito diverso da quello del server
Odoo e comunicano con Odoo attraverso una VPN. Il programma *Selco Logger*
([antexsrl/loggerselco](https://github.com/antexsrl/loggerselco)) legge il log della sezionatrice e,
al primo pezzo finito di ogni programma di taglio, chiede a Odoo di stampare i bindelli di produzione.

Quando la VPN cade il PC non vede Odoo, quindi **i bindelli non escono**. Al ritorno della VPN il logger
ripete le chiamate e i bindelli arretrati escono tutti insieme, quando i pezzi sono già stati tagliati e
spostati.

**Obiettivo:** i bindelli (e le etichette ID in ZPL) devono uscire al momento del taglio anche quando
Odoo non è raggiungibile. Al ritorno della VPN Odoo deve risultare allineato, come se la stampa fosse
avvenuta normalmente.

## 2. Come funziona oggi

```mermaid
sequenceDiagram
    participant Selco as Sezionatrice (Event.log)
    participant PC as PC SEZ1 — Selco Logger
    participant Odoo as Server Odoo
    participant CUPS as CUPS (lato Odoo)
    participant PRT as Stampanti sito SEZ1

    Selco->>PC: PRODUCED PIECE (primo pezzo del programma)
    PC->>Odoo: cerca lo schema con barcode = nome programma
    PC->>Odoo: print_layout_labels_from_cutting_plan()
    Odoo->>Odoo: decide quali bindelli stampare
    Odoo->>Odoo: genera il PDF (QWeb + wkhtmltopdf + etichetta cliente)
    Odoo->>CUPS: lavoro di stampa
    CUPS-->>PRT: attraverso la VPN
```

### 2.1 Chi decide cosa stampare

`mrp.sale.plan.layout.print_layout_labels_from_cutting_plan()` (modulo `oi_mrp_label`). Per ogni riga
dello schema:

- il tipo di bindello è `frame` (cartella) se il materiale è della categoria cartella
  (`antex_product.product_car_category`), altrimenti `support`;
- **pezzi da coprire** = pezzi degli schemi già stampati + pezzi di questo schema − pezzi dei bindelli già
  stampati;
- stampa i bindelli non ancora stampati, in ordine di numero (`label_sub`), finché la quantità non è
  coperta;
- segna i bindelli come stampati (`is_printed`) e lo schema come stampato (`printed_label`).

La "produzione fatta finora" non viene dai contatori della macchina: sono solo questi due indicatori.

Esempio, riga da 60 pezzi con 3 bindelli da 20:

| Taglio | Pezzi dello schema | Tagliati finora | Già coperti | Da coprire | Stampa |
|---|---|---|---|---|---|
| Schema A | 15 | 15 | 0 | 15 | bindello 1 |
| Schema B | 15 | 30 | 20 | 10 | bindello 2 |
| Schema C | 30 | 60 | 40 | 20 | bindello 3 |

L'ordine di taglio non cambia il totale: tagliando C prima di B escono comunque i tre bindelli, cambia solo
quale schema fa uscire quale bindello.

> **Correzione già fatta (oi_mrp_label 12.0.32.0.0, 28/09/2026).** Il conteggio dei pezzi tagliati era
> limitato al piano di taglio in corso, mentre i bindelli stampati erano contati su tutti i piani. Una
> riga divisa su due piani dello stesso tipo non stampava i bindelli del secondo piano. Lo stesso
> succedeva con una riga presente due volte nello stesso schema. La logica descritta qui è quella corretta.

### 2.2 Come si stampa

`mrp.production.label.print_label()`:

| Caso | Comportamento |
|---|---|
| Bindello cartella (`frame`) | una stampa |
| Bindello supporto con `highlighted_label` | prima pagina (o le prime 2 se fronte/retro) dal cassetto `TRAY2` (carta colorata), il resto da `TRAY1`, poi le copie restanti |
| Bindello supporto normale | `copies` = `product_mod_id.label_copies`; 2 copie fisse per i clienti `025` e `001` |
| Ordine con etichetta cliente (`label_pdf`) | fronte/retro (`Duplex=DuplexNoTumble`); il PDF contiene bindello + etichetta cliente sul retro (casi speciali per i clienti `025`, `001`, `032` in `ir_actions_report._run_wkhtmltopdf`) |
| Etichetta aggiuntiva (`additional_label`) | report `report_label_attachment`, `additional_label_copies` copie |
| ID PDT | `pcs_id` della riga dello schema, stampato sulla prima fase di sezionatura |

Le etichette ID in ZPL (`antex_jit_label`) vengono stampate subito dopo, per i modelli con
`zpl_print_label`. Sono tante copie quanti i pezzi della riga nello schema (`qt_on_layout`), con un testo
ZPL per ordine di produzione. Non dipendono dal calcolo dei bindelli.

Stampanti usate (utente Odoo `sezselco`): `Brother_HL-L6450DW_series` per i bindelli,
`ARGOX-P4-250-PPLA-SEZ1` per le ZPL.

## 3. Decisioni prese

| # | Decisione |
|---|---|
| D1 | La stampa parte **sempre dal sito della sezionatrice**, con o senza VPN. Odoo non manda più lavori di stampa oltre la VPN per SEZ1. |
| D2 | Stampa tramite il **CUPS sulla VM 192.168.20.18**, sul sito della sezionatrice (raggiungibile a VPN giù). Ha già le code `Brother_HL-L6450DW_series` e `ARGOX-P4-250-PPLA-SEZ1`, con gli stessi nomi usati da Odoo. |
| D3 | **VPN attiva:** decide Odoo, come oggi, ma restituisce al logger i PDF e le istruzioni di stampa invece di stampare. |
| D4 | **VPN giù:** il logger rifà lo stesso calcolo di Odoo su una **fotografia** scaricata in precedenza e stampa i PDF già pronti. |
| D5 | Fotografia e PDF stanno sulla **share OpenMediaVault** del sito, **mai sul disco del PC**. Si conserva un giorno. |
| D6 | Il bindello può cambiare fino all'ultimo: la fotografia viene **aggiornata di continuo** mentre la VPN funziona. A VPN giù si stampa l'ultima versione scaricata. |
| D7 | Al ritorno della VPN il logger invia il **registro delle stampe prima di qualsiasi nuova stampa**. Odoo segna bindelli e schemi come stampati e segnala i bindelli cambiati nel frattempo. |
| D8 | **Anche le etichette ZPL** escono a VPN giù. |
| D9 | **La stampa manuale è bloccata** (procedura guidata, solo anteprima) per i bindelli presenti nella fotografia attiva del logger. Il gruppo *Superuser labels* può forzarla e la forzatura resta registrata. |
| D10 | Il calcolo dei bindelli è scritto **una sola volta**, come funzione Python senza database, usata sia da Odoo sia dal logger. |

## 4. Architettura

```mermaid
flowchart LR
    subgraph SEDE["Sede — server Odoo"]
        ODOO["Odoo 12<br/>oi_mrp_label + antex_label_offline"]
    end
    subgraph SITO["Sito sezionatrice"]
        SELCO["Sezionatrice Selco<br/>Event.log"]
        PC["PC Windows<br/>Selco Logger"]
        OMV[("Share OpenMediaVault<br/>fotografia, PDF, ZPL, registro")]
        CUPS["VM CUPS<br/>192.168.20.18"]
        BRO["Brother HL-L6450DW<br/>bindelli A4"]
        ARG["Argox P4-250 SEZ1<br/>etichette ZPL"]
    end
    SELCO --> PC
    PC <-- "JSON-RPC (VPN)" --> ODOO
    PC <-- "SMB" --> OMV
    PC -- "IPP" --> CUPS
    CUPS --> BRO
    CUPS --> ARG
```

Solo la freccia PC ↔ Odoo passa dalla VPN. Tutto quello che serve per stampare (fotografia, PDF, CUPS,
stampanti) è sul sito.

### 4.1 Componenti e repository

```
selco_offline/
├── docs/                       questo documento
├── odoo/antex_label_offline/   modulo Odoo (copia; i test girano da addons_antex_skilled)
├── logger/                     evoluzione di loggerselco
└── shared/label_allocation.py  calcolo dei bindelli, senza database
```

`shared/label_allocation.py` è l'unica copia del calcolo. Il modulo Odoo e il logger ne includono una
copia identica. Un test in ciascuno dei due confronta la propria copia con quella di `shared/` e fallisce
se sono diverse.

## 5. Modulo Odoo `antex_label_offline`

Dipende da `oi_mrp_label`, `antex_jit_label`, `mrp_sale_plan`, `base_report_to_printer`.

### 5.1 Istruzioni di stampa separate dalla stampa (in `oi_mrp_label`)

`print_label()` oggi decide copie, cassetti e pagine **e** manda il lavoro a CUPS. Lo dividiamo in due:

- `_prepare_print_jobs()` restituisce l'elenco dei lavori: coda, PDF, opzioni (`copies`, `InputSlot`,
  `page-ranges`, `Duplex`);
- `print_label()` prepara i lavori e li manda a CUPS: **stesso comportamento di oggi** per chi stampa da
  Odoo (altri reparti, procedura guidata).

La modifica va in `oi_mrp_label`, perché copre tutti i casi della tabella 2.2 e non deve esistere in due
copie. Lo stesso per le ZPL in `antex_jit_label` (`_prepare_id_label_zpl()` restituisce il testo,
`print_ID_label()` lo stampa).

Ogni lavoro ha questa forma:

```json
{
  "queue": "Brother_HL-L6450DW_series",
  "document": "label:1234:ab12cd…",
  "format": "application/pdf",
  "options": {"copies": 1, "InputSlot": "TRAY2", "page-ranges": "1-2", "Duplex": "DuplexNoTumble"}
}
```

`document` punta a un file della fotografia (§6), così lo stesso PDF non viaggia due volte.

### 5.2 Calcolo dei bindelli

`print_layout_labels_from_cutting_plan()` usa `label_allocation.allocate()` (§7) invece del ciclo
attuale: stesso risultato, ma lo stesso codice gira anche nel logger.

### 5.3 Metodi chiamati dal logger (JSON-RPC, utente `sezselco`)

| Metodo | Uso |
|---|---|
| `offline_get_snapshot(workcenter_code, known_documents)` | Restituisce la fotografia (§6). `known_documents` sono le impronte già presenti sulla share: Odoo rimanda solo i PDF/ZPL nuovi o cambiati. |
| `offline_confirm_snapshot(snapshot_id)` | Il logger conferma di aver scritto la fotografia sulla share. Da qui in poi è la fotografia **attiva** (serve al blocco D9). |
| `offline_sync_journal(entries)` | Riceve il registro delle stampe fatte dal logger (§8). Idempotente: ogni voce ha un identificativo univoco. |
| `offline_print_layout(barcode)` | Stampa a VPN attiva: decide come oggi, segna stampato e restituisce i lavori (§5.1) invece di stampare. |

### 5.4 Nuovi modelli

- `label.offline.snapshot`: fotografie consegnate al logger (centro di lavoro, data, bindelli inclusi,
  stato *consegnata / attiva / sostituita*).
- `label.offline.journal`: voci di registro ricevute (identificativo, data di stampa sul sito, bindello o
  ZPL, schema, impronta stampata, esito).
- `label.offline.alert`: bindelli da verificare. Un'allerta nasce quando il bindello stampato a VPN giù è
  diverso dalla versione attuale, quando il registro cita un bindello che non esiste più (bindelli
  rigenerati durante il guasto), oppure quando un bindello è stato stampato due volte. Menu
  *Produzione › Bindelli offline*.

### 5.5 Blocco della stampa manuale (D9)

Nella procedura guidata `mrp.production.label.report.confirmation`, la stampa senza anteprima rifiuta i
bindelli presenti nella fotografia attiva del logger. Il messaggio indica che il bindello verrà stampato
dalla sezionatrice. Gli utenti del gruppo `oi_mrp_label.group_superuser_labels` possono forzarla: la
forzatura viene registrata sul bindello (utente e data).

Il blocco vale solo per i bindelli **non ancora stampati**, perché la ristampa di un bindello già stampato
è già limitata all'anteprima oggi.

## 6. Fotografia sulla share

### 6.1 Cosa contiene

Schemi inclusi: schemi SEZ1 (barcode `PE…`), il cui piano di taglio è stato stampato
(`mrp.sale.plan.material.is_printed`), non ancora stampati (`printed_label = False`), creati negli ultimi
**N giorni** (proposta: 7). Per ciascuno:

- barcode, materiale, tipo (supporto/cartella) e righe (riga d'ordine, pezzi, ID PDT);
- per ogni riga d'ordine coinvolta: bindelli del tipo giusto (id, numero, quantità, già stampato) e pezzi
  già tagliati (schemi stampati dello stesso tipo);
- lavori di stampa di ogni bindello non ancora stampato (§5.1);
- per le righe con `zpl_print_label`: testo ZPL dell'ordine di produzione;
- code di stampa da usare, lette dall'utente `sezselco` (`printing_printer_id`,
  `zpl_printing_printer_id`).

L'ID PDT (`pcs_id`) viene dall'ottimizzatore ed è lo stesso per una riga d'ordine in tutti gli schemi della
stessa ottimizzazione. Il PDF di un bindello quindi non dipende da quale schema lo farà uscire: basta un PDF
per bindello.

### 6.2 Aggiornamento senza sovraccaricare il server

Volumi SEZ1 (giugno–agosto 2026, database di test): in media **41 schemi e 85 righe d'ordine al giorno**
(massimo 80 e 167), **2,5 bindelli per riga**, cioè circa 200 PDF al giorno, fino a circa 400.
Rigenerarli tutti ogni 15 minuti con wkhtmltopdf sarebbe troppo pesante.

Per ogni bindello Odoo calcola quindi un'**impronta** dell'HTML QWeb, escludendo la riga di piè di pagina
con operatore e data/ora. Generare l'HTML è molto più veloce del PDF. Il PDF viene rigenerato solo se
l'impronta cambia, e il logger scarica solo i documenti con impronta nuova. Lo stesso vale per le ZPL.

Il piè di pagina del PDF preparato in anticipo riporta la data di generazione, non quella di stampa.

### 6.3 Struttura

```
\\<omv>\<share>\SEZ1\
├── snapshot.json                 fotografia attiva (scrittura su file temporaneo + rinomina)
├── documents\
│   ├── label_1234_ab12cd.pdf     un file per bindello e impronta
│   └── zpl_5678_ef34ab.zpl       un file per ordine di produzione e impronta
└── journal\
    └── 2026-09-30.jsonl          registro delle stampe (una riga JSON per voce)
```

I documenti non più citati dalla fotografia attiva e più vecchi di un giorno vengono cancellati dal logger.

## 7. Il calcolo dei bindelli (`shared/label_allocation.py`)

Funzione pura, senza database:

```python
def allocate(layout, sale_lines):
    """Bindelli da stampare per uno schema.

    layout: {"kind": "support"|"frame", "lines": [{"sale_line": id, "qty": n}, ...]}
    sale_lines: {id: {"cut_before": n,                # pezzi degli schemi già stampati, stesso tipo
                      "labels": [{"id", "sub", "qty", "printed"}, ...]}}
    ritorna: [label_id, ...] nell'ordine di stampa
    """
```

La logica è quella della §2.1 (corretta): per ogni riga, i pezzi tagliati prima (compresi quelli delle righe
precedenti dello stesso schema) più quelli della riga, meno i pezzi dei bindelli già stampati. Si prendono i
bindelli non stampati in ordine di `sub`.

- **Odoo** la chiama con i dati letti dal database.
- **Il logger** la chiama con i dati della fotografia, a cui applica le voci del proprio registro successive
  alla fotografia: bindelli stampati e pezzi degli schemi stampati a VPN giù. La fotografia non viene mai
  modificata: lo stato si ricava sempre da fotografia + registro, e sopravvive al riavvio del PC.

## 8. Il logger

### 8.1 Modifiche

| Modulo | Compito |
|---|---|
| `snapshot.py` | a VPN attiva, ogni *N* minuti (proposta: 15): invia il registro, scarica la fotografia, scrive i documenti nuovi sulla share, conferma la fotografia, pulisce i vecchi documenti |
| `label_allocation.py` | copia di `shared/label_allocation.py` |
| `printing.py` | client IPP verso `http://192.168.20.18:631/printers/<coda>`: invia il documento letto dalla share (in memoria, senza file temporanei) con le opzioni del lavoro |
| `journal.py` | registro sulla share, invio a Odoo, stato locale = fotografia + registro |
| `selco.py` | alla riga `PRODUCED PIECE`, il vecchio `print_layout_labels_from_cutting_plan()` viene sostituito dal flusso della §8.2 |

Le opzioni dei lavori sono le stesse che `lp -o` passerebbe a CUPS (`InputSlot`, `page-ranges`, `Duplex`,
`copies`). Il client IPP va verificato con una stampa di prova da cassetto `TRAY2` prima di tutto il resto.

### 8.2 Flusso al primo pezzo finito

```mermaid
flowchart TD
    A[PRODUCED PIECE del programma X] --> B{Odoo raggiungibile?}
    B -- sì --> C[invia il registro in sospeso]
    C --> D["offline_print_layout(X)"]
    D --> E[stampa i lavori ricevuti via IPP]
    E --> F[scrive nel registro l'esito di ogni lavoro]
    B -- no --> G{schema X nella fotografia?}
    G -- sì --> H["allocate() su fotografia + registro"]
    H --> I[stampa bindelli e ZPL dalla share via IPP]
    I --> J[scrive nel registro: schema X stampato, bindelli, impronte, esito]
    G -- no --> K[mette X in attesa]
    K --> L[al ritorno della VPN: flusso 'sì']
```

Uno schema non presente nella fotografia (piano creato a VPN già giù) si comporta come oggi: esce al
ritorno della VPN.

### 8.3 Ritorno della VPN

```mermaid
sequenceDiagram
    participant PC as Logger
    participant OMV as Share
    participant Odoo as Odoo
    PC->>OMV: legge le voci di registro non ancora inviate
    PC->>Odoo: offline_sync_journal(voci)
    Odoo->>Odoo: segna bindelli (is_printed) e schemi (printed_label)
    Odoo->>Odoo: confronta le impronte stampate con quelle attuali
    Odoo->>Odoo: crea le allerte (bindello cambiato / sparito / doppio)
    Odoo-->>PC: voci accettate
    PC->>OMV: segna le voci come inviate
    PC->>PC: stampa gli schemi rimasti in attesa (flusso online)
    PC->>Odoo: offline_get_snapshot(...)
```

Se una stampa via IPP fallisce, la voce di registro riporta l'errore e il bindello non viene considerato
stampato, né dal logger né da Odoo. Resta disponibile per lo schema successivo, come oggi.

## 9. Casi particolari

| Caso | Comportamento |
|---|---|
| Ordine di lavoro modificato dopo l'ultimo aggiornamento, VPN giù | esce la versione precedente; al ritorno della VPN Odoo crea un'allerta *bindello cambiato* |
| Bindelli rigenerati in Odoo durante il guasto | il registro cita bindelli inesistenti: allerta *bindello sparito* |
| Stampa manuale in Odoo durante il guasto | bloccata (D9); una forzatura da superuser può creare un'allerta *bindello doppio* alla sincronizzazione |
| Share non raggiungibile | a VPN attiva si stampa come in §8.2 senza fotografia; a VPN giù non si stampa (schema in attesa); icona del logger in allarme |
| CUPS 192.168.20.18 non raggiungibile | nessuna stampa; voce di registro con errore; il bindello resta non stampato |
| Stesso programma ripetuto | il logger stampa una volta sola per programma (flag `label_printed` in `activeprogram.json`, come oggi) |
| Schema tagliato anche su SEZ (altro sito) durante il guasto | non visibile al logger; la differenza si recupera allo schema successivo |

## 10. Piano di lavoro

| Fase | Contenuto | Verifica |
|---|---|---|
| F0 | Portare in produzione la correzione di `oi_mrp_label` 12.0.32.0.0 | test del modulo; controllo sulla riga segnalata |
| F1 | `oi_mrp_label` / `antex_jit_label`: istruzioni di stampa separate dalla stampa, `allocate()` condiviso — nessun cambiamento visibile | test: stessi lavori per ogni caso della tabella 2.2 |
| F2 | Modulo `antex_label_offline`: metodi RPC, fotografia con impronte, registro, allerte, blocco della stampa manuale | test su `antex12test` |
| F3 | Logger: stampa IPP verso 192.168.20.18 con `offline_print_layout` (solo VPN attiva) | stampa di prova con `TRAY2`, fronte/retro, copie; confronto con la stampa attuale |
| F4 | Logger: fotografia sulla share, calcolo a VPN giù, registro, sincronizzazione | simulazione di VPN giù (Odoo irraggiungibile) su un lotto di schemi reali |
| F5 | Messa in servizio su SEZ1 | una settimana di confronto tra registro e stato di Odoo |

## 11. Punti aperti

1. Percorso della share OpenMediaVault e utenza con cui il logger la monta.
2. Criterio degli schemi nella fotografia: proposta *piano stampato, schema non stampato, ultimi 7
   giorni*. Nei dati di test ci sono schemi `PE…` mai stampati anche su piani chiusi: vanno esclusi?
3. Intervallo di aggiornamento della fotografia (proposta 15 minuti) e carico sul server all'inizio del
   turno, quando arrivano i piani nuovi.
4. Versione di Python e librerie disponibili sul PC Windows (client IPP).
5. Destinatari delle allerte: solo menu, oppure anche un'attività a un responsabile?
