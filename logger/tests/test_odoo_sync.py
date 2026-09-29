import unittest
from datetime import datetime

import odoorpc

import common  # noqa: F401  (sys.path)
from odoo_sync import OdooSync, OdooUnreachable


class Config:
    server = 'odoo'
    port = 8069
    db_name = 'db'
    user = 'sezselco'
    password = 'x'
    workcenter_code = 'SEZ1'
    interval = 60


class FakeModel:

    def __init__(self, odoo, name):
        self.odoo = odoo
        self.name = name

    def __getattr__(self, method):
        def call(*args, **kwargs):
            self.odoo.calls.append((self.name, method, args))
            if self.odoo.refuse == method:
                raise odoorpc.error.RPCError('refused')
            if method in ('create_productivity', 'create'):
                self.odoo.next_id += 1
                return self.odoo.next_id
            if method == 'search':
                return [7]
            if method == 'get_last_sez_productivity':
                return {'last_productivity_employees_ids': [3]}
            if method == 'browse':
                return self
            return True
        return call


class FakeRef:
    def __init__(self, id):
        self.id = id


class FakeEnv(dict):

    def __init__(self, odoo):
        super().__init__()
        self.odoo = odoo
        self.context = {'tz': 'Europe/Rome'}

    def __getitem__(self, name):
        return FakeModel(self.odoo, name)

    def ref(self, xmlid):
        return FakeRef({'mrp.block_reason7': 12, 'mrp.block_reason0': 8}[xmlid])


class FakeOdoo:

    def __init__(self):
        self.calls = []
        self.next_id = 100
        self.refuse = None
        self.env = FakeEnv(self)


OPS = [
    {'op': 'create_productivity', 'key': 1, 'layout': 'A.001', 'action': 'working', 'start': '2026-05-29 10:00:00'},
    {'op': 'add_pack', 'key': 1, 'qty': 2},
    {'op': 'close_productivity', 'key': 1, 'start': '2026-05-29 10:00:00', 'end': '2026-05-29 10:05:00', 'boards': 2},
    {'op': 'create_productivity', 'key': 2, 'layout': 'block', 'action': 'block', 'start': '2026-05-29 10:05:00'},
    {'op': 'print_labels', 'barcode': 'A.001'},
]


class TestOdooSync(unittest.TestCase):

    def test_operations_become_odoo_calls_in_utc(self):
        odoo = FakeOdoo()
        sync = OdooSync(Config(), odoo_factory=lambda: odoo)
        sync.enqueue([dict(op) for op in OPS])
        self.assertEqual(sync.flush(), 5)
        self.assertFalse(sync.outbox)
        create = [c for c in odoo.calls if c[1] == 'create_productivity']
        self.assertEqual(create[0][2][1], {
            'layout': 'A.001', 'action': 'working', 'date_start': '2026-05-29 08:00:00', 'loss_id': 12,
            'workcenter_id': 7, 'employee_ids': [(0, 0, {'employee_id': 3})],
        })
        self.assertEqual(create[1][2][1]['loss_id'], 8)
        self.assertIn(('mrp.workcenter.productivity', 'add_sez_pack', (101, 2)), odoo.calls)
        close = [c for c in odoo.calls if c[1] == 'close_productivity'][0]
        self.assertEqual(close[2], (101, {'date_start': '2026-05-29 08:00:00',
                                          'date_end': '2026-05-29 08:05:00', 'boards': [2]}))
        self.assertIn(('mrp.sale.plan.layout', 'print_layout_labels_from_cutting_plan', ()), odoo.calls)

    def test_odoo_unreachable_keeps_the_queue(self):
        def unreachable():
            raise OdooUnreachable('VPN down')
        sync = OdooSync(Config(), odoo_factory=unreachable)
        sync.enqueue([dict(op) for op in OPS])
        now = datetime(2026, 5, 29, 10, 0, 0)
        with self.assertLogs('odoo_sync', 'WARNING'):
            self.assertEqual(sync.flush(now), 0)
        self.assertEqual(len(sync.outbox), 5)
        self.assertFalse(sync.can_try(datetime(2026, 5, 29, 10, 0, 30)))
        self.assertTrue(sync.can_try(datetime(2026, 5, 29, 10, 1, 0)))

    def test_queue_and_ids_survive_a_restart(self):
        odoo = FakeOdoo()
        sync = OdooSync(Config(), odoo_factory=lambda: odoo)
        sync.enqueue([dict(op) for op in OPS[:2]])
        sync.flush()
        saved = sync.to_dict()
        resumed = OdooSync(Config(), saved, odoo_factory=lambda: odoo)
        resumed.enqueue([dict(OPS[2])])
        resumed.flush()
        self.assertEqual([c for c in odoo.calls if c[1] == 'close_productivity'][0][2][0], 101)

    def test_refused_operation_is_retried_then_dropped(self):
        odoo = FakeOdoo()
        odoo.refuse = 'add_sez_pack'
        sync = OdooSync(Config(), odoo_factory=lambda: odoo)
        sync.enqueue([dict(op) for op in OPS[:3]])
        with self.assertLogs('odoo_sync', 'ERROR'):
            self.assertEqual(sync.flush(), 1)          # created, the pack is refused
            self.assertEqual(len(sync.outbox), 2)
            sync.flush()
            sync.flush()                               # third refusal: dropped, the rest goes on
        self.assertFalse(sync.outbox)


if __name__ == '__main__':
    unittest.main()
