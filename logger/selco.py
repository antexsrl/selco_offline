"""Selco saw logger: reads Event.log, builds productivity/block records and label requests, sends them to Odoo.

poll()       every few seconds: new log lines -> engine -> Odoo operation queue (no network)
sync_odoo()  sends the queue when Odoo is reachable; label requests trigger it at once

Everything needed to resume (log position, engine state, queue) is saved in STATE_FILE after each
step, written to a temporary file and renamed so a crash never leaves it half written.
"""
import json
import logging
import os
from datetime import datetime

from eventlog import EventLogReader
from events import parse_line
from odoo_sync import OdooSync
from productivity import ProductivityEngine

STATE_FILE = 'state.json'
STATE_VERSION = 1

_logger = logging.getLogger(__name__)


def load_state(path=STATE_FILE):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            state = json.load(f)
    except (OSError, ValueError) as e:
        _logger.error('State file %s not readable, starting from the end of the log: %s', path, e)
        return {}
    if state.get('version') != STATE_VERSION:
        _logger.error('State file %s has version %s, expected %s: ignored',
                      path, state.get('version'), STATE_VERSION)
        return {}
    return state


def save_state(state, path=STATE_FILE):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f)
    os.replace(tmp, path)


class Selco:

    def __init__(self, config, state_path=STATE_FILE, odoo_factory=None):
        self.config = config
        self.state_path = state_path
        logging.basicConfig(filename=config.logfile, level=logging.INFO,
                            format='%(asctime)s;%(levelname)s;%(name)s;%(message)s')
        state = load_state(state_path)
        self.reader = EventLogReader(config.file, config.filebkp, state.get('reader'))
        self.engine = ProductivityEngine.from_dict(state.get('engine'))
        self.sync = OdooSync(config, state.get('sync'), odoo_factory=odoo_factory)

    def save(self):
        save_state({
            'version': STATE_VERSION,
            'reader': self.reader.to_dict(),
            'engine': self.engine.to_dict(),
            'sync': self.sync.to_dict(),
        }, self.state_path)

    def poll(self, now=None):
        """Read the new lines of the log. Returns the number of lines read."""
        lines = self.reader.read()
        for line in lines:
            event = parse_line(line)
            if event:
                self.engine.feed(event)
        self.engine.tick(now or datetime.now())
        self.sync.enqueue(self.engine.drain_ops())
        self.save()
        return len(lines)

    def sync_odoo(self, now=None):
        """Send the queued operations to Odoo, unless a recent attempt failed."""
        if not self.sync.can_try(now):
            return 0
        sent = self.sync.flush(now)
        self.save()
        return sent

    def update(self, now=None):
        try:
            self.poll(now)
            if self.sync.has_urgent():
                self.sync_odoo(now)
        except Exception:
            _logger.exception('Update failed')
