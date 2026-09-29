import json
import os

# default configuration

CONFIGURATIONFILENAME = 'configuration.json'
DEFAULTEVENTFILE = 'Event.log'
DEFAULTEVENTBKPFILE = 'EvtBack.log'
DEFAULTSERVER = 'localhost'
DEFAULTPORT = 8069
DEFAULTDBNAME = 'odoo'
DEFAULTUSER = 'user'
DEFAULTPASSWORD = 'password'
DEFAULTWORKCENTERCODE = 'MCH1'
DEFAULTINTERVAL = 180
DEFAULTLOGFILE = 'Error.log'
# MQTT broker on the saw site (event_new_copy_v2.py); credentials only in configuration.json
DEFAULTMQTTHOST = '192.168.20.9'
DEFAULTMQTTPORT = 1883
DEFAULTMQTTTOPIC = 'sez/selco'
DEFAULTMQTTUSER = ''
DEFAULTMQTTPASSWORD = ''

MQTT_DEFAULTS = {
    'mqtt_host': DEFAULTMQTTHOST,
    'mqtt_port': DEFAULTMQTTPORT,
    'mqtt_topic': DEFAULTMQTTTOPIC,
    'mqtt_user': DEFAULTMQTTUSER,
    'mqtt_password': DEFAULTMQTTPASSWORD,
}


class Configuration:

    def __init__(self):

        if not self._check():
            self._create()
        self._load()

    def _check(self):

        if os.path.exists(CONFIGURATIONFILENAME):
            return True
        else:
            return False

    def _create(self):
        with open(CONFIGURATIONFILENAME, 'w', encoding="utf-8") as f:
            # write default configuration

            c = {
                # input :
                'file': DEFAULTEVENTFILE,
                # output
                'server': DEFAULTSERVER,
                'port': DEFAULTPORT,
                # db settings
                'db_name': DEFAULTDBNAME,
                'user': DEFAULTUSER,
                'password': DEFAULTPASSWORD,
                'workcenter_code': DEFAULTWORKCENTERCODE,
                # program settings
                'interval': DEFAULTINTERVAL,
                'logfile': DEFAULTLOGFILE,
                'filebkp': DEFAULTEVENTBKPFILE,
            }
            c.update(MQTT_DEFAULTS)

            c_json = json.dumps(c)
            f.write(c_json)

    def _load(self):
        with open(CONFIGURATIONFILENAME, 'r', encoding="utf-8") as f:
            c = json.load(f)
            self.file = c['file']
            self.filebkp = c['filebkp']
            self.server = c['server']
            self.port = c['port']
            self.db_name = c['db_name']
            self.user = c['user']
            self.password = c['password']
            self.workcenter_code = c['workcenter_code']
            self.interval = c['interval']
            self.logfile = c['logfile']
            # added with MQTT: older files don't have them
            for key, default in MQTT_DEFAULTS.items():
                setattr(self, key, c.get(key, default))


    def save(self):
        with open(CONFIGURATIONFILENAME, 'w', encoding="utf-8") as f:
            # save default configuration

            c = {
                # input :
                'file': self.file,
                # output
                'server': self.server,
                'port': self.port,
                # db settings
                'db_name': self.db_name,
                'user': self.user,
                'password': self.password,
                'workcenter_code': self.workcenter_code,
                # program settings
                'interval': self.interval,
                'logfile': self.logfile,
                'filebkp': self.filebkp,
            }
            for key in MQTT_DEFAULTS:
                c[key] = getattr(self, key)

            c_json = json.dumps(c)
            f.write(c_json)