import json, sys
from datetime import datetime
P = lambda s: datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
def stats(recs, utc):
    w = [r for r in recs if r["action"] == "working" and r["end"] not in (None, "None")]
    b = [r for r in recs if r["action"] == "block" and r["end"] not in (None, "None")]
    mins = lambda rs: sum((P(r["end"]) - P(r["start"])).total_seconds() for r in rs) / 60
    return {"working": len(w), "block": len(b), "zero": sum(1 for r in w + b if r["end"] == r["start"]),
            "neg": sum(1 for r in w + b if P(r["end"]) < P(r["start"])),
            "work_min": round(mins(w)), "block_min": round(mins(b)),
            "boards": sum(r["boards"] or 0 for r in w),
            "empty_work_min": round(mins([r for r in w if not r["boards"]]))}
old = json.load(open(sys.argv[1])); new = json.load(open(sys.argv[2]))
print("  old:", stats(old, True)); print("  new:", stats(new, False))
