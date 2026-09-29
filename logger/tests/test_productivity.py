import json
import unittest
from datetime import datetime

from common import boards, command, emergency, message, piece, session, start_program

from events import parse_line
from productivity import ProductivityEngine


def run(lines, engine=None):
    engine = engine or ProductivityEngine()
    for l in lines:
        event = parse_line(l)
        if event:
            engine.feed(event)
    return engine


def records(ops):
    """Productivity records rebuilt from the operations: key -> dict."""
    recs = {}
    for op in ops:
        if op['op'] == 'create_productivity':
            recs[op['key']] = {'layout': op['layout'], 'action': op['action'], 'start': op['start'][11:],
                               'end': None, 'boards': 0}
        elif op['op'] == 'close_productivity':
            recs[op['key']].update(end=op['end'][11:], boards=op['boards'])
    return list(recs.values())


def rec(layout, start, end, boards=0, action='working'):
    return {'layout': layout, 'action': action, 'start': start, 'end': end, 'boards': boards}


def block(start, end):
    return rec('block', start, end, action='block')


class TestProductivityEngine(unittest.TestCase):

    def test_queued_programs_get_no_record(self):
        # regression: every program loaded in the worklist got a zero-duration record at the emergency
        e = run([
            start_program('P.010', '06:20:00'),
            command('Start worklist', '06:20:00'),
            start_program('P.011', '06:23:00'),
            boards('P.010', 2, '06:24:03'),
            emergency('06:26:04'),
            command('Start worklist', '06:39:44'),
        ])
        self.assertEqual(records(e.drain_ops()), [
            rec('P.010', '06:20:00', '06:26:04', 2),
            block('06:26:04', '06:39:44'),
        ])

    def test_boards_of_the_next_program_hand_over_at_the_last_board(self):
        e = run([
            start_program('A.001', '10:00:00'),
            command('Start worklist', '10:00:00'),
            boards('A.001', 1, '10:03:00'),
            start_program('B.001', '10:04:00'),
            boards('B.001', 1, '10:09:00'),
            boards('B.001', 5, '10:12:00'),
        ])
        self.assertEqual(records(e.drain_ops()), [
            rec('A.001', '10:00:00', '10:03:00', 1),
            rec('B.001', '10:03:00', '10:12:00', 5),
        ])

    def test_program_interrupted_and_replaced_gives_its_time_to_the_next(self):
        # 29/05/2026: PE2601001 started and stopped after 25 s, PE2600995 run instead.
        # regression: the interrupted program got 12 min 34 s, the real one a zero-duration record
        e = run([
            start_program('PE2601001_2_0.001', '07:37:07', todo=6),
            command('Stop worklist', '07:37:32'),
            start_program('PE2600995_4_01.001', '07:38:03', todo=5),
            command('Start worklist', '07:38:03'),
            boards('PE2600995_4_01.001', 5, '07:50:37'),
        ])
        self.assertEqual(records(e.drain_ops()), [
            rec('PE2600995_4_01.001', '07:37:07', '07:50:37', 5),
        ])

    def test_long_stop_of_an_interrupted_program_is_all_block(self):
        e = run([
            start_program('A.001', '07:37:07'),
            command('Stop worklist', '07:37:32'),
            start_program('B.001', '07:45:00'),
            boards('B.001', 5, '07:50:00'),
        ])
        self.assertEqual(records(e.drain_ops()), [
            block('07:37:07', '07:45:00'),
            rec('B.001', '07:45:00', '07:50:00', 5),
        ])

    def test_stop_right_after_a_completed_program_opens_a_block(self):
        # regression: 04/06/2026 14:19:38 -> 15:58:00 was not recorded at all
        e = run([
            start_program('P.007', '14:16:37', todo=5),
            command('Start worklist', '14:16:37'),
            boards('P.007', 5, '14:19:38'),
            command('Stop worklist', '14:19:38'),
            session('End Session', '15:58:00'),
        ])
        self.assertEqual(records(e.drain_ops()), [
            rec('P.007', '14:16:37', '14:19:38', 5),
            block('14:19:38', '15:58:00'),
        ])

    def test_short_stop_does_not_split_the_record(self):
        e = run([
            start_program('A.001', '10:00:00', todo=10),
            command('Start worklist', '10:00:00'),
            boards('A.001', 2, '10:04:00'),
            emergency('10:05:00'),
            command('Restart worklist', '10:07:59'),
            boards('A.001', 10, '10:15:00'),
        ])
        self.assertEqual(records(e.drain_ops()), [rec('A.001', '10:00:00', '10:15:00', 10)])

    def test_close_stops_make_one_block_from_the_first(self):
        e = run([
            start_program('A.001', '10:00:00', todo=10),
            command('Start worklist', '10:00:00'),
            boards('A.001', 2, '10:04:00'),
            command('Stop worklist', '10:05:00'),
            emergency('10:06:00'),
            command('Start worklist', '10:20:00'),
        ])
        self.assertEqual(records(e.drain_ops()), [
            rec('A.001', '10:00:00', '10:05:00', 2),
            block('10:05:00', '10:20:00'),
        ])

    def test_power_on_is_a_block(self):
        e = run([
            session('Init Session', '05:54:04'),
            emergency('05:54:04'),
            start_program('P.004', '05:57:33'),
            command('Start worklist', '05:57:33'),
        ])
        self.assertEqual(records(e.drain_ops()), [block('05:54:04', '05:57:33')])

    def test_crash_closes_at_the_last_event_read(self):
        e = run([
            start_program('A.001', '10:00:00', todo=10),
            command('Start worklist', '10:00:00'),
            boards('A.001', 2, '10:04:00'),
            message('1388', '10:06:00'),
            session('Init Session', '13:00:00'),
        ])
        self.assertEqual(records(e.drain_ops()), [rec('A.001', '10:00:00', '10:06:00', 2)])

    def test_board_counter_follows_the_start_program(self):
        # a program run again from scratch reports done: 0, its boards count again
        e = run([
            start_program('A.001', '10:00:00', todo=3),
            command('Start worklist', '10:00:00'),
            boards('A.001', 3, '10:05:00'),
            start_program('A.001', '10:06:00', done=0, todo=3),
            boards('A.001', 3, '10:10:00'),
        ])
        self.assertEqual([r['boards'] for r in records(e.drain_ops())], [3, 3])

    def test_packs_follow_the_boards(self):
        e = run([
            start_program('A.001', '10:00:00', todo=10),
            command('Start worklist', '10:00:00'),
            boards('A.001', 2, '10:04:00'),
            boards('A.001', 5, '10:08:00'),
        ])
        self.assertEqual([op['qty'] for op in e.drain_ops() if op['op'] == 'add_pack'], [2, 3])

    def test_tick_confirms_a_stop_without_new_lines(self):
        e = run([
            start_program('A.001', '10:00:00', todo=10),
            command('Start worklist', '10:00:00'),
            boards('A.001', 2, '10:04:00'),
            command('Stop worklist', '10:05:00'),
        ])
        e.tick(datetime(2026, 5, 29, 10, 8, 5))
        self.assertEqual(records(e.ops)[-1]['action'], 'working')
        e.tick(datetime(2026, 5, 29, 10, 8, 11))
        self.assertEqual(records(e.drain_ops()), [
            rec('A.001', '10:00:00', '10:05:00', 2),
            rec('block', '10:05:00', None, action='block'),
        ])

    def test_labels_are_asked_once_per_program(self):
        e = run([
            piece('A.001', '10:00:00'),
            piece('A.001', '10:00:05'),
            piece('B.001', '10:01:00'),
        ])
        self.assertEqual([op['barcode'] for op in e.drain_ops() if op['op'] == 'print_labels'],
                         ['A.001', 'B.001'])

    def test_short_alarm_creates_no_state(self):
        e = run([message('1477', '10:00:00'), message('-1477', '10:00:20')])
        self.assertFalse([op for op in e.drain_ops() if op['op'].endswith('_state')])

    def test_long_alarm_creates_a_state_from_its_start(self):
        e = run([message('1477', '10:00:00'), message('-1477', '10:00:45')])
        ops = e.drain_ops()
        self.assertEqual([(op['op'], op.get('start'), op.get('end')) for op in ops], [
            ('create_state', '2026-05-29 10:00:00', None),
            ('close_state', None, '2026-05-29 10:00:45'),
        ])
        self.assertEqual(ops[0]['name'], 'Attesa rimozione rifili/finiti')

    def test_alarm_still_active_creates_its_state_at_max_time(self):
        e = run([message('32', '10:00:00')])
        e.tick(datetime(2026, 5, 29, 10, 0, 45))
        self.assertEqual([op['op'] for op in e.drain_ops()], ['create_state'])

    def test_blade_alarm_is_immediate(self):
        e = run([message('1083', '10:00:00')])
        self.assertEqual([op['op'] for op in e.drain_ops()], ['create_state'])

    def test_unmonitored_alarm_is_ignored(self):
        e = run([message('1388', '10:00:00'), message('-1388', '10:05:00')])
        self.assertFalse(e.drain_ops())

    def test_state_survives_a_restart(self):
        lines = [
            start_program('A.001', '10:00:00', todo=10),
            command('Start worklist', '10:00:00'),
            boards('A.001', 2, '10:04:00'),
            message('32', '10:04:30'),
            command('Stop worklist', '10:05:00'),
            command('Start worklist', '10:20:00'),
            message('-32', '10:21:00'),
            boards('A.001', 10, '10:30:00'),
            piece('A.001', '10:30:10'),
        ]
        whole = run(lines).drain_ops()
        first = run(lines[:5])
        saved = json.loads(json.dumps(first.to_dict()))
        resumed = run(lines[5:], ProductivityEngine.from_dict(saved))
        self.assertEqual(resumed.drain_ops(), whole)


if __name__ == '__main__':
    unittest.main()
