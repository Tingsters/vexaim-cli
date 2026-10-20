# AIM Python API as exposed by the robot (generated from `dir()` on the real robot, FW 1.0.0-beta.2)

Names only; the firmware exposes no signatures. Signatures below the lists are from VEX's public AIM docs
(https://api.vex.com/aim/home/python/) and are marked with what has actually been run on this robot.

Preamble (vexaim exec adds it automatically): `from vex import *`, `from vex_globals import *`, `robot = Robot()`.

## `robot` and its parts

**robot**: battery, get_battery_level, get_x_position, get_y_position, has_any_barrel, has_blue_barrel,
has_orange_barrel, has_sports_ball, inertial, is_move_active, is_stopped, is_turn_active, kicker,
led, move_at, move_for, move_with_vectors, screen, set_move_velocity, set_turn_velocity,
set_xy_position, sound, spin_wheels, stop_all_movement, stop_program, timer, turn, turn_for,
turn_to, vision

**robot.led**: get_light_color, off, on, set_light_color

**robot.vision**: index, set, AI_OBJECT, ALL_AIOBJECTS, ALL_AIOBJS, ALL_CODES, ALL_COLORS, ALL_OBJECTS, ALL_TAGS,
CODE_OBJECT, COLOR_OBJECT, FLG_COLORMERGE, FLG_OVLENABLE, TAG_16H5, TAG_25H9, TAG_36H11,
TAG_CIRCLE21H7, TAG_OBJECT, code_description, color_control, color_description, color_detection,
debug_get, get_data, has_any_barrel, has_blue_barrel, has_orange_barrel, has_sports_ball, installed,
largest_object, model_detection, object_count, reset, set_tag_family, start_awb, status_overlay,
tag_detection, take_snapshot, usb_overlay

**robot.sound**: stop, is_active, play, play_file, play_note

**robot.screen**: print, clear_line, clear_row, clear_screen, column, draw_circle, draw_image_from_file, draw_line,
draw_pixel, draw_rectangle, get_column, get_row, get_string_height, get_string_width, hide_aivision,
hide_emoji, layer, new_line, next_row, pressed, pressing, print_at, released, row, set_clip_region,
set_cursor, set_fill_color, set_font, set_origin, set_pen_color, set_pen_width, show_aivision,
show_emoji, show_file, x_position, y_position

**robot.timer**: clear, value, dump, event, reset, system, system_high_res, time

**robot.kicker**: index, kick, place, push, status

**robot.battery**: current, level, status, voltage

**robot.inertial**: index, acceleration, calibrate, changed, collision, collision_data, crashed, get_acceleration,
get_heading, get_pitch, get_roll, get_rotation, get_turn_rate, get_turn_type, get_yaw, gyro_rate,
heading, installed, is_calibrating, orientation, reset_heading, reset_rotation, rotation,
set_crash_sensitivity, set_heading, set_rotation, set_turn_type, shake


## Constants (`from vex_globals import *`)

**LEDs**: ALL_LEDS, LED1, LED2, LED3, LED4, LED5, LED6, LED_ALL

**Colors**: BLACK, BLUE, CYAN, GREEN, ORANGE, PURPLE, RED, TRANSPARENT, WHITE, YELLOW

**Emoji**: AFFECTIONATE, AMAZED, ANGRY, ANNOYED, BORED, CALM, CHEERFUL, CONFIDENT, CONFUSED, DETERMINED,
DISAPPOINTED, DISGUST, EMBARRASSED, EXCITED, FEAR, FRUSTRATED, HAPPY, JEALOUS, LAUGHING, LOVED,
NERVOUS, OPTIMISTIC, PROUD, QUIET, SAD, SHOCKED, SHY, SICK, SILLY, STRESSED, STRONG, SURPRISED,
THINKING, THRILLED, TIRED, WORRIED

**Sounds**: ACT_ANGRY, ACT_EXCITED, ACT_HAPPY, ACT_SAD, ACT_SILLY, BLINKER, BRAKES, CHEER, CHIRP, COMPLETE,
CRASH, DETECTED, DOORBELL, FAIL, FLOURISH, HUAH, LOOPING, OBSTACLE, PAUSE, PICKUP, RECEIVE, RESUME,
SEND, SENSING, SPARKLE, TADA

**Units/directions**: DOWNWARD, FORWARD, HARD, LOOK_FORWARD, LOOK_LEFT, LOOK_RIGHT, MEDIUM, PITCH, RIGHTWARD, ROLL, SOFT,
X_AXIS, YAW, Y_AXIS, Z_AXIS

**Vision/objects**: AIM_ROBOT, ALL_CARGO, ALL_COLORS, ALL_TAGS, ALL_VISION, BLUE_BARREL, ORANGE_BARREL, SPORTS_BALL,
TAG0, TAG1, TAG2, TAG3, TAG4

**Other**: MONO12, MONO15, MONO20, MONO24, MONO30, MONO36, MONO40, MONO60, MOVE_FORWARD, MOVE_REVERSE, PROP20,
PROP24, PROP30, PROP36, PROP40, PROP60, TURN_LEFT, TURN_RIGHT


## Documented signatures and hardware status
Legend: RAN = executed on the test robot without error; DOC = from VEX docs, not yet run here.

| Call | Notes | Status |
|---|---|---|
| `robot.get_battery_level()` | 0-100 % | RAN |
| `robot.led.on(LED, COLOR)` / `robot.led.off(LED)` | LED = `ALL_LEDS`, `LED1`..`LED6` or a tuple | RAN (no error; light not visually confirmed) |
| `robot.screen.show_emoji(EMOJI[, LOOK_*])` / `hide_emoji()` | | RAN (no error; screen not visually confirmed) |
| `robot.sound.play(SOUND[, volume])`, `play_note("D6", ms[, volume])`, `stop()`, `is_active()` | non-blocking | RAN (no error; audio not confirmed) |
| `robot.move_for(distance_mm, angle_deg, velocity, units)` | angle 0 = forward, 90 = right; blocks until done | RAN: `move_for(50, 0, 40, MMPS)` moved ~49 mm |
| `robot.move_at(angle[, velocity, units])`, `move_with_vectors(fwd, right, rot)`, `spin_wheels(...)` | continuous | DOC |
| `robot.turn_for(LEFT/RIGHT, degrees[, velocity, units])`, `turn_to(heading)`, `turn(dir)` | | DOC |
| `robot.stop_all_movement()` | | RAN (via `vexaim stop`) |
| `robot.get_x_position()`, `get_y_position()` | mm; see position-frame note in SKILL.md | RAN |
| `robot.is_stopped()`, `is_move_active()`, `is_turn_active()` | | RAN (is_stopped) |
| `robot.inertial.get_heading()`, `get_rotation()`, `get_pitch()`, `get_roll()`, `get_yaw()` | degrees | RAN (heading, rotation, pitch, roll) |
| `robot.kicker.kick(SOFT/MEDIUM/HARD)`, `place()`, `push()` | try SOFT first | `kick(SOFT)` RAN, human confirmed it moved; the rest DOC |
| `robot.vision.take_snapshot(...)`, `largest_object()`, `object_count()`; `robot.has_sports_ball()` etc. | on-robot detection | RAN (returned empty: nothing in view) |
| `wait(n, SECONDS/MSEC)`, `Thread(fn)`, `robot.timer.time(MSEC)` | | RAN |
| `robot.get_name()` | **does not exist** on this firmware despite the docs | RAN (AttributeError) |
