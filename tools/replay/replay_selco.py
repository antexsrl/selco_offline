"""Replay a Selco event log through loggerselco's Selco.process_buffer with a fake Odoo."""
import sys, types
from datetime import datetime
import os
LOGGERSELCO = os.environ.get("LOGGERSELCO", "/home/odoo-dev/loggerselco")
sys.path.insert(0, LOGGERSELCO)
import pytz
import odooutils
import selco as selco_mod

records = {}   # id -> dict
states = {}
seq = [0]

def nid():
    seq[0] += 1
    return seq[0]

def create_productivity(odoo, values):
    i = nid()
    records[i] = {"id": i, "layout": values["layout"], "action": values["action"],
                  "start": values["date_start"], "end": None, "boards": None,
                  "ctx": CTX[0]}
    return i

def close_productivity(odoo, pid, values):
    r = records.get(pid)
    if r is None:
        raise Exception("not found %s" % pid)
    if r["end"] is not None:
        r.setdefault("reclosed", 0)
        r["reclosed"] += 1
    r["end"] = values["date_end"]
    r["boards"] = sum(values["boards"])
    r["close_ctx"] = CTX[0]
    return False

def add_sez_pack(odoo, pid, qty):
    return nid()

def create_wcstate(odoo, values):
    i = nid(); states[i] = dict(values); return i

def close_wcstate(odoo, event_date, state_id=False, messages=[]):
    return False

odooutils.create_productivity = create_productivity
odooutils.close_productivity = close_productivity
odooutils.add_sez_pack = add_sez_pack
odooutils.create_wcstate = create_wcstate
odooutils.close_wcstate = close_wcstate

CTX = [None]

class Cfg:
    logfile = "sim_error.log"

def run(paths):
    s = selco_mod.Selco(Cfg())
    s.tz = pytz.timezone("Europe/Rome")
    s.workcenter_id = 1
    s.odoo = object()
    selco_mod.ENABLELABELS = False
    s.working_loss_id = 12
    s.block_loss_id = 8
    s.last_productivity_employees_ids = []
    s.last_productivity_id = False
    s.active_programs = selco_mod.OrderedDict()
    s.messages = selco_mod.OrderedDict()
    lines = []
    for p in paths:
        with open(p, encoding="utf-8", errors="ignore") as f:
            lines += [l.rstrip("\r\n") for l in f]
    # feed line by line so that CTX tracks the triggering line
    for l in lines:
        CTX[0] = l
        s.buffer = [l]
        s.backup_buffer = []
        s.process_buffer()
    return s

if __name__ == "__main__":
    s = run(sys.argv[1:])
    import json
    tot = len(records)
    zero = [r for r in records.values() if r["end"] is not None and r["end"] == r["start"]]
    neg = [r for r in records.values() if r["end"] is not None and r["end"] < r["start"]]
    opened = [r for r in records.values() if r["end"] is None]
    print("records", tot, "zero", len(zero), "negative", len(neg), "left open", len(opened))
    from collections import Counter
    def kind(line):
        a = line.split("\t")
        return a[0] + ("/" + a[2][:20] if a[0] in ("Comand", "Session", "State") else "")
    print("zero by closing line:", Counter(kind(r["close_ctx"]) for r in zero).most_common(10))
    print("zero by action:", Counter(r["action"] for r in zero))
    print("neg by closing line:", Counter(kind(r["close_ctx"]) for r in neg).most_common(10))
    json.dump([dict(r, start=str(r["start"]), end=str(r["end"])) for r in records.values()], open("selco_records.json", "w"), indent=0)
