# CLI-owned, transient AIM behaviors. Native VEX APIs remain on `robot`.
# Algorithm references: api.vex.com/aim/home/python/Macro.html and Logic/Timer.html.
_vb_owner = None


class _VxBehaviors:
    def __init__(self, limit_ms=30000, job=None, emit=False):
        self.clock = Timer()
        self.system = getattr(robot.timer, 'system', None)
        self.origin = self.now()
        self.limit_ms = limit_ms
        self.timeout_ms = min(30000, limit_ms)
        self.move_mmps = 80
        self.turn_dps = 30
        self.contact_mmps = 80
        self.job = job
        self.emit = emit
        self.active = False
        self.expired = False
        self.generation = 0
        self.started = False
        self.phase = 'preparing_behavior'
        self.last_call = None
        self.carrying = None
        self.last_target = None
        self.near = False
        self.last_seen_ms = 0

    def now(self):
        return int(self.system()) if self.system is not None else int(self.clock.time(MSEC))

    def age(self, since):
        return (self.now() - since) & 0xffffffff

    def begin(self):
        global _vb_owner
        if _vb_owner is not None and _vb_owner.active:
            raise RuntimeError('Conflicting behavior; cancel the current activity first')
        if self.job is None and _vx_busy():
            raise RuntimeError('Conflicting native action; cancel it before a new behavior')
        if not robot.is_stopped() or robot.inertial.is_calibrating():
            raise RuntimeError('Robot moving or calibrating; behavior not started')
        _vb_owner = self
        self.active = True
        try:
            self.arm()
        except BaseException:
            self.active = False
            _vb_owner = None
            raise
        return self

    def arm(self):
        # Native timer callbacks survive some executions: obsolete callbacks are inert.
        self.generation += 1
        generation = self.generation
        def expired():
            if self.active and _vb_owner is self and self.generation == generation:
                self.expired = True
                robot.stop_all_movement()
        event = getattr(robot.timer, 'event', None)
        if event is not None:
            event(expired, max(1, self.timeout_ms - self.age(self.origin)))
            wait(15, MSEC)

    def configure(self, move_mmps=80, turn_dps=30, contact_mmps=None, timeout_ms=30000):
        if self.started:
            raise RuntimeError('Configure once before the first behavior')
        contact_mmps = move_mmps if contact_mmps is None else contact_mmps
        for name, value, maximum in (('move_mmps', move_mmps, 200),
                                      ('turn_dps', turn_dps, 150),
                                      ('contact_mmps', contact_mmps, 200),
                                      ('timeout_ms', timeout_ms, self.limit_ms)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= maximum:
                raise ValueError(name + ' outside native/activity limits')
        if int(timeout_ms) != timeout_ms or timeout_ms < 1:
            raise ValueError('timeout_ms must be a positive whole number')
        self.move_mmps = move_mmps
        self.turn_dps = turn_dps
        self.contact_mmps = contact_mmps
        self.timeout_ms = int(timeout_ms)
        self.arm()

    def check(self):
        if not self.active or _vb_owner is not self:
            raise RuntimeError('Behavior no longer owns this activity')
        if self.job is not None and self.job.get('cancel_requested'):
            raise RuntimeError('Behavior cancelled')
        if self.expired or self.age(self.origin) >= self.timeout_ms:
            self.expired = True
            robot.stop_all_movement()
            raise RuntimeError('Behavior deadline during ' + self.phase + '; last call: ' + str(self.last_call))

    def call(self, name, fn, *args):
        self.check()
        self.last_call = name
        if self.job is not None:
            self.job['last_call'] = name
        result = fn(*args)
        self.check()
        return result

    def pause(self, milliseconds):
        # Iteration bounds remain finite even if a firmware clock stops advancing.
        for _ in range(max(1, int((milliseconds + 19) // 20))):
            self.call('wait', wait, min(20, milliseconds), MSEC)

    def report(self, phase, **details):
        self.phase = phase
        event = {'event': 'progress', 'phase': phase, 'robot_elapsed_ms': self.age(self.origin)}
        event.update(details)
        if self.job is not None:
            self.job['phase'] = phase
            self.job['progress'] = (self.job.get('progress', []) + [event])[-24:]
        if self.emit:
            print('__VEXAIM_EVENT__' + _vx_json.dumps(event))

    def kind(self, target):
        for name in ('BLUE_BARREL', 'ORANGE_BARREL', 'SPORTS_BALL', 'AIM_ROBOT'):
            if name in globals() and target == globals()[name]:
                return name
        for name in ('ALL_TAGS', 'TAG0', 'TAG1', 'TAG2', 'TAG3', 'TAG4'):
            if name in globals() and target == globals()[name]:
                return 'TAG'
        constructor = globals().get('Tagdesc')
        if constructor is not None and isinstance(target, type(constructor(0))):
            return 'TAG'
        if isinstance(target, str) and target.startswith('TAG') and target[3:].isdigit() and 0 <= int(target[3:]) <= 37:
            return 'TAG'
        raise ValueError('Behavior target must be native kit cargo, AIM_ROBOT or an AprilTag')

    def prepare(self, target):
        self.started = True
        kind = self.kind(target)
        mode = 'tag_detection' if kind == 'TAG' else 'model_detection'
        setter = getattr(robot.vision, mode, None)
        if setter is not None:
            self.call('vision.' + mode, setter, True)
        return kind

    def cargo_fn(self, cargo):
        name = {'BLUE_BARREL': 'has_blue_barrel', 'ORANGE_BARREL': 'has_orange_barrel',
                'SPORTS_BALL': 'has_sports_ball'}.get(self.kind(cargo))
        if name is None:
            raise ValueError('Collection requires a barrel or sports ball')
        fn = getattr(robot, name, None)
        if fn is None:
            fn = getattr(robot.vision, name, None)
        if fn is None:
            raise RuntimeError('unsupported_firmware: robot.' + name)
        return fn

    def held(self, cargo):
        return bool(self.call('cargo.' + self.kind(cargo), self.cargo_fn(cargo)))

    def confirm(self, cargo, wanted=True):
        votes = 0
        for _ in range(3):
            votes += self.held(cargo) == wanted
            if votes >= 2:
                return True
            self.pause(100)
        return False

    def objects(self, target):
        data = self.call('vision.get_data', robot.vision.get_data, target, 8)
        # AIM's native tuple has special out-of-bounds behavior. Bound indexing.
        objects = [data[n] for n in range(min(8, len(data))) if getattr(data[n], 'exists', False)]
        if not objects:
            return None
        # Prefer continuity of the selected target over alternating between barrels.
        if self.last_target is not None:
            return min(objects, key=lambda o: abs(o.bearing - self.last_target.bearing))
        return max(objects, key=lambda o: o.width)

    def stop(self):
        self.call('stop_all_movement', robot.stop_all_movement)
        for _ in range(50):
            if self.call('is_stopped', robot.is_stopped):
                return
            self.pause(20)
        raise RuntimeError('Stop not confirmed during ' + self.phase)

    def position(self):
        return (self.call('get_x_position', robot.get_x_position),
                self.call('get_y_position', robot.get_y_position))

    def motion(self, fn, args, limit_ms, cargo=None):
        began = self.now()
        self.call('finite_motion', fn, *args)
        self.pause(80)  # Motion status may lag dispatch.
        positives = 0
        for _ in range(max(5, int(limit_ms // 20) + 1)):
            if self.age(began) >= limit_ms:
                break
            if cargo is not None:
                positives = positives + 1 if self.held(cargo) else 0
                if positives >= 2:
                    self.stop()
                    return
            if self.call('is_stopped', robot.is_stopped):
                return
            self.pause(20)
        self.stop()
        raise RuntimeError('Motion stalled during ' + self.phase)

    def align(self, obj):
        if abs(obj.bearing) <= 5:
            return
        self.report('aligning', bearing=obj.bearing)
        self.stop()
        heading = (self.call('inertial.get_heading', robot.inertial.get_heading) + obj.bearing) % 360
        self.motion(robot.turn_to, (heading, self.turn_dps, DPS, False),
                    min(4000, int(abs(obj.bearing) / self.turn_dps * 1500 + 700)))
        self.pause(100)

    def find(self, target, direction=None):
        self.prepare(target)
        self.last_target = None
        direction = RIGHT if direction is None else direction
        if direction not in (LEFT, RIGHT):
            raise ValueError('Find direction must be LEFT or RIGHT')
        self.report('searching', target=str(target))
        began = self.now()
        previous = self.call('inertial.get_rotation', robot.inertial.get_rotation)
        travel = 0
        rotating = False
        phase_limit = min(15000, int(360 / self.turn_dps * 1000 + 750))
        for _ in range(320):
            obj = self.objects(target)
            if obj is not None:
                self.stop()
                self.align(obj)
                self.last_target = obj
                self.report('found', search_degrees=round(travel, 1))
                return _vx_plain(obj)
            rotation = self.call('inertial.get_rotation', robot.inertial.get_rotation)
            travel += abs(rotation - previous)
            previous = rotation
            if travel >= 360 or self.age(began) >= phase_limit:
                break
            if not rotating:
                self.call('turn', robot.turn, direction, self.turn_dps, DPS)
                rotating = True
            self.pause(50)
        self.stop()
        self.report('not_found', search_degrees=round(travel, 1))
        raise RuntimeError('not_found: ' + str(target) + '; one search sweep exhausted')

    def reacquire(self, target):
        self.report('reacquiring', target=str(target))
        self.stop()
        heading = self.call('inertial.get_heading', robot.inertial.get_heading)
        for offset in (0, -20, 20, 0):
            if offset:
                self.motion(robot.turn_to, ((heading + offset) % 360, self.turn_dps, DPS, False), 1800)
            obj = self.objects(target)
            if obj is not None:
                self.align(obj)
                self.last_target = obj
                return True
        return False

    def contact(self, cargo, bearing=0):
        self.report('contacting', target=str(cargo), distance_limit_mm=200)
        self.stop()
        self.motion(robot.move_for, (200, bearing, self.contact_mmps, MMPS, False),
                    int(200 / self.contact_mmps * 1500 + 400), cargo)
        return self.confirm(cargo)

    def retained(self, cargo):
        self.report('verifying_retention', target=str(cargo))
        self.stop()
        self.motion(robot.move_for, (40, 180, self.move_mmps, MMPS, False),
                    int(40 / self.move_mmps * 1500 + 500))
        return self.confirm(cargo)

    def capture(self, cargo):
        self.report('approaching_cargo', target=str(cargo))
        began = self.now()
        last = self.last_target
        near = False
        can_commit = False
        last_seen = self.now()
        reacquired = False
        last_command = None
        for _ in range(240):
            # Possession is checked independently of the separate detection frame.
            if self.held(cargo) and self.confirm(cargo):
                return self.retained(cargo)
            obj = self.objects(cargo)
            if obj is not None:
                last_seen = self.now()
                last = obj
                self.last_target = obj
                bottom = getattr(obj, 'originY', 0) + getattr(obj, 'height', 0)
                near = obj.width >= 60 or bottom >= 220
                # A cropped/tilted barrel may disappear before the normal
                # contact threshold. Keep a wider, recent alignment gate for
                # completing the finite stroke through that blind region.
                can_commit = obj.width >= 35 or bottom >= 180
                if abs(obj.bearing) > 12:
                    self.align(obj)
                    last_command = None
                elif near:
                    return self.contact(cargo, obj.bearing) and self.retained(cargo)
                else:
                    if last_command is None or abs(last_command - obj.bearing) > 3:
                        self.call('move_at', robot.move_at, obj.bearing, self.move_mmps, MMPS)
                        last_command = obj.bearing
            elif last is not None and can_commit and abs(last.bearing) <= 12 and self.age(last_seen) <= 500:
                return self.contact(cargo, last.bearing) and self.retained(cargo)
            elif self.age(last_seen) <= 350:
                # The detector is asynchronous. A single empty update, especially
                # just after gyro alignment, is not yet target loss.
                self.pause(50)
                continue
            else:
                self.stop()
                if not reacquired and self.reacquire(cargo):
                    reacquired = True
                    last_command = None
                    continue
                raise RuntimeError('target_lost_before_contact: ' + str(cargo))
            if self.age(began) >= 10000:
                break
            self.pause(50)
        self.stop()
        raise RuntimeError('approach_stalled: ' + str(cargo))

    def collect(self, cargo):
        self.prepare(cargo)
        self.cargo_fn(cargo)  # Reject non-cargo targets before movement.
        if self.confirm(cargo):
            self.carrying = cargo
            return {'collected': True, 'target': str(cargo), 'evidence': 'native_possession'}
        for name in ('BLUE_BARREL', 'ORANGE_BARREL', 'SPORTS_BALL'):
            other = globals().get(name)
            if other is not None and other != cargo and self.held(other) and self.confirm(other):
                raise RuntimeError('wrong_cargo: place the existing cargo before collecting another')
        self.find(cargo)
        for attempt in range(2):
            if self.capture(cargo):
                self.carrying = cargo
                self.report('collected', target=str(cargo))
                return {'collected': True, 'target': str(cargo), 'evidence': 'native_possession_and_retention'}
            if attempt == 0:
                self.report('contact_retry')
                self.motion(robot.move_for, (60, 180, self.move_mmps, MMPS, False),
                            int(60 / self.move_mmps * 1500 + 500))
                # A second charge down the same line repeats a blocked contact.
                # Use the holonomic drive to give the one retry a new viewpoint.
                side = 90 if self.last_target is None or self.last_target.bearing >= 0 else 270
                self.motion(robot.move_for, (80, side, self.move_mmps, MMPS, False),
                            int(80 / self.move_mmps * 1500 + 500))
                if not self.reacquire(cargo):
                    break
        raise RuntimeError('not_collected: ' + str(cargo) + '; contact retry exhausted')

    def approach(self, target):
        kind = self.prepare(target)
        if kind not in ('TAG', 'AIM_ROBOT'):
            raise ValueError('Approach requires an AprilTag or AIM_ROBOT; use collect for cargo')
        threshold = 60 if kind == 'TAG' else 140
        self.find(target)
        self.report('approaching_marker', target=str(target), width_threshold=threshold)
        began = self.now()
        last_cargo = self.now()
        last_seen = self.now()
        reacquired = False
        previous = None
        for _ in range(240):
            if self.carrying is not None:
                if self.held(self.carrying):
                    last_cargo = self.now()
                elif self.age(last_cargo) > 600:
                    raise RuntimeError('cargo_lost_before_placement')
            obj = self.objects(target)
            if obj is None:
                if self.age(last_seen) <= 350:
                    self.pause(50)
                    continue
                self.stop()
                if not reacquired and self.reacquire(target):
                    reacquired = True
                    previous = None
                    continue
                raise RuntimeError('marker_lost: ' + str(target))
            self.last_target = obj
            last_seen = self.now()
            if abs(obj.bearing) > 12:
                self.align(obj)
                previous = None
            elif obj.width >= threshold:
                self.stop()
                return {'approached': _vx_plain(obj)}
            elif previous is None or abs(previous - obj.bearing) > 3:
                self.call('move_at', robot.move_at, obj.bearing, self.move_mmps, MMPS)
                previous = obj.bearing
            if self.age(began) >= 10000:
                break
            self.pause(50)
        raise RuntimeError('marker_approach_stalled')

    def deliver(self, cargo, tag):
        self.cargo_fn(cargo)
        if self.kind(tag) != 'TAG' or tag == globals().get('ALL_TAGS'):
            raise ValueError('Delivery requires an individual AprilTag')
        if not self.confirm(cargo):
            raise RuntimeError('cargo_required: collect the requested cargo first')
        self.carrying = cargo
        self.approach(tag)
        if not self.confirm(cargo):
            raise RuntimeError('cargo_lost_before_placement')
        self.report('placing', target=str(cargo), destination=str(tag))
        self.call('kicker.place', robot.kicker.place)
        self.pause(300)
        self.motion(robot.move_for, (100, 180, self.move_mmps, MMPS, False),
                    int(100 / self.move_mmps * 1500 + 500))
        if not self.confirm(cargo, False):
            raise RuntimeError('release_not_confirmed')
        self.carrying = None
        self.report('delivered', destination=str(tag))
        return {'delivered': True, 'cargo': str(cargo), 'destination': str(tag), 'evidence': 'native_release'}

    def close(self):
        global _vb_owner
        if _vb_owner is not self:
            return
        self.active = False
        self.generation += 1
        robot.stop_all_movement()
        began = self.now()
        for _ in range(50):
            if robot.is_stopped():
                _vb_owner = None
                return
            if self.age(began) >= 1000:
                break
            wait(20, MSEC)
        _vb_owner = None
        raise RuntimeError('Behavior stop not confirmed')


def _vx_behavior_exec(source, limit_ms):
    global behaviors
    behaviors = _VxBehaviors(limit_ms, emit=True)
    context = behaviors  # Student variables cannot redirect cleanup ownership.
    context.begin()
    try:
        exec(source, globals())
        context.check()
        context.report('behavior_complete')
    finally:
        context.close()


def _vx_behavior_macro(args, action, job):
    context = _VxBehaviors(action['timeout'] * 1000, job)
    context.move_mmps = _vx_move_velocity[0] * (2 if _vx_move_velocity[1] == globals().get('PERCENT') else 1)
    context.turn_dps = _vx_turn_velocity[0] * (1.5 if _vx_turn_velocity[1] == globals().get('PERCENT') else 1)
    context.contact_mmps = context.move_mmps
    context.begin()
    try:
        if args[0].startswith('search-'):
            return {'found': context.find(args[1], LEFT if args[0] == 'search-left' else RIGHT)}
        if args[0] == 'collect':
            return context.collect(args[1])
        return context.approach(args[1])
    finally:
        context.close()
