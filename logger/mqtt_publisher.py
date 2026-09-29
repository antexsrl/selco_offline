"""Publication of the saw events on MQTT, as event_new_copy_v2.py did.

Same topic and same JSON messages (events.mqtt_event). The broker is on the saw site
(192.168.20.9), so it works with the VPN down too.

paho-mqtt runs its network loop in a thread and reconnects by itself. Messages wait in a queue,
saved with the logger state, while the broker is not connected. The script only published live
events (it skipped the log already written at start): messages older than MAX_AGE are dropped,
so a logger restarted after a long stop doesn't replay old pieces to the consumers.
"""
import json
import logging
from datetime import datetime, timedelta

import paho.mqtt.client as mqtt

_logger = logging.getLogger(__name__)

DATE_FORMAT = '%Y-%m-%d %H:%M:%S'
MAX_AGE = timedelta(minutes=2)
MAX_QUEUE = 2000
KEEPALIVE = 5          # seconds, as the script
RECONNECT_DELAY = 5    # seconds, as the script


class MqttPublisher:

    def __init__(self, config, state=None, client_factory=None):
        self.config = config
        self.enabled = bool(getattr(config, 'mqtt_host', ''))
        self.queue = (state or {}).get('queue', [])
        self.client_factory = client_factory or self._new_client
        self.client = None

    def to_dict(self):
        return {'queue': self.queue}

    def _new_client(self):
        c = self.config
        client = mqtt.Client()
        if c.mqtt_user:
            client.username_pw_set(c.mqtt_user, c.mqtt_password)
        client.reconnect_delay_set(min_delay=1, max_delay=RECONNECT_DELAY)
        client.on_connect = lambda cl, userdata, flags, rc: _logger.info('MQTT connected (rc %s)', rc)
        client.on_disconnect = lambda cl, userdata, rc: _logger.warning('MQTT disconnected (rc %s)', rc)
        client.connect_async(c.mqtt_host, c.mqtt_port, keepalive=KEEPALIVE)
        client.loop_start()
        return client

    def enqueue(self, t, message):
        if not self.enabled:
            return
        self.queue.append({'t': t.strftime(DATE_FORMAT) if t else None, 'message': message})
        if len(self.queue) > MAX_QUEUE:
            _logger.warning('MQTT queue full: %s oldest messages dropped', len(self.queue) - MAX_QUEUE)
            del self.queue[:-MAX_QUEUE]

    def flush(self, now=None):
        """Publish the queued messages. Returns how many were published."""
        if not self.enabled or not self.queue:
            return 0
        now = now or datetime.now()
        fresh = [q for q in self.queue
                 if not q['t'] or now - datetime.strptime(q['t'], DATE_FORMAT) <= MAX_AGE]
        if len(fresh) < len(self.queue):
            _logger.warning('MQTT: %s messages older than %s dropped', len(self.queue) - len(fresh), MAX_AGE)
            self.queue = fresh
        if not self.queue:
            return 0
        if self.client is None:
            self.client = self.client_factory()
        if not self.client.is_connected():
            return 0
        sent = 0
        while self.queue:
            payload = json.dumps(self.queue[0]['message'])
            info = self.client.publish(self.config.mqtt_topic, payload)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                _logger.warning('MQTT publish failed (rc %s), %s messages queued', info.rc, len(self.queue))
                break
            _logger.debug('MQTT %s', payload)
            self.queue.pop(0)
            sent += 1
        return sent

    def reconfigure(self):
        """Apply a change of the broker settings: the next flush connects again."""
        self.stop()
        self.enabled = bool(self.config.mqtt_host)

    def stop(self):
        if self.client is not None:
            self.client.loop_stop()
            self.client.disconnect()
            self.client = None
