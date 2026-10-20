# Transient REPL helpers, not an uploaded/stored robot program.
import json as _va_json


def _va_state():
    return {
        'battery_pct': robot.get_battery_level(),
        'heading': robot.inertial.get_heading(),
        'rotation': robot.inertial.get_rotation(),
        'x_mm': robot.get_x_position(),
        'y_mm': robot.get_y_position(),
        'stopped': robot.is_stopped(),
        'imu_calibrating': robot.inertial.is_calibrating(),
    }


def _va_motion(kind, value, angle, speed):
    # Validate on the robot too: arbitrary exec callers can invoke this function.
    if kind not in ('turn', 'move'):
        raise ValueError('Unknown movement')
    if not (0.1 <= abs(value) <= (360 if kind == 'turn' else 500)):
        raise ValueError('Movement exceeds workshop helper limits')
    if not ((30 <= speed <= 90) if kind == 'turn' else (40 <= speed <= 100)):
        raise ValueError('Speed exceeds workshop helper limits')
    if not (-360 <= angle <= 360) or (kind == 'move' and value < 0):
        raise ValueError('Invalid movement angle or distance')
    before = _va_state()
    if not before['stopped']:
        raise RuntimeError('Robot already moving; action not started')
    if before['imu_calibrating']:
        raise RuntimeError('Robot gyro initializing; action not started')
    started = robot.timer.time(MSEC)
    deadline_ms = min(20000, max(4000, int(abs(value) / speed * 1500 + 2000)))
    try:
        if kind == 'turn':
            robot.turn_for(LEFT if value < 0 else RIGHT, abs(value), speed, DPS, False)
        else:
            robot.move_for(value, angle, speed, MMPS, False)
        print('__VEXAIM_EVENT__' + _va_json.dumps({
            'event': 'started', 'kind': kind, 'robot_ms': robot.timer.time(MSEC)}))
        wait(100, MSEC)
        while robot.is_turn_active() or robot.is_move_active():
            if robot.timer.time(MSEC) - started >= deadline_ms:
                raise RuntimeError('Movement deadline reached; stopped without retry')
            wait(20, MSEC)
    finally:
        robot.stop_all_movement()
        wait(100, MSEC)
    after = _va_state()
    delta = after['rotation'] - before['rotation']
    result = {
        'kind': kind, 'requested': value, 'speed': speed,
        'rotation_delta_deg': round(delta, 2),
        'heading_before': before['heading'], 'heading_after': after['heading'],
        'x_before_mm': before['x_mm'], 'y_before_mm': before['y_mm'],
        'x_after_mm': after['x_mm'], 'y_after_mm': after['y_mm'],
        'motion_ms': robot.timer.time(MSEC) - started,
        'stopped': after['stopped'], 'battery_pct': after['battery_pct'],
        'verification_source': 'robot_sensors', 'physical_accuracy_verified': False,
    }
    print(_va_json.dumps(result))
    if not after['stopped'] or (kind == 'turn' and abs(delta - value) > 5):
        raise RuntimeError('Movement sensor check failed; stopped without retry')


_va_helpers_version = 1
