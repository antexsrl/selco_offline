"""Queue of the Odoo operations produced by the engine, sent in order when Odoo is reachable.

The queue is part of the logger state: with the VPN down, or after a restart of the PC, nothing is
lost. Local record keys are mapped to the Odoo ids as the records get created.

Odoo methods (antex_mobile_cutting_plan, unchanged): mrp.workcenter.productivity.create_productivity,
add_sez_pack, close_productivity, get_last_sez_productivity; mrp.workcenter.state create/write;
mrp.sale.plan.layout.print_layout_labels_from_cutting_plan.
"""
import logging
import socket
from datetime import datetime, timedelta

import odoorpc
import pytz

_logger = logging.getLogger(__name__)

DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
CONNECT_TIMEOUT = 5       # seconds: fail fast when the VPN is down
RPC_TIMEOUT = 300         # seconds: printing labels renders PDFs on the server
MAX_ATTEMPTS = 3          # an operation refused by Odoo this many times is dropped
IDS_MEMORY = 2000         # Odoo ids kept for the most recent local keys


class OdooUnreachable(Exception):
    pass


class OdooSync:

    def __init__(self, config, state=None, odoo_factory=None):
        self.config = config
        state = state or {}
        self.outbox = state.get('outbox', [])
        self.ids = {str(k): v for k, v in state.get('ids', {}).items()}
        self.odoo = None
        self.odoo_factory = odoo_factory or self._connect
        self.retry_after = None

    def to_dict(self):
        # the ids of records closed long ago are not needed anymore
        if len(self.ids) > IDS_MEMORY:
            recent = sorted(self.ids, key=int)[-IDS_MEMORY:]
            self.ids = {k: self.ids[k] for k in recent}
        return {'outbox': self.outbox, 'ids': self.ids}

    def enqueue(self, ops):
        self.outbox.extend(ops)

    def has_urgent(self):
        return any(op['op'] == 'print_labels' for op in self.outbox)

    def can_try(self, now=None):
        return self.retry_after is None or (now or datetime.now()) >= self.retry_after

    # ------------------------------------------------------------------ connection
    def _connect(self):
        c = self.config
        try:
            socket.create_connection((c.server, c.port), CONNECT_TIMEOUT).close()
        except OSError as e:
            raise OdooUnreachable(e)
        odoo = odoorpc.ODOO(c.server, port=c.port, timeout=RPC_TIMEOUT)
        odoo.login(c.db_name, c.user, c.password)
        return odoo

    def _prepare(self):
        if self.odoo is None:
            self.odoo = self.odoo_factory()
            env = self.odoo.env
            self.tz = pytz.timezone(env.context.get('tz') or 'Europe/Rome')
            self.working_loss_id = env.ref('mrp.block_reason7').id  # fully productive
            self.block_loss_id = env.ref('mrp.block_reason0').id    # availability
            self.workcenter_id = env['mrp.workcenter'].search(
                [('code', '=', self.config.workcenter_code)], limit=1)[0]
        self.employee_ids = None

    def _utc(self, value):
        local = datetime.strptime(value, DATE_FORMAT)
        return self.tz.localize(local).astimezone(pytz.UTC).strftime(DATE_FORMAT)

    def _employees(self):
        # the operators of the last record carry over, as in the old logger
        if self.employee_ids is None:
            last = self.odoo.env['mrp.workcenter.productivity'].get_last_sez_productivity(
                [], self.workcenter_id)
            self.employee_ids = last['last_productivity_employees_ids']
        return self.employee_ids

    # ------------------------------------------------------------------ operations
    def _odoo_id(self, op):
        odoo_id = self.ids.get(str(op['key']))
        if odoo_id is None:
            raise KeyError('record %s never created in Odoo' % op['key'])
        return odoo_id

    def _execute(self, op):
        env = self.odoo.env
        productivity = env['mrp.workcenter.productivity']
        state = env['mrp.workcenter.state']
        kind = op['op']
        if kind == 'create_productivity':
            values = {
                'layout': op['layout'],
                'action': op['action'],
                'date_start': self._utc(op['start']),
                'loss_id': self.working_loss_id if op['action'] == 'working' else self.block_loss_id,
                'workcenter_id': self.workcenter_id,
                'employee_ids': [(0, 0, {'employee_id': e}) for e in self._employees()],
            }
            self.ids[str(op['key'])] = productivity.create_productivity([], values)
        elif kind == 'add_pack':
            productivity.add_sez_pack(self._odoo_id(op), op['qty'])
        elif kind == 'close_productivity':
            productivity.close_productivity(self._odoo_id(op), {
                'date_start': self._utc(op['start']),
                'date_end': self._utc(op['end']),
                'boards': [op['boards']],
            })
        elif kind == 'create_state':
            self.ids[str(op['key'])] = state.create({
                'name': op['name'],
                'zone': op['zone'],
                'state': op['state'],
                'workcenter_id': self.workcenter_id,
                'date_start': self._utc(op['start']),
            })
        elif kind == 'close_state':
            state.browse(self._odoo_id(op)).write({'date_end': self._utc(op['end'])})
        elif kind == 'close_open_states':
            open_ids = state.search([('workcenter_id', '=', self.workcenter_id),
                                     ('date_end', '=', False)])
            if open_ids:
                state.browse(open_ids).write({'date_end': self._utc(op['end'])})
        elif kind == 'print_labels':
            layouts = env['mrp.sale.plan.layout']
            layout_ids = layouts.search([('barcode', '=', op['barcode'])], order='create_date desc', limit=1)
            if layout_ids:
                _logger.info('Program %s: sent command for printing labels', op['barcode'])
                layouts.browse(layout_ids).print_layout_labels_from_cutting_plan()
            else:
                _logger.warning('Program %s: no cutting plan layout with this barcode', op['barcode'])
        else:
            raise ValueError('unknown operation %s' % kind)

    def flush(self, now=None):
        """Send the queued operations in order. Returns how many were sent."""
        now = now or datetime.now()
        if not self.outbox:
            return 0
        sent = 0
        refused = False
        try:
            self._prepare()
            while self.outbox:
                op = self.outbox[0]
                try:
                    self._execute(op)
                except odoorpc.error.RPCError as e:
                    op['attempts'] = op.get('attempts', 0) + 1
                    _logger.error('Odoo refused %s (attempt %s): %s', op, op['attempts'], e)
                    if op['attempts'] < MAX_ATTEMPTS:
                        refused = True
                        break
                except KeyError as e:
                    _logger.error('Dropping %s: %s', op, e)
                self.outbox.pop(0)
                sent += 1
            self.retry_after = now + timedelta(seconds=self.config.interval) if refused else None
        except (OdooUnreachable, OSError, odoorpc.error.Error) as e:
            # VPN down, Odoo restarting or login refused: keep the queue, retry later.
            # A creation whose answer got lost is sent again: it can leave a duplicate record.
            _logger.warning('Odoo not reachable, %s operations queued: %s', len(self.outbox), e)
            self.odoo = None
            self.retry_after = now + timedelta(seconds=self.config.interval)
        return sent
