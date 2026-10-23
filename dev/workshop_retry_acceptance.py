"""Explicit stationary CLI acceptance: replace a running display, then camera.

No wheels, kicker, uploads or credential reads. Start with no existing owner.
Leaves the persistent owner connected. Python is a maintainer tool only.
"""
import argparse
import json
from pathlib import Path
import queue
import subprocess
import threading
import time


def run(tool, name, output):
    output.mkdir(parents=True, exist_ok=True)
    results = []

    def call(*args):
        result = subprocess.run([str(tool), '--json', *args], capture_output=True,
                                text=True, timeout=120)
        events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
        if not events or result.returncode or events[-1].get('ok') is not True:
            raise RuntimeError(events[-1] if events else result.stderr[:300])
        return events[-1]

    owner = call('--name', name, 'session', 'start', '--persistent', '--takeover')
    session = owner['session']
    old = subprocess.Popen([str(tool), '--json', '--session', session, 'exec', '--timeout', '30',
        'robot.screen.show_emoji(Emoji.HAPPY, EmojiLook.LOOK_FORWARD); wait(20, SECONDS); print("old activity finished")'],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    pending = queue.Queue()

    def collect():
        for line in old.stdout:
            if line.startswith('{'):
                event = json.loads(line)
                results.append(event)
                pending.put(event)
        pending.put(None)

    reader = threading.Thread(target=collect, daemon=True)
    reader.start()
    try:
        deadline = time.monotonic() + 60
        while True:
            event = pending.get(timeout=max(.1, deadline-time.monotonic()))
            if event is None or event.get('event') == 'result':
                raise RuntimeError('Old activity ended before the replacement request')
            if event.get('phase') == 'running':
                break
        began = time.monotonic()
        replaced = call('--name', name, 'session', 'start', '--persistent', '--takeover')
        replace_ms = round((time.monotonic()-began)*1000)
        old.wait(timeout=10)
        reader.join(timeout=2)
        assert replaced['session'] == session
        assert replaced['state'] == 'ready' and replaced['needs_check'] is False, replaced
        assert results[-1]['ok'] is False and results[-1]['stopped_confirmed'] is True, results[-1]
        fresh = call('--session', session, 'info')
        assert fresh['robot_state']['stopped'] is True, fresh
        call('--session', session, 'exec', '--timeout', '15',
             'robot.screen.show_emoji(Emoji.HAPPY, EmojiLook.LOOK_FORWARD); print("fresh activity complete")')
        photograph = call('--session', session, 'camera', 'observe', '--output-dir', str(output / 'camera'))
        evidence = dict(event='stationary_retry_passed', session=session, takeover_ms=replace_ms,
                        robot_state=fresh['robot_state'], camera=photograph,
                        persistent_owner_retained=True, human_interventions=0)
        (output / 'result.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
        print(json.dumps(evidence), flush=True)
    finally:
        if old.poll() is None:
            old.terminate()
            old.wait(timeout=10)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool', required=True, type=Path)
    parser.add_argument('--name', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--stationary-ready', action='store_true', required=True)
    args = parser.parse_args()
    run(args.tool.resolve(), args.name, args.output.resolve())
