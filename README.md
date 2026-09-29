# selco_offline

Stampa dei bindelli di produzione della sezionatrice Selco (SEZ1) anche quando la VPN verso Odoo non è
disponibile.

- Documento di progetto: [docs/progetto.md](docs/progetto.md)
- Logger attuale: [antexsrl/loggerselco](https://github.com/antexsrl/loggerselco)

## Struttura

| Cartella | Contenuto |
|---|---|
| `docs/` | documentazione di progetto |
| `odoo/antex_label_offline/` | modulo Odoo 12 (copia; i test girano da `addons_antex_skilled`) |
| `logger/` | evoluzione di Selco Logger (PC Windows della sezionatrice) |
| `shared/` | calcolo dei bindelli senza database, usato da Odoo e dal logger |
