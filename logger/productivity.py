"""Productivity and block records of the saw, rules R1-R10 of docs/progetto.md §10.2.

The engine is fed with the events of the log and produces operations for Odoo (see odoo_sync.py).
It has no Odoo access, so the same code runs live and on a replayed log.

R1  a working record opens at the first board of a program, from the end of the previous work
R2  boards of another program: the open record closes at its own last board, the new one starts there
R3  the record closes on the board that completes the program (done >= to do)
R4  a confirmed stop always opens a block (even with nothing open, even right after power-on);
    with no board since the restart, the block starts at the restart (interrupted program)
R5  start worklist / restart worklist / start program / a board close the block or cancel the stop
R6  End Session closes everything without a block; an Init Session with things still open (crash)
    closes them at the last event read
R7  a record with no duration and no board is never sent
R8  the board counter follows the "done:" of every Start program
R9  an OSI alarm becomes a workcenter state only when it lasts at least its max_time
R10 a stop becomes a block only without restart within MIN_STOP; shorter stops stay work
"""
from collections import OrderedDict
from datetime import datetime, timedelta

MIN_STOP = timedelta(minutes=3)
# the log lines can reach the file a few seconds late: wall clock checks keep a margin
TICK_MARGIN = timedelta(seconds=10)
LABELS_MEMORY = 500

MSG_TO_MONITOR = OrderedDict([
    ('32', {'state': 'idle', 'name': 'Attesa caricamento in carico', 'zone': 'load', 'max_time': 30}),
    # usually together with alarm 58, so 58 is ignored
    ('39', {'state': 'idle', 'name': 'Attesa start ciclo in carico', 'zone': 'load', 'max_time': 30}),
    ('53', {'state': 'idle', 'name': 'Attesa caricamento in carico', 'zone': 'load', 'max_time': 30}),
    ('45', {'state': 'idle', 'name': 'Attesa scarico martire', 'zone': 'load', 'max_time': 30}),
    ('1055', {'state': 'idle', 'name': 'Hold spintore', 'zone': 'trasv', 'max_time': 30}),
    ('1083', {'state': 'idle', 'name': 'Allarme lama soglia 4 trasv.', 'zone': 'motor1', 'max_time': 0}),
    ('1078', {'state': 'idle', 'name': 'Allarme lama soglia 4 long.', 'zone': 'motor2', 'max_time': 0}),
    ('1408', {'state': 'idle', 'name': 'Attesa rimozione rifili/finiti', 'zone': 'trasv', 'max_time': 30}),
    ('1477', {'state': 'idle', 'name': 'Attesa rimozione rifili/finiti', 'zone': 'trasv', 'max_time': 30}),
    ('1822', {'state': 'idle', 'name': 'Attesa rimozione rifili/finiti', 'zone': 'trasv', 'max_time': 30}),
])

DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


def _dt(value):
    return datetime.strptime(value, DATE_FORMAT) if value else None


def _str(value):
    return value.strftime(DATE_FORMAT) if value else None


