# Transient VEX AIM runtime. All motion uses the official drivetrain methods.
import json as _vx_json

try:
    _vx_jobs
except NameError:
    _vx_jobs = {}
    _vx_next = 0
    _vx_move_velocity = (80, None)
    _vx_turn_velocity = (30, None)
    _vx_colors = {}
    _vx_codes = {}
    _vx_watchers = {}
    _vx_onestick = None


def _vx_print(value):
    # Verified over AIM BLE: 256 bytes/35 ms loses long reports. Keep small
    # replies immediate, then pace larger ones below the console drain rate.
    text = _vx_json.dumps(value).encode('utf-8')
    if len(text) > 16384:
        raise RuntimeError('Result exceeds 16 KiB; shorten samples or request fewer objects')
    offset = 0
    while offset < len(text):
        end = min(offset + 128, len(text))
        # Count bytes, preserving UTF-8 characters at chunk boundaries.
        while end < len(text) and text[end] & 0xc0 == 0x80:
            end -= 1
        if offset:
            wait(100, MSEC)
        print(text[offset:end].decode('utf-8'), end='')
        offset = end
    print()


def _vx_resolve(path):
    global _vx_onestick
    parts = path.split('.')
    if parts[0] == 'robot':
        obj = robot
    elif parts[0] == 'onestick':
        if _vx_onestick is None:
            _vx_onestick = Onestick()
        obj = _vx_onestick
    elif parts[0].startswith('_vx_'):
        return globals()[parts[0]]
    else:
        raise ValueError('Unknown AIM API namespace')
    for name in parts[1:]:
        if not hasattr(obj, name):
            raise RuntimeError('unsupported_firmware: ' + path)
        obj = getattr(obj, name)
    return obj


def _vx_arg(value):
    if isinstance(value, list):
        return [_vx_arg(v) for v in value]
    if not isinstance(value, dict):
        return value
    if 'constant' in value:
        name = value['constant']
        if name in globals():
            return globals()[name]
        # Some AIM revisions expose vision selectors on the sensor object only.
        if name in ('ALL_AIOBJS', 'ALL_AIOBJECTS', 'ALL_OBJECTS', 'ALL_TAGS', 'ALL_COLORS', 'ALL_CODES') and hasattr(robot.vision, name):
            return getattr(robot.vision, name)
        # Constants share names between Color/TurnType/SoundType. Keep namespaces.
        for typename in ('Color', 'FontType', 'AxisType', 'OrientationType', 'AccelerationType', 'SensitivityType', 'KickType', 'TurnType', 'LightType', 'Emoji', 'EmojiLook', 'EmojiType', 'EmojiLookType', 'VoltageUnits', 'CurrentUnits', 'SoundType'):
            cls = globals().get(typename)
            if cls is not None and hasattr(cls, name):
                return getattr(cls, name)
        raise RuntimeError('unsupported_firmware: constant ' + name)
    if 'color' in value:
        return Color(value['color'])
    if 'rgb' in value:
        return Color(*value['rgb'])
    if value.get('target') == 'TAG':
        return Tagdesc(value['id'])
    if value.get('target') == 'COLOR':
        if value['id'] not in _vx_colors:
            raise RuntimeError('Define this color signature first')
        return _vx_colors[value['id']]
    if value.get('target') == 'CODE':
        if value['id'] not in _vx_codes:
            raise RuntimeError('Define this color code first')
        return _vx_codes[value['id']]
    raise ValueError('Unknown typed AIM argument')


def _vx_plain(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (tuple, list)):
        return [_vx_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _vx_plain(v) for k, v in value.items()}
    if hasattr(value, 'exists'):
        return {name: _vx_plain(getattr(value, name, None)) for name in ('exists', 'width', 'height', 'centerX', 'centerY', 'bearing', 'rotation', 'originX', 'originY', 'id', 'score', 'type')}
    return str(value)


def _vx_busy():
    return any(j['state'] == 'running' and j['resource'] == 'motion' for j in _vx_jobs.values()) or not robot.is_stopped()


