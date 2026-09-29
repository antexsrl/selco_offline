"""Prototype: productivity attributed by output (Boards done) instead of by the FIFO of Start program.

Rules R1-R8 and R10 of docs/progetto.md §10.2 (R9, OSI alarm states, is not simulated).
"""
import re, sys, json
from datetime import datetime, timedelta
MIN_STOP = timedelta(minutes=3)   # R10: shorter stops don't split the working record
START = re.compile(r'Start program;(.*?);(.*?);measure: ((?:\d|x)*) done: (\d{1,5}) to do: (\d{1,5})')

class Engine:
    def __init__(self):
        self.recs = []          # emitted records
        self.mode = "off"       # off | working | block
        self.open = None        # open working record
        self.block = None       # open block record
        self.anchor = None      # start of the working time not yet attributed
        self.done = {}          # program -> cumulative boards
        self.todo = {}
        self.last_started = None
        self.last_board = {}    # program -> time of last board
        self.last_t = None
        self.pending_stop = None  # R10: time of a stop not yet confirmed

    def _rec(self, layout, start, action):
        r = {"layout": layout, "start": start, "end": None, "boards": 0, "action": action}
        self.recs.append(r); return r

    def _close(self, r, end):
        r["end"] = end
        if r["end"] == r["start"] and not r["boards"]:
            self.recs.remove(r)   # nothing happened: never sent to Odoo

    def _start_work(self, t):
        if self.block:
            self._close(self.block, t); self.block = None
        if self.mode != "working":
            self.mode = "working"; self.anchor = t

    def _stop(self, t, block):
        block_start = t
        if self.mode == "working":
            if self.open:
                self._close(self.open, t); self.open = None
            elif self.anchor and t > self.anchor:
                # R4: nothing produced since the (re)start: that time belongs to the stop
                block_start = self.anchor
        self.open = None; self.anchor = None
        if block and not self.block:
            self.block = self._rec("block", block_start, "block")
        self.mode = "block" if block else "off"
        if not block and self.block:
            self._close(self.block, t); self.block = None

    def _request_stop(self, t):
        # also right after power-on (Init Session -> Emergency -> calibration): today that is a block too
        if self.mode in ("working", "off") and not self.pending_stop:
            self.pending_stop = t

    @staticmethod
    def _is_restart(kind, a):
        if kind == "Boards done":
            return True
        return kind == "Comand" and (START.match(a[2]) or a[2] in ("Start worklist", "Restart worklist"))

    def feed(self, line):
        a = line.rstrip("\r\n").split("\t")
        if len(a) < 6: return
        try: t = datetime.strptime(a[5] + " " + a[4], "%d/%m/%Y %H:%M:%S")
        except ValueError: return
        kind = a[0]
        # R10: a stop becomes a block only after MIN_STOP without restart
        if self.pending_stop and t - self.pending_stop >= MIN_STOP:
            self._stop(self.pending_stop, block=True)
            self.pending_stop = None
        if self.pending_stop and self._is_restart(kind, a):
            self.pending_stop = None
        if kind == "Comand":
            c = a[2]
            m = START.match(c)
            if m:
                p = m.group(2)
                self.todo[p] = int(m.group(5)); self.done[p] = int(m.group(4))
                self.last_started = p
                if self.mode != "working": self._start_work(t)
            elif c in ("Start worklist", "Restart worklist"):
                self._start_work(t)
            elif c in ("Stop program", "Stop worklist"):
                self._request_stop(t)
        elif kind == "State" and a[2] == "Emergency" and a[1] != "-1":
            self._request_stop(t)
        elif kind == "Session":
            if a[2] == "End Session":
                self.pending_stop = None
                self._stop(t, block=False)
            else:  # Init Session: a crash leaves things open, close them at the last known event
                if self.mode != "off" and self.last_t:
                    self._stop(self.last_t, block=False)
        elif kind == "Boards done":
            p = a[2].split(";")[0]
            try: n = int(a[1])
            except ValueError: n = 0
            delta = n - self.done.get(p, 0)
            self.done[p] = n
            if self.mode != "working": self._start_work(t)
            if self.open and self.open["layout"] != p:
                prev = self.open
                handover = self.last_board.get(prev["layout"], prev["start"])
                handover = max(handover, prev["start"])
                self._close(prev, handover)
                self.open = self._rec(p, handover, "working")
            elif not self.open:
                self.open = self._rec(p, self.anchor or t, "working")
            self.open["boards"] += max(delta, 0)
            self.open["end"] = None
            self.last_board[p] = t
            if p in self.todo and n >= self.todo[p]:
                self._close(self.open, t); self.open = None; self.anchor = t
        self.last_t = t

if __name__ == "__main__":
    e = Engine()
    for p in sys.argv[1:]:
        for l in open(p, encoding="utf-8", errors="ignore"):
            e.feed(l)
    json.dump([dict(r, start=str(r["start"]), end=str(r["end"])) for r in e.recs], open("engine_records.json", "w"), indent=0)