class ProductivityEngine:

    def __init__(self, min_stop=MIN_STOP, monitored=MSG_TO_MONITOR):
        self.min_stop = min_stop
        self.monitored = monitored
        self.ops = []
        self.seq = 0
        self.mode = 'off'           # off | working | block
        self.open = None            # working record: key, program, start, boards
        self.block = None           # block record: key, start
        self.anchor = None          # start of the working time not attributed yet
        self.pending_stop = None    # R10: stop not confirmed yet
        self.done = {}              # program -> boards done (cumulative)
        self.todo = {}
        self.last_board = {}        # program -> time of its last board
        self.last_t = None
        self.labels_requested = []  # programs whose labels were already asked for
        self.alarms = {}            # code -> start, key (key set once the state exists)

    # ------------------------------------------------------------------ persistence
    def to_dict(self):
        rec = lambda r: r and dict(r, start=_str(r['start']))
        return {
            'seq': self.seq,
            'mode': self.mode,
            'open': rec(self.open),
            'block': rec(self.block),
            'anchor': _str(self.anchor),
            'pending_stop': _str(self.pending_stop),
            'done': self.done,
            'todo': self.todo,
            'last_board': {p: _str(t) for p, t in self.last_board.items()},
            'last_t': _str(self.last_t),
            'labels_requested': self.labels_requested,
            'alarms': {c: dict(a, start=_str(a['start'])) for c, a in self.alarms.items()},
            'ops': self.ops,
        }

    @classmethod
    def from_dict(cls, data, **kwargs):
        engine = cls(**kwargs)
        if not data:
            return engine
        rec = lambda r: r and dict(r, start=_dt(r['start']))
        engine.seq = data['seq']
        engine.mode = data['mode']
        engine.open = rec(data['open'])
        engine.block = rec(data['block'])
        engine.anchor = _dt(data['anchor'])
        engine.pending_stop = _dt(data['pending_stop'])
        engine.done = data['done']
        engine.todo = data['todo']
        engine.last_board = {p: _dt(t) for p, t in data['last_board'].items()}
        engine.last_t = _dt(data['last_t'])
        engine.labels_requested = data['labels_requested']
        engine.alarms = {c: dict(a, start=_dt(a['start'])) for c, a in data['alarms'].items()}
        engine.ops = data.get('ops', [])
        return engine

    def drain_ops(self):
        ops, self.ops = self.ops, []
        return ops

    # ------------------------------------------------------------------ operations
    def _key(self):
        self.seq += 1
        return self.seq

    def _op(self, op, **values):
        values['op'] = op
        self.ops.append(values)

    def _open_working(self, program, start):
        self.open = {'key': self._key(), 'program': program, 'start': start, 'boards': 0}
        self._op('create_productivity', key=self.open['key'], layout=program, action='working',
                 start=_str(start))

    def _close_working(self, end):
        r, self.open = self.open, None
        self._op('close_productivity', key=r['key'], start=_str(r['start']), end=_str(end),
                 boards=r['boards'])

    def _open_block(self, start):
        self.block = {'key': self._key(), 'start': start}
        self._op('create_productivity', key=self.block['key'], layout='block', action='block',
                 start=_str(start))

    def _close_block(self, end):
        r, self.block = self.block, None
        self._op('close_productivity', key=r['key'], start=_str(r['start']), end=_str(end), boards=0)

    # ------------------------------------------------------------------ state changes
    def _start_work(self, t):
        if self.block:
            self._close_block(t)
        if self.mode != 'working':
            self.mode = 'working'
            self.anchor = t

    def _stop(self, t, block):
        block_start = t
        if self.mode == 'working':
            if self.open:
                self._close_working(t)
            elif self.anchor and t > self.anchor:
                # R4: nothing produced since the (re)start, that time belongs to the stop
                block_start = self.anchor
        self.anchor = None
        if block:
            if not self.block:
                self._open_block(block_start)
            self.mode = 'block'
        else:
            if self.block:
                self._close_block(t)
            self.mode = 'off'

    def _confirm_pending_stop(self, now):
        if self.pending_stop and now - self.pending_stop >= self.min_stop:
            stop, self.pending_stop = self.pending_stop, None
            self._stop(stop, block=True)

    # ------------------------------------------------------------------ alarms (R9)
    def _create_state(self, code, alarm):
        alarm['key'] = self._key()
        info = self.monitored[code]
        self._op('create_state', key=alarm['key'], name=info['name'], zone=info['zone'],
                 state=info['state'], start=_str(alarm['start']))

    def _alarms_tick(self, now):
        for code, alarm in self.alarms.items():
            max_time = timedelta(seconds=self.monitored[code]['max_time'])
            if not alarm['key'] and now - alarm['start'] >= max_time:
                self._create_state(code, alarm)

    def _alarm(self, event):
        if event.code not in self.monitored:
            return
        if not event.cleared:
            if event.code not in self.alarms:
                self.alarms[event.code] = {'start': event.t, 'key': None}
                self._alarms_tick(event.t)
            return
        alarm = self.alarms.pop(event.code, None)
        if not alarm:
            return
        if not alarm['key']:
            max_time = timedelta(seconds=self.monitored[event.code]['max_time'])
            if event.t - alarm['start'] < max_time:
                return
            self._create_state(event.code, alarm)
        self._op('close_state', key=alarm['key'], end=_str(event.t))

    def _close_alarms(self, t):
        for alarm in self.alarms.values():
            if alarm['key']:
                self._op('close_state', key=alarm['key'], end=_str(t))
        self.alarms = {}
        # states left open in Odoo by a crash of the logger
        self._op('close_open_states', end=_str(t))

    # ------------------------------------------------------------------ input
    def tick(self, now):
        """Time passing without new lines (live mode): confirm stops and alarms."""
        now = now - TICK_MARGIN
        self._confirm_pending_stop(now)
        self._alarms_tick(now)

    def feed(self, event):
        t = event.t
        self._confirm_pending_stop(t)
        self._alarms_tick(t)
        if self.pending_stop and event.kind in ('start_program', 'start_worklist', 'boards_done'):
            self.pending_stop = None
        handler = getattr(self, '_on_' + event.kind, None)
        if handler:
            handler(event)
        self.last_t = t

    def _on_start_program(self, event):
        self.todo[event.program] = event.todo
        self.done[event.program] = event.done   # R8
        if self.mode != 'working':
            self._start_work(event.t)

    def _on_start_worklist(self, event):
        self._start_work(event.t)

    def _on_stop(self, event):
        # also right after power-on (Init Session -> Emergency -> calibration)
        if self.mode in ('working', 'off') and not self.pending_stop:
            self.pending_stop = event.t

    def _on_end_session(self, event):
        self.pending_stop = None
        self._stop(event.t, block=False)
        self._close_alarms(event.t)

    def _on_init_session(self, event):
        self.pending_stop = None
        if self.mode != 'off' and self.last_t:
            self._stop(self.last_t, block=False)
        self._close_alarms(self.last_t or event.t)

    def _on_boards_done(self, event):
        p, t = event.program, event.t
        delta = event.done - self.done.get(p, 0)
        self.done[p] = event.done
        if self.mode != 'working':
            self._start_work(t)
        if self.open and self.open['program'] != p:
            prev = self.open
            handover = max(self.last_board.get(prev['program'], prev['start']), prev['start'])
            self._close_working(handover)
            self._open_working(p, handover)
        elif not self.open:
            self._open_working(p, self.anchor or t)
        if delta > 0:
            self.open['boards'] += delta
            self._op('add_pack', key=self.open['key'], qty=delta)
        self.last_board[p] = t
        if p in self.todo and event.done >= self.todo[p]:
            self._close_working(t)
            self.anchor = t

    def _on_produced_piece(self, event):
        # labels are asked once per program, at its first piece
        if event.program in self.labels_requested:
            return
        self.labels_requested.append(event.program)
        del self.labels_requested[:-LABELS_MEMORY]
        self._op('print_labels', barcode=event.program)

    def _on_message(self, event):
        self._alarm(event)