def _vx_actions():
    return [_vx_public(j) for j in _vx_jobs.values()]


def _vx_public(job):
    return {k: v for k, v in job.items() if k not in ('thread', 'clock')}


def _vx_action_status(identifier):
    if identifier not in _vx_jobs:
        raise ValueError('Unknown action ID')
    return _vx_public(_vx_jobs[identifier])


def _vx_action_cancel(identifier):
    job = _vx_jobs.get(identifier)
    if job is None:
        raise ValueError('Unknown action ID')
    job['cancel_requested'] = True
    # Worker owns its cleanup. Do not kill a thread inside a motor API call.
    return _vx_public(job)


def _vx_action_wait(identifier, timeout_ms=30000):
    clock = Timer()
    while _vx_action_status(identifier)['state'] == 'running':
        if clock.time(MSEC) >= timeout_ms:
            raise RuntimeError('Action wait timed out; action not replayed')
        wait(20, MSEC)
    return _vx_action_status(identifier)


def _vx_capabilities(paths):
    result = {}
    for path in paths:
        try:
            _vx_resolve(path)
            result[path] = True
        except Exception:
            result[path] = False
    return {'model': 'VEX AIM', 'api_presence': result, 'hardware_verified': False,
            'note': 'Presence is not a behavioral test. Missing methods are never emulated.'}


