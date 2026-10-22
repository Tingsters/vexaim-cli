# Transient AIM 1.0.4 power lease. Never saved as a robot project.
class _VaPowerLease:
    def __init__(self, token, ttl_ms, restore_to):
        self.control = getattr(robot, '_sleep_disable', None)
        if not callable(self.control):
            raise RuntimeError('Observed AIM sleep control is missing')
        previous = self.control()
        if type(previous) is not bool:
            raise RuntimeError('AIM sleep state is not Boolean')
        self.previous = previous if restore_to is None else restore_to
        self.token = token
        self.now = robot.timer.system
        self.ttl_ms = ttl_ms
        self.renewed_ms = int(self.now())
        self.last_tick_ms = int(self.now())
        self.ticks = 0
        self.active = False
        self.expired = False
        self.released = False

    def start(self):
        try:
            self.control(True)
            if self.control() is not True:
                raise RuntimeError('AIM sleep-disable readback failed')
            self.active = True
            self.worker = Thread(self.watch)
            started_ms = int(self.now())
            while self.ticks == 0 and self.age(started_ms) < 1000:
                wait(20, MSEC)
            if self.ticks == 0 or not self.active:
                raise RuntimeError('AIM power watchdog did not start')
        except BaseException:
            self.release(self.token)
            raise
        return self.status()

    def tick(self):
        if globals().get('_va_power_lease') is not self:
            self.active = False
            return
        self.ticks += 1
        self.last_tick_ms = int(self.now())
        if self.age(self.renewed_ms) >= self.ttl_ms:
            self.expired = True
            self.release(self.token)

    def age(self, since_ms):
        return (int(self.now()) - since_ms) & 0xffffffff

    def watch(self):
        try:
            while self.active:
                self.tick()
                wait(100, MSEC)
        finally:
            if self.active and globals().get('_va_power_lease') is self:
                self.release(self.token)

    def renew(self, token, ttl_ms):
        if token != self.token or not self.active:
            raise RuntimeError('Power lease expired or belongs to another owner')
        if self.age(self.last_tick_ms) > 3000:
            raise RuntimeError('Power watchdog stopped advancing')
        self.control(True)
        if self.control() is not True:
            raise RuntimeError('AIM sleep-disable readback failed')
        self.ttl_ms = ttl_ms
        self.renewed_ms = int(self.now())
        return self.status()

    def release(self, token):
        if token != self.token:
            raise RuntimeError('Power lease belongs to another owner')
        self.active = False
        if not self.released and globals().get('_va_power_lease') is self:
            self.control(self.previous)
            if self.control() is not self.previous:
                raise RuntimeError('Original AIM sleep setting was not restored')
            self.released = True
        return self.status()

    def status(self):
        return {'token': self.token, 'active': self.active, 'expired': self.expired,
                'sleep_disabled': self.control(), 'restore_to': self.previous,
                'watchdog_ticks': self.ticks,
                'watchdog_age_ms': self.age(self.last_tick_ms),
                'remaining_ms': max(0, self.ttl_ms - self.age(self.renewed_ms))}


def _va_power_acquire(token, ttl_ms, restore_to=None):
    global _va_power_lease
    if ttl_ms <= 0 or ttl_ms > 1800000:
        raise ValueError('Power lease must fit the client idle deadline')
    old = globals().get('_va_power_lease')
    if old is not None and old.active:
        if old.token != token:
            raise RuntimeError('Another power lease still owns this REPL')
        if old.age(old.last_tick_ms) <= 3000:
            return old.renew(token, ttl_ms)
        old.release(token)
    _va_power_lease = _VaPowerLease(token, ttl_ms, restore_to)
    return _va_power_lease.start()
