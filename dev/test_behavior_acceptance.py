"""Verify acceptance gating without a radio or executable."""
import json
from pathlib import Path
import runpy
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

HARNESS=runpy.run_path(str(Path(__file__).with_name('accept-behaviors.py')))


class Acceptance(unittest.TestCase):
    def exercise(self,fail=None,motion=False):
        calls=[]
        def runner(command,**kwargs):
            words=command[4:];calls.append(words)
            if words==['session','status']:result={'ok':True,'transport':'bluetooth'}
            elif words==['info']:result={'ok':True,'robot_state':{'stopped':True,'battery_pct':80}}
            elif 'timing.py' in command[-1]:result={'ok':True,'measurement':{'stopped':True,'callback_ms':[400],'system_ms':620,'timer_ms':620,'read_ms':[1]*6}}
            elif 'cargo.py' in command[-1]:result={'ok':True,'measurement':{'pickup':{'collected':True},'delivery':{'delivered':True}}}
            else:result={'ok':True}
            if fail=='timeout' and 'cargo.py' in command[-1]:raise subprocess.TimeoutExpired(command,110)
            if fail=='clock' and 'timing.py' in command[-1]:result['measurement']['timer_ms']=0
            if fail=='low' and words==['info']:result['robot_state']['battery_pct']=20
            if fail=='cargo' and 'cargo.py' in command[-1]:result={'ok':False,'stderr':'not_collected'}
            return SimpleNamespace(returncode=0 if result['ok'] else 1,stdout=json.dumps({'event':'result',**result}),stderr='')
        with tempfile.TemporaryDirectory() as root:
            args=SimpleNamespace(tool=Path(root)/'vexaim',session='fixture',output_dir=Path(root)/'results',motion_ready=motion,cargo='BLUE_BARREL',tag=0)
            report=HARNESS['run'](args,runner)
            self.assertTrue((args.output_dir/'report.json').exists())
        return report,calls

    def test_stationary_is_default_and_keeps_owner(self):
        report,calls=self.exercise()
        self.assertTrue(report['passed'])
        self.assertFalse(any('cargo.py' in w[-1] for w in calls))
        self.assertNotIn(['session','close'],calls)

    def test_motion_follows_the_timing_gate(self):
        report,calls=self.exercise(motion=True)
        self.assertTrue(report['passed'])
        self.assertFalse(report['physical_attachment_independently_verified'])
        self.assertEqual(sum('cargo.py' in w[-1] for w in calls),1)

    def test_failure_stops_without_replay_or_later_human_request(self):
        for failure in ('clock','low','cargo','timeout'):
            with self.subTest(failure=failure):
                report,calls=self.exercise(failure,motion=True)
                self.assertFalse(report['passed'])
                self.assertEqual(calls[-1],['stop'])
                self.assertLessEqual(sum('cargo.py' in w[-1] for w in calls),1)


if __name__=='__main__':unittest.main()
