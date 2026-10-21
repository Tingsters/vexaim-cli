"""Local Windows attention cue for stationary developer investigations.

Rehearse while the operator is present, then confirm that they heard the cue.
Requests checkpoint one action before sounding and wait for an explicit reply.
This helper never connects to the robot or changes the computer's volume.
"""

import argparse
import io
import json
import math
import os
import struct
import time
import uuid
import wave
from pathlib import Path


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def play_chime():
    if os.name != "nt":
        raise RuntimeError("This attention cue requires a Windows speaker")
    import winsound

    samples = []
    rate = 22050
    for frequency in (660, 880, 660):
        for index in range(int(rate * 0.18)):
            fade = min(1, index / 110, (rate * 0.18 - index) / 110)
            samples.append(
                int(7000 * fade * math.sin(2 * math.pi * frequency * index / rate))
            )
        samples.extend([0] * int(rate * 0.12))
    output = io.BytesIO()
    with wave.open(output, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(struct.pack("<" + "h" * len(samples), *samples))
    winsound.PlaySound(output.getvalue(), winsound.SND_MEMORY | winsound.SND_NODEFAULT)


class Attention:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.rehearsal = self.directory / "rehearsal.json"
        self.pending = self.directory / "pending.json"

    def rehearse(self):
        record = {
            "state": "rehearsing",
            "heard_confirmed": False,
            "created_at": time.time(),
        }
        write_json(self.rehearsal, record)
        try:
            play_chime()
        except Exception as error:
            record.update(state="incomplete", audio_error=str(error))
            write_json(self.rehearsal, record)
            raise
        return record

    def confirm(self):
        record = json.loads(self.rehearsal.read_text(encoding="utf-8"))
        if record["state"] != "rehearsing":
            raise RuntimeError(
                "Rehearse successfully before confirming the operator heard it"
            )
        record.update(state="ready", heard_confirmed=True, confirmed_at=time.time())
        write_json(self.rehearsal, record)
        return record

    def reply(self, request_id, cancel=False):
        record = json.loads(self.pending.read_text(encoding="utf-8"))
        if (
            record["request_id"] != request_id
            or record["state"] != "awaiting_user"
            or time.time() >= record["expires_at"]
        ):
            raise RuntimeError("That attention request is no longer awaiting a reply")
        record.update(
            state="cancelled" if cancel else "acknowledged", replied_at=time.time()
        )
        write_json(self.directory / (request_id + ".reply.json"), record)
        return record

    def request(self, action, reason, wait_seconds=600):
        rehearsal = json.loads(self.rehearsal.read_text(encoding="utf-8"))
        if rehearsal.get("heard_confirmed") is not True:
            raise RuntimeError(
                "Confirm the operator heard the rehearsal before unattended work"
            )
        if self.pending.exists():
            previous = json.loads(self.pending.read_text(encoding="utf-8"))
            if previous["state"] == "awaiting_user":
                raise RuntimeError("Resolve the existing attention request first")
        if not 1 <= wait_seconds <= 600:
            raise ValueError("Attention waits must be between 1 and 600 seconds")
        created = time.time()
        record = {
            "request_id": str(uuid.uuid4()),
            "state": "awaiting_user",
            "action": action,
            "reason": reason,
            "created_at": created,
            "expires_at": created + wait_seconds,
            "wait_seconds": wait_seconds,
            "alerts": [],
            "instruction": "Return to the computer for this action; no movement is authorized.",
        }

        def save():
            write_json(self.pending, record)
            write_json(self.directory / (record["request_id"] + ".json"), record)

        def read_reply():
            path = self.directory / (record["request_id"] + ".reply.json")
            return (
                json.loads(path.read_text(encoding="utf-8"))
                if path.exists()
                else record
            )

        save()
        print(json.dumps(record), flush=True)
        started = time.monotonic()
        next_alert = 0
        try:
            while time.monotonic() - started < wait_seconds:
                reply = read_reply()
                if reply["request_id"] != record["request_id"]:
                    raise RuntimeError("Pending attention request changed unexpectedly")
                if reply["state"] in ("acknowledged", "cancelled"):
                    record.update(state=reply["state"], replied_at=reply["replied_at"])
                    save()
                    return record
                elapsed = time.monotonic() - started
                if next_alert < 3 and elapsed >= next_alert * 60:
                    # The pending action is durable before any sound is played.
                    play_chime()
                    record["alerts"].append({"elapsed_s": time.monotonic() - started})
                    next_alert += 1
                    # Preserve a reply that arrived during synchronous playback.
                    reply = read_reply()
                    if reply["state"] in ("acknowledged", "cancelled"):
                        record.update(state=reply["state"], replied_at=reply["replied_at"])
                        save()
                        return record
                    save()
                time.sleep(
                    min(0.5, max(0, wait_seconds - (time.monotonic() - started)))
                )
            record.update(
                state="incomplete", reason_wait_ended="operator did not reply"
            )
        except KeyboardInterrupt:
            record.update(state="cancelled", reason_wait_ended="request interrupted")
        except (OSError, RuntimeError, ValueError) as error:
            record.update(state="incomplete", attention_error=str(error))
        save()
        return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(".vexaim/attention"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("rehearse")
    commands.add_parser("confirm-heard")
    request = commands.add_parser("request")
    request.add_argument("--action", required=True)
    request.add_argument("--reason", required=True)
    request.add_argument("--wait-seconds", type=int, default=600)
    reply = commands.add_parser("reply")
    reply.add_argument("request_id")
    reply.add_argument("--cancel", action="store_true")
    args = parser.parse_args()
    helper = Attention(args.directory)
    try:
        if args.command == "rehearse":
            result = helper.rehearse()
        elif args.command == "confirm-heard":
            result = helper.confirm()
        elif args.command == "reply":
            result = helper.reply(args.request_id, args.cancel)
        else:
            result = helper.request(args.action, args.reason, args.wait_seconds)
        print(json.dumps(result), flush=True)
        return 2 if result["state"] in ("cancelled", "incomplete") else 0
    except (OSError, RuntimeError, ValueError) as error:
        print(json.dumps({"state": "incomplete", "error": str(error)}), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
