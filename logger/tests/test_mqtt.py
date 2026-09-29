import json
import unittest
from datetime import datetime

import paho.mqtt.client as mqtt

from common import boards, command, line, piece, start_program

from events import mqtt_event
from mqtt_publisher import MqttPublisher


class Config:
    mqtt_host = '192.168.20.9'
    mqtt_port = 1883
    mqtt_topic = 'sez/selco'
    mqtt_user = ''
    mqtt_password = ''


class FakeInfo:
    def __init__(self, rc):
        self.rc = rc


class FakeClient:

    def __init__(self):
        self.connected = False
        self.published = []
        self.rc = mqtt.MQTT_ERR_SUCCESS

    def is_connected(self):
        return self.connected

    def publish(self, topic, payload):
        if self.rc == mqtt.MQTT_ERR_SUCCESS:
            self.published.append((topic, json.loads(payload)))
        return FakeInfo(self.rc)


T = datetime(2026, 5, 29, 10, 0, 0)


class TestMqttEvent(unittest.TestCase):
    """Messages of format_event() in event_new_copy_v2.py (checked equal on 172,206 real lines)."""

    def test_produced_piece(self):
        self.assertEqual(mqtt_event(piece('PE2501622_2_31.018', '13:23:28')), (
            datetime(2026, 5, 29, 13, 23, 28),
            {'event_type': 'produced_piece', 'cutlist_name': 'PE2501622_2_31', 'pattern_nr': '018',
             'height': '807.00', 'length': '407.00', 'quantity': '5'},
        ))

    def test_start_program(self):
        self.assertEqual(mqtt_event(start_program('PE2600837_2_01.004', '13:06:38', done=0, todo=32))[1], {
            'event_type': 'start_program', 'list_name': 'PE2600837_2_01', 'program_name': 'PE2600837_2_01.004',
            'measure': '366000x187000x2200', 'boards_done': 0, 'boards_todo': 32,
            'cut_cross': '0.00', 'cut_long': '0.00',
        })

    def test_boards_done(self):
        self.assertEqual(mqtt_event(boards('PE2600995_4_01.001', 5, '07:50:37'))[1], {
            'event_type': 'boards_done', 'program_name': 'PE2600995_4_01.001', 'boards_done': 5,
        })

    def test_other_lines_are_not_published(self):
        for l in (command('Stop worklist', '10:00:00'), line('Message', '1477', '', '10:00:00'),
                  command('Start program', '10:00:00'), ''):
            self.assertIsNone(mqtt_event(l), l)

    def test_malformed_piece_is_skipped(self):
        with self.assertLogs('events', 'WARNING'):
            self.assertIsNone(mqtt_event(line('PRODUCED PIECE', '', 'PE2501622_2_31;Part. Dimension: 1x2', '10:00:00')))


class TestMqttPublisher(unittest.TestCase):

    def setUp(self):
        self.client = FakeClient()
        self.publisher = MqttPublisher(Config(), client_factory=lambda: self.client)

    def test_messages_wait_for_the_connection_then_go_in_order(self):
        self.publisher.enqueue(T, {'n': 1})
        self.publisher.enqueue(T, {'n': 2})
        self.assertEqual(self.publisher.flush(T), 0)
        self.client.connected = True
        self.assertEqual(self.publisher.flush(T), 2)
        self.assertEqual(self.client.published, [('sez/selco', {'n': 1}), ('sez/selco', {'n': 2})])
        self.assertFalse(self.publisher.queue)

    def test_failed_publish_keeps_the_message(self):
        self.client.connected = True
        self.client.rc = mqtt.MQTT_ERR_NO_CONN
        self.publisher.enqueue(T, {'n': 1})
        with self.assertLogs('mqtt_publisher', 'WARNING'):
            self.assertEqual(self.publisher.flush(T), 0)
        self.assertEqual(len(self.publisher.queue), 1)

    def test_old_messages_are_dropped(self):
        # a logger restarted after a long stop must not replay old pieces
        self.client.connected = True
        self.publisher.enqueue(datetime(2026, 5, 29, 9, 0, 0), {'n': 'old'})
        self.publisher.enqueue(T, {'n': 'new'})
        with self.assertLogs('mqtt_publisher', 'WARNING'):
            self.publisher.flush(T)
        self.assertEqual(self.client.published, [('sez/selco', {'n': 'new'})])

    def test_queue_survives_a_restart(self):
        self.publisher.enqueue(T, {'n': 1})
        saved = json.loads(json.dumps(self.publisher.to_dict()))
        resumed = MqttPublisher(Config(), saved, client_factory=lambda: self.client)
        self.client.connected = True
        resumed.flush(T)
        self.assertEqual(self.client.published, [('sez/selco', {'n': 1})])

    def test_reconfigure_connects_again(self):
        self.client.connected = True
        self.publisher.enqueue(T, {'n': 1})
        self.publisher.flush(T)
        self.client.loop_stop = self.client.disconnect = lambda: None
        self.publisher.config.mqtt_host = ''
        self.publisher.reconfigure()
        self.assertIsNone(self.publisher.client)
        self.publisher.enqueue(T, {'n': 2})
        self.assertFalse(self.publisher.queue)

    def test_no_broker_configured_publishes_nothing(self):
        config = Config()
        config.mqtt_host = ''
        publisher = MqttPublisher(config, client_factory=lambda: self.fail('no client expected'))
        publisher.enqueue(T, {'n': 1})
        self.assertEqual(publisher.flush(T), 0)
        self.assertFalse(publisher.queue)


if __name__ == '__main__':
    unittest.main()