def _vx_watch(source, duration_ms, job=None):
    # Registrations persist on some firmware. Reuse one gated callback per source.
    if source not in _vx_watchers:
        path = ('onestick.' + source[len('controller.'):]) if source.startswith('controller.') else 'robot.' + source
        fn = _vx_resolve(path)
        watcher = {'active': False, 'events': [], 'dropped': 0}
        _vx_watchers[source] = watcher
        def callback(*args):
            if watcher['active']:
                if len(watcher['events']) < 32:
                    watcher['events'].append({'source': source, 'data': _vx_plain(args)})
                else:
                    watcher['dropped'] += 1
        if source != 'timer.event':
            fn(callback)
        watcher['callback'] = callback
    watcher = _vx_watchers[source]
    watcher['events'] = []
    watcher['dropped'] = 0
    watcher['active'] = True
    clock = Timer()
    if source == 'timer.event':
        _vx_resolve('robot.timer.event')(watcher['callback'], max(1, duration_ms // 2))
    try:
        while clock.time(MSEC) < duration_ms:
            if job is not None and job['cancel_requested']:
                break
            wait(20, MSEC)
    finally:
        watcher['active'] = False
    return {'events': watcher['events'], 'dropped': watcher['dropped']}


def _vx_execute(a, job):
    kind = a['kind']
    args = [_vx_arg(v) for v in a['args']]
    method = a['method']
    fn = _vx_resolve(method)
    if kind == 'macro':
        return _vx_macro(args, a, job)
    if kind == 'color-description':
        desc = Colordesc(*args)
        fn(desc)
        _vx_colors[args[0]] = desc
        return {'color_index': args[0]}
    if kind == 'code-description':
        colors = [_vx_colors[n] for n in args[1]]
        desc = Codedesc(args[0], *colors)
        fn(desc)
        _vx_codes[args[0]] = desc
        return {'code_index': args[0]}
    if kind == 'print-at':
        return fn(args[0], x=args[1], y=args[2])
    if kind == 'events':
        return _vx_watch(args[0], a['duration_ms'], job)
    if method == 'robot.link.send_message':
        return fn(args[0], *args[1])
    if kind == 'actions':
        if method == '_vx_action_wait':
            return _vx_action_wait(args[0], a['timeout'] * 1000)
        return fn(*args)
    if method == 'robot.set_move_velocity':
        global _vx_move_velocity
        _vx_move_velocity = tuple(args)
    if method == 'robot.set_turn_velocity':
        global _vx_turn_velocity
        _vx_turn_velocity = tuple(args)
    if kind == 'calibrate':
        fn()
        wait(100, MSEC)
        while robot.inertial.is_calibrating():
            _vx_deadline(job, a)
            wait(20, MSEC)
        return {'calibrating': False}
    if kind in ('motion', 'continuous', 'experimental'):
        vector = method.endswith('move_with_vectors') or method.endswith('spin_wheels')
        if not vector:
            turn = '.turn' in method
            default = _vx_turn_velocity if turn else _vx_move_velocity
            speed = a.get('velocity') if a.get('velocity') is not None else default[0]
            units = _vx_arg({'constant': a['velocity_units']}) if a.get('velocity_units') else default[1]
            if units is None:
                units = DPS if turn else MMPS
            args.extend([speed, units])
            if kind == 'motion':
                args.append(False)
        fn(*args)
        wait(100, MSEC)
        while True:
            if job['cancel_requested']:
                return {'cancelled': True}
            _vx_deadline(job, a)
            elapsed = job['clock'].time(MSEC)
            if kind == 'motion' and not (robot.is_move_active() or robot.is_turn_active()):
                break
            if kind != 'motion' and elapsed >= a['duration_ms']:
                break
            wait(20, MSEC)
        return {'verification_source': 'robot_sensors', 'physical_accuracy_verified': False,
                'heading': robot.inertial.get_heading(), 'rotation': robot.inertial.get_rotation(),
                'x_mm': robot.get_x_position(), 'y_mm': robot.get_y_position()}
    if a.get('sample_ms'):
        samples = []
        while job['clock'].time(MSEC) < a['duration_ms']:
            if job['cancel_requested']:
                break
            _vx_deadline(job, a)
            if len(samples) >= 256:
                raise RuntimeError('Sampling limit 256 reached; choose a shorter duration or interval')
            samples.append({'robot_elapsed_ms': job['clock'].time(MSEC), 'value': _vx_plain(fn(*args))})
            wait(a['sample_ms'], MSEC)
        return {'samples': samples}
    # AIM MicroPython accepts one suffix; CPython's tuple overload raises here.
    if kind == 'vision' and (method.endswith('.get_data') or method.endswith('.take_snapshot')):
        return [obj for obj in fn(*args) if getattr(obj, 'exists', False)]
    return fn(*args)


def _vx_deadline(job, a):
    if job['clock'].time(MSEC) >= a['timeout'] * 1000:
        raise RuntimeError('Robot action deadline reached; not retried')


def _vx_macro(args, a, job):
    # Bounded adaptations of the official toolbox's 20 behavior sequences.
    # Macros are sequences in VEXcode, not fictitious firmware methods.
    behavior = args[0]
    if behavior in ('happy', 'sad', 'silly', 'angry', 'excited'):
        robot.screen.show_emoji(_vx_arg({'constant': behavior.upper()}))
        robot.sound.play(_vx_arg({'constant': 'ACT_' + behavior.upper()}), 50)
        robot.led.on(ALL_LEDS, _vx_arg({'constant': {'happy':'YELLOW','sad':'BLUE','silly':'PURPLE','angry':'RED','excited':'GREEN'}[behavior]}))
        for direction in (LEFT, RIGHT, LEFT):
            if job['cancel_requested']:
                break
            _vx_deadline(job, a)
            robot.turn_for(direction, 8, 30, DPS, False)
            wait(100, MSEC)
            while robot.is_turn_active():
                _vx_deadline(job, a)
                if job['cancel_requested']:
                    return {'cancelled': True}
                wait(20, MSEC)
        return {'behavior': behavior}
    target = args[1]
    while True:
        _vx_deadline(job, a)
        if job['cancel_requested']:
            return {'cancelled': True}
        objects = [o for o in robot.vision.get_data(target, 8) if getattr(o, 'exists', False)]
        if behavior.startswith('search-'):
            if objects:
                return {'found': _vx_plain(objects[0])}
            robot.turn(LEFT if behavior == 'search-left' else RIGHT, 30, DPS)
        elif objects:
            obj = objects[0]
            # Native detection coordinates, not camera JPEG coordinates.
            if behavior == 'collect':
                collected = (
                    (target == globals().get('SPORTS_BALL') and robot.vision.has_sports_ball()) or
                    (target == globals().get('ORANGE_BARREL') and robot.vision.has_orange_barrel()) or
                    (target == globals().get('BLUE_BARREL') and robot.vision.has_blue_barrel()))
                if collected:
                    return {'collected': True}
            if behavior == 'approach' and obj.width >= 100:
                return {'approached': _vx_plain(obj)}
            if abs(obj.centerX - 160) > 20:
                robot.turn(LEFT if obj.centerX < 160 else RIGHT, 20, DPS)
            else:
                robot.move_at(0, 60, MMPS)
        else:
            robot.stop_all_movement()
        wait(50, MSEC)


def _vx_worker(a, job):
    terminal = 'failed'
    try:
        job['value'] = None if job['cancel_requested'] else _vx_plain(_vx_execute(a, job))
        terminal = 'cancelled' if job['cancel_requested'] else 'completed'
    except Exception as error:
        job['error'] = str(error)
    finally:
        if job['resource'] == 'motion':
            try:
                robot.stop_all_movement()
                clock = Timer()
                while not robot.is_stopped() and clock.time(MSEC) < 1000:
                    wait(20, MSEC)
                job['stopped_confirmed'] = robot.is_stopped()
                if not job['stopped_confirmed']:
                    terminal = 'failed'
                    job['error'] = 'Stop not confirmed; check physical robot'
            except Exception as error:
                terminal = 'failed'
                job['error'] = str(error)
        job['elapsed_ms'] = job['clock'].time(MSEC)
        # Completion is published only after stop/cleanup, never while settling.
        job['state'] = terminal


def _vx_dispatch(a):
    global _vx_next
    moving = a['kind'] in ('motion', 'continuous', 'experimental', 'macro')
    if (moving or a['kind'] in ('reference', 'calibrate')) and _vx_busy():
        return {'rejected': True, 'error': 'Conflicting motion/reference operation; no command queued'}
    if moving and robot.inertial.is_calibrating():
        raise RuntimeError('Inertial sensor calibrating; no movement sent')
    # Resolve before reserving a resource; unsupported firmware cannot start a job.
    try:
        _vx_resolve(a['method'])
        for value in a['args']:
            _vx_arg(value)
    except Exception as error:
        return {'rejected': True, 'error': str(error)}
    if a['kind'] == 'stop':
        _vx_cancel_all()
        robot.stop_all_movement()
        clock = Timer()
        while not robot.is_stopped() and clock.time(MSEC) < 1000:
            wait(20, MSEC)
        if not robot.is_stopped():
            raise RuntimeError('Stopped state not confirmed')
        return {'stopped': True}
    if moving or a['no_wait']:
        # Retain only a bounded history. Active jobs are never discarded.
        for key in list(_vx_jobs):
            if len(_vx_jobs) < 32:
                break
            if _vx_jobs[key]['state'] != 'running':
                del _vx_jobs[key]
        if len(_vx_jobs) >= 32:
            raise RuntimeError('Action capacity reached')
        _vx_next += 1
        identifier = 'action-' + str(_vx_next)
        job = {'id': identifier, 'command': a['command'], 'state': 'running',
               'resource': 'motion' if moving else 'device', 'cancel_requested': False, 'clock': Timer()}
        _vx_jobs[identifier] = job
        try:
            job['thread'] = Thread(_vx_worker, (a, job))
        except Exception as error:
            job['state'] = 'failed'
            job['error'] = str(error)
            raise
        return {'action': _vx_public(job)}
    job = {'clock': Timer(), 'cancel_requested': False, 'resource': 'device'}
    return {'value': _vx_plain(_vx_execute(a, job))}


def _vx_cancel_all():
    for job in _vx_jobs.values():
        if job['state'] == 'running':
            job['cancel_requested'] = True


_vx_runtime_version = 1
