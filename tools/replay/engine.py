"""Replay a Selco event log through the new logger engine (logger/productivity.py).

Turns the Odoo operations into records, in the same shape as replay_selco.py, for compare.py.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'logger'))

from events import parse_line  # noqa: E402
from productivity import ProductivityEngine  # noqa: E402


def replay(paths):
    engine = ProductivityEngine()
    for path in paths:
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                event = parse_line(line)
                if event:
                    engine.feed(event)
    records, states, labels = {}, {}, []
    for op in engine.drain_ops():
        kind = op['op']
        if kind == 'create_productivity':
            records[op['key']] = {'layout': op['layout'], 'action': op['action'],
                                  'start': op['start'], 'end': None, 'boards': 0}
        elif kind == 'close_productivity':
            records[op['key']].update(end=op['end'], boards=op['boards'])
        elif kind == 'create_state':
            states[op['key']] = {'name': op['name'], 'start': op['start'], 'end': None}
        elif kind == 'close_state':
            states[op['key']]['end'] = op['end']
        elif kind == 'print_labels':
            labels.append(op['barcode'])
    return list(records.values()), list(states.values()), labels


if __name__ == '__main__':
    records, states, labels = replay(sys.argv[1:])
    with open('engine_records.json', 'w') as f:
        json.dump(records, f, indent=0)
    print('records', len(records), 'states', len(states), 'label requests', len(labels))
