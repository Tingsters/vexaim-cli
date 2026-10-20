# Starter ideas

On macOS/Linux, snippets run with `vexaim exec - <<'PY' ... PY`. On PowerShell, use `@'` and `'@ | & $vexaim exec -`
as shown in SKILL.md, or save the Python in a file and use `& $vexaim exec -f program.py`.
Items marked (tested) were run on a real AIM on Linux;
the rest use documented calls and have not been run yet: try them small first.

## Say hello (tested calls)
```python
robot.led.on(ALL_LEDS, GREEN)
robot.screen.show_emoji(HAPPY)
robot.sound.play(TADA)
wait(2, SECONDS)
robot.screen.hide_emoji()
robot.led.off(ALL_LEDS)
```

## Report status (tested)
```python
import json
print(json.dumps({"battery": robot.get_battery_level(),
                  "heading": robot.inertial.get_heading(),
                  "pitch": robot.inertial.get_pitch(),
                  "roll": robot.inertial.get_roll()}))
```

## Battery-aware light (tested calls)
```python
b = robot.get_battery_level()
robot.led.on(ALL_LEDS, GREEN if b > 50 else ORANGE if b > 20 else RED)
```

## A tiny, safe move (50 mm forward, then back; the forward half is tested)
```python
robot.move_for(50, 0, 40, MMPS)
wait(500, MSEC)
robot.move_for(50, 180, 40, MMPS)
print(robot.get_x_position(), robot.get_y_position())
```

## Look with the camera, then react (tested: snap; the reaction is up to you)
```
vexaim snap -o look.jpg      # then view look.jpg and decide
vexaim exec 'robot.screen.show_emoji(SURPRISED)'
```

## Let the robot's own vision look for a ball (documented, empty scene tested)
```python
robot.vision.tag_detection(True)
print(robot.has_sports_ball(), robot.vision.object_count())
```

## Run a loop for a while, safely
`exec` interrupts after `--timeout` seconds (default 30), so a loop can't run forever by accident:
```
vexaim exec --timeout 10 - <<'PY'
while True:
    robot.led.on(ALL_LEDS, BLUE); wait(300, MSEC)
    robot.led.on(ALL_LEDS, RED);  wait(300, MSEC)
PY
vexaim stop
```
