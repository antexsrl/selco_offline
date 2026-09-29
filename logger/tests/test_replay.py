"""The engine on the real logs of the saw (docs/progetto.md §10.3). Skipped when the logs are missing.

SELCO_LOGS points to the folder with EventOsi.log, EvtBack.log, Event.log
(default: /home/odoo-dev/loggerselco/log).
"""
import os
import unittest
from datetime import datetime

from test_productivity import run

LOGS = os.environ.get('SELCO_LOGS', '/home/odoo-dev/loggerselco/log')
# records per log with the rules R1-R10 (docs/progetto.md §10.3)
EXPECTED = {'EventOsi.log': 321, 'EvtBack.log': 805, 'Event.log': 357}


def parse(value):
    return datetime.strptime(value, '%Y-%m-%d %H:%M:%S')


@unittest.skipUnless(os.path.isdir(LOGS), 'real logs not available')
class TestReplay(unittest.TestCase):

    def test_real_logs(self):
        for name, expected in EXPECTED.items():
            with self.subTest(log=name):
                with open(os.path.join(LOGS, name), encoding='utf-8', errors='replace') as f:
                    engine = run(f)
                recs = {}
                for op in engine.drain_ops():
                    if op['op'] == 'create_productivity':
                        recs[op['key']] = dict(op, end=None, boards=0)
                    elif op['op'] == 'close_productivity':
                        recs[op['key']].update(end=op['end'], boards=op['boards'])
                self.assertEqual(len(recs), expected)
                closed = [r for r in recs.values() if r['end']]
                for r in closed:
                    self.assertLessEqual(parse(r['start']), parse(r['end']), r)
                    if r['start'] == r['end']:
                        self.assertTrue(r['boards'], 'zero-duration record without boards: %s' % r)


if __name__ == '__main__':
    unittest.main()
