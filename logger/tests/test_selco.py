"""End to end: Event.log growing, Odoo unreachable for a while, logger restarted in the middle."""
import os
import shutil
import tempfile
import unittest

from test_odoo_sync import Config as SyncConfig, FakeOdoo
from test_productivity import run
from test_replay import LOGS

from events import parse_line
from odoo_sync import OdooUnreachable
from selco import Selco

CHUNK = 200


class Config(SyncConfig):
    pass


class RecordingOdoo(FakeOdoo):
    """Keeps the productivity records as Odoo would store them (local times back from UTC)."""

    def records(self):
        recs, next_id = {}, 100
        for model, method, args in self.calls:
            if method in ('create_productivity', 'create'):   # the same id sequence as FakeModel
                next_id += 1
            if method == 'create_productivity':
                recs[next_id] = {'layout': args[1]['layout'], 'start': args[1]['date_start'],
                                 'end': None, 'boards': 0}
            elif method == 'close_productivity':
                recs[args[0]].update(end=args[1]['date_end'], boards=args[1]['boards'][0])
        return list(recs.values())

    def labels(self):
        return [c for c in self.calls if c[1] == 'print_layout_labels_from_cutting_plan']


@unittest.skipUnless(os.path.isdir(LOGS), 'real logs not available')
class TestSelco(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.config = Config()
        self.config.file = os.path.join(self.dir, 'Event.log')
        self.config.filebkp = os.path.join(self.dir, 'EvtBack.log')
        self.config.logfile = os.path.join(self.dir, 'Error.log')
        self.state = os.path.join(self.dir, 'state.json')
        with open(os.path.join(LOGS, 'Event.log'), 'rb') as f:
            self.lines = f.read().split(b'\r\n')[:6000]

    def append(self, lines):
        with open(self.config.file, 'ab') as f:
            f.write(b''.join(l + b'\r\n' for l in lines))

    def last_time(self, lines):
        for l in reversed(lines):
            event = parse_line(l.decode('utf-8', 'replace'))
            if event:
                return event.t

    def test_log_growing_with_odoo_down_and_a_restart(self):
        odoo = RecordingOdoo()
        vpn = {'up': True}

        def factory():
            if not vpn['up']:
                raise OdooUnreachable('VPN down')
            return odoo

        self.append([])
        selco = Selco(self.config, self.state, odoo_factory=factory)
        selco.poll()   # first run: takes the position at the end of the (empty) log
        chunks = [self.lines[i:i + CHUNK] for i in range(0, len(self.lines), CHUNK)]
        for n, chunk in enumerate(chunks):
            vpn['up'] = not (10 <= n < 20)
            if n == 15:
                selco = Selco(self.config, self.state, odoo_factory=factory)   # PC restarted
            self.append(chunk)
            now = self.last_time(chunk)
            selco.poll(now)
            selco.sync.retry_after = None
            selco.sync_odoo(now)
        vpn['up'] = True
        selco.sync_odoo()
        self.assertFalse(selco.sync.outbox)

        direct = run(l.decode('utf-8', 'replace') for l in self.lines)
        # the live run confirms the last stops by the clock of each chunk: compare the closed records
        expected = []
        opened = {}
        for op in direct.drain_ops():
            if op['op'] == 'create_productivity':
                opened[op['key']] = op
            elif op['op'] == 'close_productivity':
                expected.append((opened[op['key']]['layout'], op['boards']))
        got = [(r['layout'], r['boards']) for r in odoo.records() if r['end']]
        self.assertEqual(got[:len(expected) - 2], expected[:len(expected) - 2])
        self.assertTrue(odoo.labels())


if __name__ == '__main__':
    unittest.main()
