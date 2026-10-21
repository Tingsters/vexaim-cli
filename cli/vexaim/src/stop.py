# Stopping is asynchronous on AIM firmware. Send once, then poll confirmation.
def _va_stop():
    robot.stop_all_movement()
    stop_clock = Timer()
    while not robot.is_stopped():
        if stop_clock.time(MSEC) >= 1000:
            return False
        wait(20, MSEC)
    return True
