"""Incremental reading of the Selco Event.log.

Taken from ``tail_windows_copy_method`` of event_new_copy_v2.py: the file is never kept open,
only its size is checked, and only the new bytes are read. Differences (docs/progetto.md §9.3):

- the position is part of the logger state, so a restart resumes where it stopped;
- when OSI rotates the log (the file shrinks or its first line changes), the lines that were still
  unread are recovered from the tail of EvtBack.log before reading the new Event.log from the start;
- the bytes are decoded in memory, a line split in the middle of a UTF-8 character included.
"""
import logging
import os

from events import parse_time

_logger = logging.getLogger(__name__)

HEAD_BYTES = 512


class EventLogReader:

    def __init__(self, path, backup_path=None, state=None):
        self.path = path
        self.backup_path = backup_path
        state = state or {}
        self.offset = state.get('offset')
        self.head = state.get('head', '')
        self.partial = state.get('partial', '').encode('utf-8', 'surrogateescape')
        self.last_line = state.get('last_line')

    def to_dict(self):
        return {
            'offset': self.offset,
            'head': self.head,
            'partial': self.partial.decode('utf-8', 'surrogateescape'),
            'last_line': self.last_line,
        }

    def _read_head(self):
        with open(self.path, 'rb') as f:
            return f.readline(HEAD_BYTES).decode('utf-8', 'replace')

    def _read_bytes(self, start, end):
        with open(self.path, 'rb') as f:
            f.seek(start)
            return f.read(end - start)

    def _rotated(self, size, head):
        if size < self.offset:
            return True
        # the saved head can be an incomplete first line: compare it as a prefix
        return bool(self.head) and not head.startswith(self.head)

    def _split(self, data):
        data = self.partial + data
        parts = data.split(b'\n')
        self.partial = parts.pop()
        lines = []
        for p in parts:
            line = p.decode('utf-8', 'replace').rstrip('\r')
            if line.strip():
                lines.append(line)
        return lines

    def _recover_from_backup(self):
        """Lines written after the last one read, before the rotation moved them to EvtBack.log."""
        if not self.backup_path or not self.last_line:
            return []
        try:
            with open(self.backup_path, 'rb') as f:
                backup = [l.decode('utf-8', 'replace').rstrip('\r') for l in f.read().split(b'\n')]
        except OSError as e:
            _logger.error('Log rotated, backup %s not readable: %s', self.backup_path, e)
            return []
        backup = [l for l in backup if l.strip()]
        for i in range(len(backup) - 1, -1, -1):
            if backup[i] == self.last_line:
                return backup[i + 1:]
        # last line not found: fall back on the timestamp (lines of the same second are lost)
        last_t = parse_time(self.last_line.split('\t'))
        if last_t is None:
            _logger.error('Log rotated, last line read not found in %s', self.backup_path)
            return []
        _logger.warning('Log rotated, last line read not found in %s: recovering by time', self.backup_path)
        return [l for l in backup if (parse_time(l.split('\t')) or last_t) > last_t]

    def read(self):
        """New complete lines since the last call. The first call ever only takes the position."""
        try:
            size = os.path.getsize(self.path)
            if self.offset is None:
                self.offset = size
                self.head = self._read_head()
                return []
            if size == self.offset:
                return []
            head = self._read_head()
            lines = []
            if self._rotated(size, head):
                _logger.info('Event log rotated (size %s -> %s)', self.offset, size)
                lines += self._recover_from_backup()
                self.offset = 0
                self.partial = b''
            self.head = head
            data = self._read_bytes(self.offset, size)
        except FileNotFoundError:
            return []
        except PermissionError as e:
            # the file is being written by OSI: next time
            _logger.warning('Event log busy: %s', e)
            return []
        self.offset += len(data)
        lines += self._split(data)
        if lines:
            self.last_line = lines[-1]
        return lines
