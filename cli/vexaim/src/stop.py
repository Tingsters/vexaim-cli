# Stopping is asynchronous on AIM firmware. Send once, then poll confirmation.
def _va_stop():
    robot.stop_all_movement()
    stop_started = robot.timer.time(MSEC)
    while not robot.is_stopped():
        if robot.timer.time(MSEC) - stop_started >= 1000:
            return False
        wait(20, MSEC)
    return True
