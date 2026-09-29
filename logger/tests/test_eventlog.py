import os
import shutil
import tempfile
import unittest

from common import boards, line

from eventlog import EventLogReader


class TestEventLogReader(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.path = os.path.join(self.dir, 'Event.log')
        self.backup = os.path.join(self.dir, 'EvtBack.log')
        self.lines = [boards('P.001', n, '10:00:%02d' % n) for n in range(1, 8)]

    def write(self, text, mode='ab', path=None):
        with open(path or self.path, mode) as f:
            f.write(text.encode('utf-8') if isinstance(text, str) else text)

    def crlf(self, lines):
        return ''.join(l + '\r\n' for l in lines)

    def test_first_read_starts_at_the_end_then_reads_the_new_lines(self):
        self.write(self.crlf(self.lines[:2]))
        reader = EventLogReader(self.path, self.backup)
        self.assertEqual(reader.read(), [])
        self.write(self.crlf(self.lines[2:4]))
        self.assertEqual(reader.read(), self.lines[2:4])
        self.assertEqual(reader.read(), [])

    def test_an_incomplete_line_waits_for_its_end(self):
        self.write(self.crlf(self.lines[:1]))
        reader = EventLogReader(self.path, self.backup)
        reader.read()
        self.write(self.lines[1][:10])
        self.assertEqual(reader.read(), [])
        self.write(self.lines[1][10:] + '\r\n')
        self.assertEqual(reader.read(), [self.lines[1]])

    def test_a_character_split_between_two_reads(self):
        text = line('Active command', '', 'Jog più Gruppo S', '10:00:00')
        data = (text + '\r\n').encode('utf-8')
        cut = data.index('ù'.encode('utf-8')) + 1   # in the middle of the two bytes
        self.write(b'')
        reader = EventLogReader(self.path, self.backup)
        reader.read()
        self.write(data[:cut])
        self.assertEqual(reader.read(), [])
        self.write(data[cut:])
        self.assertEqual(reader.read(), [text])

    def test_resumes_from_the_saved_state(self):
        self.write(self.crlf(self.lines[:2]))
        reader = EventLogReader(self.path, self.backup)
        reader.read()
        self.write(self.crlf(self.lines[2:3]))
        reader.read()
        saved = reader.to_dict()
        # lines written while the logger was not running
        self.write(self.crlf(self.lines[3:5]))
        self.assertEqual(EventLogReader(self.path, self.backup, saved).read(), self.lines[3:5])

    def test_rotation_recovers_the_unread_lines_from_the_backup(self):
        self.write(self.crlf(self.lines[:3]))
        reader = EventLogReader(self.path, self.backup)
        reader.read()
        self.write(self.crlf(self.lines[3:4]))
        reader.read()
        # OSI writes two more lines, then moves the log to EvtBack.log and starts a new one
        self.write(self.crlf(self.lines[4:6]))
        shutil.move(self.path, self.backup)
        self.write(self.crlf(self.lines[6:]), mode='wb')
        self.assertEqual(reader.read(), self.lines[4:])

    def test_rotation_to_a_longer_file_is_seen_by_its_first_line(self):
        self.write(self.crlf(self.lines[:1]))
        reader = EventLogReader(self.path, self.backup)
        reader.read()
        self.write(self.crlf(self.lines[1:2]))
        reader.read()
        shutil.move(self.path, self.backup)
        new = [boards('Q.001', n, '11:00:%02d' % n) for n in range(1, 6)]
        self.write(self.crlf(new), mode='wb')
        self.assertEqual(reader.read(), new)

    def test_missing_file_reads_nothing(self):
        reader = EventLogReader(self.path, self.backup)
        self.assertEqual(reader.read(), [])
        self.write(self.crlf(self.lines[:1]))
        self.assertEqual(reader.read(), [])   # first read: position only
        self.write(self.crlf(self.lines[1:2]))
        self.assertEqual(reader.read(), self.lines[1:2])


if __name__ == '__main__':
    unittest.main()
