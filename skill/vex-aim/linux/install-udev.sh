#!/bin/sh
# Installs the VEX AIM udev rule (needs sudo once). Safe to re-run. Unplug/replug the robot afterwards.
set -e
here="$(cd "$(dirname "$0")" && pwd)"
sudo install -m 644 "$here/99-vex-aim.rules" /etc/udev/rules.d/99-vex-aim.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=tty --subsystem-match=usb --subsystem-match=video4linux
echo "Installed. Unplug and replug the AIM USB cable."
