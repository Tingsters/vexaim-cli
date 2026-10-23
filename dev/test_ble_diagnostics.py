"""Unattended failure paths, using no Bluetooth, vault or Windows changes."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from ble_diagnostics import CliClient, HostMonitor, Incomplete, Journal, Limits, LowBattery, PhaseFailed, Runner, official_ble_chunk


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Host:
    def __init__(self, resets=0, error=False):
        self.resets, self.error = resets, error

    def reset_count(self, since):
        return self.resets

    def check(self):
        if self.error:
            raise Incomplete('Monitor stopped')


class Client:
    def __init__(self, battery=95, error=None, cleanup=True):
        self.calls = []
        self.level, self.error, self.cleanup = battery, error, cleanup
        self.closed = False

    def start(self):
        self.calls.append('start')
        return {'keepalive': {'reconnect_count': 0}}

    def command(self, *args, **kwargs):
        self.calls.append(args)
        if self.error:
            raise self.error
        if args[0] == 'info':
            return {'robot_state': {'battery_pct': self.level, 'stopped': True}}
        if args[:2] == ('session', 'status'):
            return {'state': 'ready', 'keepalive': {'healthy': True, 'reconnect_count': 0}}
        if args[:2] == ('camera', 'observe'):
            return {'control_ready': True, 'path': 'local-frame.jpg', 'width': 640, 'height': 480}
        if args[:2] == ('screen', 'screenshot'):
            return {'control_ready': True, 'path': 'lcd.png', 'width': 240, 'height': 240}
        return {'ok': True}

    def close(self):
        self.closed = True
        return {'confirmed': self.cleanup}


class Unattended(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        self.journal = Journal(self.temp.name, self.clock)
        self.runner = Runner(self.journal, Host(), Limits(5400, self.clock), self.clock.sleep)
        self.output = redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def test_low_initial_battery_closes_the_owner_without_asking_for_help(self):
        client = Client(battery=13)
        with self.assertRaises(LowBattery):
            self.runner.cli_phase('initial', client, 10, initial=True)
        self.assertTrue(client.closed)
        self.assertEqual(self.runner.phases[-1]['outcome'], 'incomplete')
        self.assertEqual(client.calls, ['start', ('info',)])

    def test_battery_drop_during_a_phase_stops_and_closes(self):
        client = Client(battery=19)
        with self.assertRaises(LowBattery):
            self.runner.cli_phase('quiet', client, 300)
        self.assertTrue(client.closed)

    def test_unexpected_authentication_is_incomplete_not_a_pairing_retry(self):
        client = Client(error=Incomplete('Authentication needs attendance'))
        with self.assertRaises(Incomplete):
            self.runner.cli_phase('candidate', client, 10)
        self.assertTrue(client.closed)
        self.assertFalse(any('pair' in str(call) for call in client.calls))

    def test_two_adapter_resets_fail_a_short_phase(self):
        self.runner.host = Host(resets=2)
        client = Client()
        self.assertFalse(self.runner.cli_phase('comparison', client, 300))
        self.assertTrue(client.closed)

    def test_one_reset_fails_confirmation(self):
        self.runner.host = Host(resets=1)
        self.assertFalse(self.runner.cli_phase('confirmation', Client(), 300, confirm=True))

    def test_recovered_link_loss_still_fails_uninterrupted_acceptance(self):
        values = iter([{'healthy': True, 'reconnects': 0}, {'healthy': True, 'reconnects': 1}])
        with self.assertRaises(PhaseFailed):
            self.runner.wait(20, lambda: next(values), strict=True)

    def test_a_recovered_interruption_does_not_select_an_unstable_comparison_winner(self):
        samples = iter([{'healthy': True}, {'healthy': False}, {'healthy': True}])
        with self.assertRaisesRegex(PhaseFailed, 'recovered interruption'):
            self.runner.wait(6, lambda: next(samples))

    def test_recovery_budget_and_unresolved_end_are_failures(self):
        with self.assertRaisesRegex(PhaseFailed, '90 seconds'):
            self.runner.wait(100, lambda: {'healthy': False})
        with self.assertRaisesRegex(PhaseFailed, 'unresolved outage'):
            self.runner.wait(5, lambda: {'healthy': False})

    def test_whole_run_deadline_is_independent_of_phase_duration(self):
        self.runner.limits = Limits(5, self.clock)
        with self.assertRaises(Incomplete):
            self.runner.wait(300, lambda: {'healthy': True})
        self.assertLess(self.clock.now, 8)

    def test_monitor_failure_is_not_silently_a_pass(self):
        self.runner.host = Host(error=True)
        with self.assertRaises(Incomplete):
            self.runner.wait(10, lambda: {'healthy': True})

    def test_failed_phase_remains_failed_and_cleanup_failure_stops_next_phase(self):
        client = Client(error=PhaseFailed('transport lost'))
        self.assertFalse(self.runner.cli_phase('released', client, 10))
        self.assertEqual(self.runner.phases[-1]['outcome'], 'failed')
        with self.assertRaises(Incomplete):
            self.runner.cli_phase('candidate', Client(cleanup=False), 10)
        self.assertEqual(self.runner.phases[0]['outcome'], 'failed')

    def test_failed_measurement_remains_failed_when_cleanup_is_also_uncertain(self):
        with self.assertRaises(Incomplete):
            self.runner.cli_phase('unstable', Client(error=PhaseFailed('radio reset'), cleanup=False), 10)
        self.assertEqual(self.runner.phases[-1]['outcome'], 'failed')
        self.assertEqual(self.runner.phases[-1]['error'], 'radio reset')
        self.assertIn('cleanup_error', self.runner.phases[-1])

    def test_successful_confirmation_checks_camera_display_stop_and_closes(self):
        client = Client()
        self.assertTrue(self.runner.cli_phase('confirmation', client, 3, confirm=True))
        self.assertEqual(sum(call[:2] == ('camera', 'observe') for call in client.calls if isinstance(call, tuple)), 2)
        self.assertIn(('stop',), client.calls)
        self.assertTrue(client.closed)
        record = json.loads((Path(self.temp.name)/'result.json').read_text())
        self.assertEqual(record['human_interventions_after_setup'], 0)

    @unittest.skipUnless(os.name == 'nt', 'Windows process containment')
    def test_detached_test_child_is_terminated_when_runner_exits(self):
        import ctypes
        source = '''import sys,subprocess
sys.path.insert(0,sys.argv[1])
from ble_diagnostics import contain_children
job=contain_children()
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],
    stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
print(child.pid,flush=True)
'''
        result = subprocess.run([sys.executable, '-c', source, str(Path(__file__).parent)],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x100000, False, int(result.stdout.strip()))
        if handle:
            try:
                self.assertEqual(kernel.WaitForSingleObject(handle, 5000), 0)
            finally:
                kernel.CloseHandle(handle)

    def test_official_lazy_bundle_is_found_without_extracting_or_changing_it(self):
        body = b'(self.webpackChunkwebapp=[]).push([["local-ble-chunk"],{}]);'
        header = json.dumps({'files': {'vex-ble-device-manager.bundle.js': {'offset': '0', 'size': len(body)}}}).encode()
        archive = Path(self.temp.name)/'app.asar'
        source = struct.pack('<IIII', 4, len(header)+8, len(header)+4, len(header))+header+body
        archive.write_bytes(source)
        self.assertEqual(official_ble_chunk(archive), 'local-ble-chunk')
        self.assertEqual(archive.read_bytes(), source)
        self.assertEqual(set(Path(self.temp.name).iterdir()), {archive})

    def test_official_bundle_outside_archive_is_rejected(self):
        header = json.dumps({'files': {'vex-ble-device-manager.bundle.js': {'offset': '9999', 'size': 1}}}).encode()
        archive = Path(self.temp.name)/'bad.asar'
        archive.write_bytes(struct.pack('<IIII', 4, len(header)+8, len(header)+4, len(header))+header)
        with self.assertRaisesRegex(Incomplete, 'outside archive'):
            official_ble_chunk(archive)

    def test_a_stop_acknowledgment_does_not_prove_the_owner_exited(self):
        client = CliClient.__new__(CliClient)
        client.session = 'aim-fixture'
        client.call = Mock(side_effect=[{'state': 'ready'}, {'robot_state': {'stopped': True}},
            {'ok': True, 'stopped': True}])
        client.wait_owner_exit = Mock(return_value=False)
        result = client.close()
        self.assertFalse(result['confirmed'])
        self.assertFalse(result['owner_exited'])
        self.assertFalse(result['power_cleanup_verified'])
        client.wait_owner_exit.assert_called_once()

    def test_failed_startup_never_invents_a_named_close_command(self):
        client = CliClient.__new__(CliClient)
        client.session = None
        client.process_ids = Mock(return_value=[])
        client.wait_owner_exit = Mock(return_value=True)
        client.call = Mock(side_effect=AssertionError('no session command is valid'))
        self.assertTrue(client.close()['confirmed'])
        client.call.assert_not_called()

    def test_cleanup_waits_for_existing_owner_recovery_before_closing(self):
        client = CliClient.__new__(CliClient)
        client.session = 'aim-fixture'
        client.call = Mock(side_effect=[{'state': 'reconnecting'}, {'state': 'reconnecting'},
            {'state': 'ready'}, {'robot_state': {'stopped': True}}, {'ok': True, 'stopped': True}])
        client.wait_owner_exit = Mock(return_value=True)
        with patch('ble_diagnostics.time.monotonic', self.clock), patch('ble_diagnostics.time.sleep', self.clock.sleep):
            self.assertTrue(client.close()['confirmed'])
        self.assertEqual(self.clock.now, 4)
        commands = [c.args[2:] for c in client.call.call_args_list]
        self.assertEqual(commands[-2:], [('info',), ('session', 'close')])
        self.assertEqual(commands.count(('session', 'close')), 1)

    def test_a_running_but_stalled_windows_monitor_is_incomplete(self):
        monitor = HostMonitor.__new__(HostMonitor)
        monitor.process = Mock()
        monitor.process.poll.return_value = None
        monitor.rows = lambda: [{'utc': '2000-01-01T00:00:00Z'}]
        with self.assertRaisesRegex(Incomplete, 'stopped progressing'):
            monitor.check()

    def test_usb_data_connection_invalidates_a_bluetooth_only_run(self):
        monitor = HostMonitor.__new__(HostMonitor)
        monitor.process = Mock()
        monitor.process.poll.return_value = None
        monitor.require_bluetooth_only = True
        monitor.rows = lambda: [{'event': 'monitor_health', 'aim_usb_present': True}]
        with self.assertRaisesRegex(Incomplete, 'USB data connection'):
            monitor.check()

    def test_failed_startup_waits_for_its_owner_before_confirming_cleanup(self):
        client = CliClient.__new__(CliClient)
        client.session = None
        exited = False
        def wait():
            nonlocal exited
            exited = True
            return True
        client.wait_owner_exit = wait
        client.process_ids = lambda: [] if exited else [123]
        self.assertTrue(client.close()['confirmed'])


if __name__ == '__main__':
    unittest.main()
