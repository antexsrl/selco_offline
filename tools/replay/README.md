# Banco di prova: registrazioni di produttività

Rigioca un `Event.log` reale della Selco e confronta le registrazioni di produttività/fermo prodotte da
`selco.py` (loggerselco) con quelle del nuovo logger (`engine.py`, che usa `logger/productivity.py`). Vedi `docs/progetto.md` §10.

```bash
# algoritmo attuale: usa il virtualenv di loggerselco (odoorpc, pytz, ...) e scrive selco_records.json
# (va lanciato in una cartella che contenga Messaggi_OsiAng.txt; crea activeprogram.json e sim_error.log)
LOGGERSELCO=/home/odoo-dev/loggerselco /home/odoo-dev/loggerselco/venv/bin/python replay_selco.py Event.log

# nuovo algoritmo: scrive engine_records.json
python3 engine.py Event.log

python3 compare.py selco_records.json engine_records.json
```

`replay_selco.py` sostituisce le funzioni di `odooutils` con un Odoo finto che registra le chiamate e passa
al logger una riga alla volta. `selco.py` converte le date in UTC, `engine.py` le lascia in ora locale: le
durate sono confrontabili, gli orari no.
