"""Parsing of the Selco Event.log lines.

A line is tab separated: type, number, detail, source, time, date.
Example: ``Boards done\t5\tPE2600995_4_01.001;Cross. Produced pieces: 84\tOsi\t07:50:37\t29/05/2026``
"""
import logging
import re
from collections import namedtuple
from datetime import datetime

_logger = logging.getLogger(__name__)

START_PROGRAM = re.compile(
    r'Start program;(.*?);(.*?);measure: ((?:\d|x)*) done: (\d{1,5}) to do: (\d{1,5})'
)
# MQTT messages: the expressions of event_new_copy_v2.py
MQTT_START_PROGRAM = re.compile(
    r'Start program;(.*?);(.*?);measure: ((?:\d|x)*) done: (\d{1,5}) to do: (\d{1,5}) '
    r'meters cuted Cross: (\d{1,9}\.?\d{0,2}) meters cuted Long: (\d{1,9}\.?\d{0,2})'
)
MQTT_PRODUCED_PIECE = re.compile(r'Part\. Dimension: (\d+\.\d+)x(\d+\.\d+)\s+Q:(\d+)')

START_WORKLIST = ('Start worklist', 'Restart worklist')
STOP_COMMANDS = ('Stop program', 'Stop worklist')

# kind: start_program | start_worklist | stop | end_session | init_session
#       | boards_done | produced_piece | message
Event = namedtuple('Event', 'kind t program done todo code cleared line')


def _event(kind, t, line, program=None, done=None, todo=None, code=None, cleared=False):
    return Event(kind, t, program, done, todo, code, cleared, line)


def parse_time(line_array):
    try:
        return datetime.strptime(line_array[5] + ' ' + line_array[4], '%d/%m/%Y %H:%M:%S')
    except (IndexError, ValueError):
        return None


def parse_line(line):
    """Return the Event of a log line, or None when the line is not relevant or malformed."""
    line = line.rstrip('\r\n')
    a = line.split('\t')
    if len(a) < 6:
        return None
    t = parse_time(a)
    if t is None:
        return None
    kind = a[0]

    if kind == 'Comand':
        command = a[2]
        m = START_PROGRAM.match(command)
        if m:
            return _event('start_program', t, line, program=m.group(2),
                          done=int(m.group(4)), todo=int(m.group(5)))
        if command in START_WORKLIST:
            return _event('start_worklist', t, line)
        if command in STOP_COMMANDS:
            return _event('stop', t, line)
        return None

    if kind == 'State':
        if a[2] == 'Emergency' and a[1] != '-1':
            return _event('stop', t, line)
        return None

    if kind == 'Session':
        if a[2] == 'End Session':
            return _event('end_session', t, line)
        return _event('init_session', t, line)

    if kind == 'Boards done':
        try:
            n = int(a[1])  # cumulative for the program
        except ValueError:
            n = 0
        return _event('boards_done', t, line, program=a[2].split(';')[0], done=n)

    if kind == 'PRODUCED PIECE':
        program = a[2].split(';')[0]
        if not program:
            return None
        return _event('produced_piece', t, line, program=program)

    if kind == 'Message':
        code = a[1]
        cleared = code.startswith('-')
        return _event('message', t, line, code=code.lstrip('-'), cleared=cleared)

    return None


def mqtt_event(line):
    """The MQTT message of a log line, as ``format_event()`` of event_new_copy_v2.py, or None.

    Returns (time of the line, message dict). The message has the same keys and types as the
    script, so the consumers on the broker don't change.
    """
    line = line.strip()
    if not line:
        return None
    a = line.split('\t')
    if len(a) < 3:
        return None
    t = parse_time(a)
    kind = a[0]

    if kind == 'PRODUCED PIECE':
        # PRODUCED PIECE\t\tPE2501622_2_31.018;Part. Dimension: 1002.00x365.00  Q:6\tOsi\t13:23:28\t18/09/2025
        if ';' not in a[2]:
            _logger.warning('PRODUCED PIECE malformed (no ;): %s', a[2])
            return None
        program_name, part_desc = a[2].split(';', 1)
        m = MQTT_PRODUCED_PIECE.match(part_desc)
        if not m:
            _logger.warning('PRODUCED PIECE not recognized: "%s"', part_desc)
            return None
        if '.' not in program_name:
            _logger.warning('Program name without pattern: %s', program_name)
            return None
        cutlist_name, pattern = program_name.rsplit('.', 1)
        return t, {
            'event_type': 'produced_piece',
            'cutlist_name': cutlist_name,
            'pattern_nr': pattern,
            'height': m.group(1),
            'length': m.group(2),
            'quantity': m.group(3),
        }

    if kind == 'Comand' and a[2].startswith('Start program'):
        command = a[2]
        if command == 'Start program':   # empty program
            return None
        m = MQTT_START_PROGRAM.match(command)
        if not m:
            _logger.warning('Start command not recognized: "%s"', command)
            return None
        return t, {
            'event_type': 'start_program',
            'list_name': m.group(1),
            'program_name': m.group(2),
            'measure': m.group(3),
            'boards_done': int(m.group(4)),
            'boards_todo': int(m.group(5)),
            'cut_cross': m.group(6),
            'cut_long': m.group(7),
        }

    if kind == 'Boards done':
        try:
            return t, {
                'event_type': 'boards_done',
                'program_name': a[2].split(';')[0],
                'boards_done': int(a[1]),
            }
        except ValueError as e:
            _logger.error('Parsing Boards done: %s', e)
            return None

    return None
