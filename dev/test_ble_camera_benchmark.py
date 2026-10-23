"""Bounded unattended runner regressions; no robot, vault or packages needed."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from ble_camera_benchmark import CameraClient, CameraLimits, Investigation, timing_feasible, saved_setup_code
from ble_diagnostics import Incomplete, Journal


class Host:
    def check(self): pass
    def reset_count(self,since): return 0


class Client:
    battery=95
    duration=1000
    cleanup=True
    def __init__(self,*args,**kwargs): self.calls=[];self.closed=False
    def start(self): self.calls.append('start')
    def command(self,*args,**kwargs): return {'robot_state':{'stopped':True,'battery_pct':self.battery}}
    def capture(self,index): self.calls.append(('capture',index));return {'call_ms':self.duration}
    def traces(self): return [{'outcome':'passed'}]
    def close(self): self.closed=True;return {'confirmed':self.cleanup}


class CameraBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.log=Journal(self.temp.name)
        self.runner=Investigation(SimpleNamespace(name='SIMULATED'),self.log,Host(),CameraLimits(840))
        self.output=redirect_stdout(io.StringIO());self.output.__enter__();self.addCleanup(self.output.__exit__,None,None,None)

    def test_weak_initial_charge_ends_the_phase_and_closes_without_a_camera(self):
        client=Client();client.battery=13
        with patch('ble_camera_benchmark.CameraClient',return_value=client):
            with self.assertRaises(Incomplete): self.runner.phase('setup','fake',initial=True)
        self.assertTrue(client.closed);self.assertEqual(client.calls,['start'])

    def test_one_frame_already_slower_than_goal_does_not_wait_for_two_more(self):
        client=Client();client.duration=16000
        with patch('ble_camera_benchmark.CameraClient',return_value=client):
            phase=self.runner.phase('candidate','fake',mode='operation',count=3)
        self.assertEqual(client.calls,['start',('capture',0)])
        self.assertIn('shortened',phase);self.assertTrue(client.closed)

    def test_missing_instrumentation_is_a_failed_comparison(self):
        client=Client();client.traces=lambda:[]
        with patch('ble_camera_benchmark.CameraClient',return_value=client):
            with self.assertRaisesRegex(Incomplete,'instrumentation'): self.runner.phase('candidate','fake',mode='operation')
        self.assertEqual(self.runner.phases[-1]['outcome'],'failed')

    def test_failed_cleanup_blocks_followup_connections(self):
        client=Client();client.cleanup=False
        with patch('ble_camera_benchmark.CameraClient',return_value=client):
            with self.assertRaisesRegex(Incomplete,'Cleanup uncertain'): self.runner.phase('candidate','fake')
        self.assertEqual(self.runner.phases[-1]['outcome'],'incomplete')

    def test_capture_failure_is_not_replayed(self):
        client=Client()
        def fail(index): client.calls.append(('capture',index));raise RuntimeError('interrupted')
        client.capture=fail
        with patch('ble_camera_benchmark.CameraClient',return_value=client):
            with self.assertRaisesRegex(RuntimeError,'interrupted'): self.runner.phase('candidate','fake',count=3)
        self.assertEqual(client.calls,['start',('capture',0)]);self.assertTrue(client.closed)

    def test_radio_reset_rejects_a_complete_image(self):
        client=Client();self.runner.host.reset_count=lambda _:1
        with patch('ble_camera_benchmark.CameraClient',return_value=client):
            with self.assertRaisesRegex(Incomplete,'Radio reset'): self.runner.phase('candidate','fake')
        self.assertEqual(self.runner.phases[-1]['outcome'],'failed')

    def test_optimistic_gate_does_not_hide_inference_or_search_coverage(self):
        slow=timing_feasible(5000,0,120)
        self.assertFalse(slow['feasible']);self.assertGreater(slow['optimistic_search_ms'],15000)
        self.assertFalse(timing_feasible(2000,1000,60)['feasible'])
        self.assertTrue(timing_feasible(500,500,60)['feasible'])

    def test_running_battery_floor_and_total_deadline_are_finite(self):
        limits=CameraLimits(10,clock=lambda:0)
        with self.assertRaises(Incomplete): limits.check(24)
        limits.clock=lambda:10
        with self.assertRaises(Incomplete): limits.check(100)

    def test_reused_workshop_owner_is_not_misreported_as_the_candidate_or_closed(self):
        client=CameraClient('fake-tool','SIMULATED',CameraLimits(840),self.log,Path(self.temp.name)/'phase')
        def reused():
            client.session='existing-workshop';client.owner_pids=[]
            return {'session':client.session}
        with patch('ble_camera_benchmark.CliClient.start',side_effect=reused):
            with self.assertRaisesRegex(Incomplete,'existing workshop owner'):client.start()
        self.assertIsNone(client.session)

    def test_existing_rust_vault_mapping_is_used_without_repairing_or_migration(self):
        class Credential(dict): value='0427'
        calls=[]
        class Vault:
            def _read_credential(self,target):
                calls.append(target)
                return Credential(UserName='AA:BB') if target=='AA:BB.vexaim.bluetooth' else None
        self.assertEqual(saved_setup_code(Vault(),'AA:BB','win32'),'0427')
        self.assertEqual(calls,['AA:BB.vexaim.bluetooth'])

    def test_another_robots_credential_is_never_used(self):
        class Credential(dict): value='0427'
        class Vault:
            def _read_credential(self,target):return Credential(UserName='ANOTHER')
        self.assertIsNone(saved_setup_code(Vault(),'AA:BB','win32'))

    def test_short_stationary_run_can_start_without_an_unnecessary_recharge(self):
        limits=CameraLimits(360,initial_minimum=35)
        limits.check(58,initial=True)
        with self.assertRaises(Incomplete):limits.check(34,initial=True)
        with self.assertRaises(Incomplete):limits.check(24)


if __name__=='__main__':unittest.main()
