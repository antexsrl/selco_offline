import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))


def line(kind, number='', detail='', time='08:00:00', date='29/05/2026'):
    """A log line as written by OSI: type, number, detail, source, time, date."""
    return '\t'.join([kind, str(number), detail, 'Osi', time, date])


def start_program(program, time, done=0, todo=5):
    detail = ('Start program;%s;%s;measure: 366000x187000x2200 done: %s to do: %s '
              'meters cuted Cross: 0.00 meters cuted Long: 0.00') % (program.rsplit('.', 1)[0], program, done, todo)
    return line('Comand', '', detail, time)


def boards(program, done, time):
    return line('Boards done', done, '%s;Cross. Produced pieces: 12' % program, time)


def piece(program, time):
    return line('PRODUCED PIECE', '', '%s;Part. Dimension: 807.00x407.00  Q:5' % program, time)


def command(text, time):
    return line('Comand', '', text, time)


def emergency(time):
    return line('State', '', 'Emergency', time)


def session(text, time):
    return line('Session', '820744528' if text == 'Init Session' else '', text, time)


def message(code, time):
    return line('Message', code, '', time)
