"""Order a single UDP publisher's packets across process restarts."""
from collections import deque
import time


class StreamOrder:
    def __init__(self, stale_sec, clock=time.monotonic):
        self.stale_sec, self.clock = stale_sec, clock
        self.session = None
        self.sequence = None
        self.arrived = None
        self.retired = deque(maxlen=64)

    def accept(self, sequence, session=None):
        if type(sequence) is not int or not 0 <= sequence <= 0xffffffffffffffff:
            return False
        if session is not None and (not isinstance(session, str) or not 1 <= len(session) <= 64):
            return False
        now = self.clock()
        if session is not None:
            if session in self.retired:
                return False
            if session == self.session:
                if self.sequence is not None and sequence <= self.sequence:
                    return False
            elif self.session is not None:
                self.retired.append(self.session)
        elif self.session is not None:
            # Do not let an old sessionless sender replace an identified process.
            return False
        elif self.sequence is not None:
            if sequence == self.sequence:
                return False
            if sequence < self.sequence and now - self.arrived < self.stale_sec:
                return False
        self.session, self.sequence, self.arrived = session, sequence, now
        return True
