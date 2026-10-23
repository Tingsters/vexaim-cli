"""Explicit stationary persistent-session acceptance; no wheels or kicker run.

Requires a charged, powered AIM, USB unplugged, VEXcode closed and prior pairing.
Local evidence only. Cached polling does not renew ordinary client idle time.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time


def run(tool, name, output, duration=3600, quiet=2100):
    output.mkdir(parents=True, exist_ok=True)
    began = time.monotonic()
    evidence = output / 'events.jsonl'

    def record(event, **data):
        value = dict(event=event, elapsed_s=round(time.monotonic()-began, 2), **data)
        with evidence.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(value)+'\n')
        print(json.dumps(value), flush=True)

    def call(*args, timeout=120):
        response = subprocess.run([str(tool), '--json', *args], capture_output=True,
                                  text=True, timeout=timeout)
        values = [json.loads(line) for line in response.stdout.splitlines() if line.startswith('{')]
        if not values:
            raise RuntimeError('CLI returned no structured result: '+response.stderr[:300])
        value = values[-1]
        if response.returncode or value.get('ok') is not True:
            raise RuntimeError(str(value.get('error', value)))
        return value

    record('begin', tool_sha256=hashlib.sha256(tool.read_bytes()).hexdigest(), duration_s=duration, quiet_s=quiet)
    owner = call('--name', name, 'session', 'start', '--persistent', '--takeover')
    session = owner['session']
    def command(*args): return call('--session', session, *args)
    command('exec', '--timeout', '15', 'robot.screen.show_emoji(Emoji.HAPPY, EmojiLook.LOOK_FORWARD); print(robot.get_battery_level())')
    command('camera', 'observe', '--output-dir', str(output / 'initial-camera'))
    quiet_began = time.monotonic()
    outage = None
    after_quiet = False
    last_print = 0
    while time.monotonic()-quiet_began < duration:
        elapsed = time.monotonic()-quiet_began
        status = command('session', 'status')
        healthy = status.get('state') == 'ready' and status.get('keepalive', {}).get('healthy') is True
        if not healthy:
            if outage is None:
                outage = time.monotonic()
                record('outage', state=status.get('state'), error=status.get('keepalive_error'),
                       disconnect_error=status.get('keepalive', {}).get('last_disconnect_error'))
            if status.get('state') == 'auth_required':
                raise RuntimeError('Authentication changed; owner correctly yielded, endurance not passed')
            if time.monotonic()-outage > 90:
                raise RuntimeError('Connection failed to recover within 90 seconds')
        elif outage is not None:
            record('recovered', outage_s=round(time.monotonic()-outage, 2))
            outage = None
        if elapsed-last_print >= 60:
            health = status.get('keepalive', {})
            record('cached_health', state=status.get('state'), healthy=healthy,
                   polls=health.get('confirmed_polls'), power=health.get('power', {}).get('active'),
                   reconnect_count=health.get('reconnect_count'), disconnect_error=health.get('last_disconnect_error'))
            last_print = elapsed
        if elapsed >= quiet and healthy and not after_quiet:
            info = command('info')
            record('after_quiet_live', robot_state=info.get('robot_state'))
            if info['robot_state']['battery_pct'] < 15:
                raise RuntimeError('Battery too low to complete an unconfounded endurance test')
            command('camera', 'observe', '--output-dir', str(output / 'after-quiet-camera'))
            command('exec', '--timeout', '15', "robot.screen.clear_screen(BLUE); robot.screen.set_pen_color(WHITE); robot.screen.draw_circle(120,120,45); print('stationary display complete')")
            command('stop')
            command('info')
            after_quiet = True
        time.sleep(5)
    info = command('info')
    command('camera', 'observe', '--output-dir', str(output / 'final-camera'))
    record('passed', robot_state=info.get('robot_state'), persistent_owner_retained=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool', required=True, type=Path)
    parser.add_argument('--name', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--duration', type=int, default=3600)
    parser.add_argument('--quiet', type=int, default=2100)
    args = parser.parse_args()
    if args.duration <= args.quiet or args.quiet < 0:
        parser.error('duration must exceed the quiet interval')
    try:
        run(args.tool.resolve(), args.name, args.output.resolve(), args.duration, args.quiet)
    except Exception as error:
        print(json.dumps(dict(event='failed', error=str(error))), flush=True)
        raise
