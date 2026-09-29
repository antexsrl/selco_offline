"""Parsing of the Selco Event.log lines.

A line is tab separated: type, number, detail, source, time, date.
Example: ``Boards done\t5\tPE2600995_4_01.001;Cross. Produced pieces: 84\tOsi\t07:50:37\t29/05/2026``
"""
import re
from collections import namedtuple
from datetime import datetime

START_PROGRAM = re.compile(
    r'Start program;(.*?);(.*?);measure: ((?:\d|x)*) done: (\d{1,5}) to do: (\d{1,5})'
)

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
