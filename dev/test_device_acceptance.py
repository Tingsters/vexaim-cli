"""Run the actual acceptance harness with a fake executable's responses."""
import contextlib
import io
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

HARNESS=runpy.run_path(str(Path(__file__).with_name('accept-device.py')))

class DeviceAcceptance(unittest.TestCase):
    def run_harness(self, failures=None, effects=False, cleanup_exception=False):
        failures=failures or {}
        calls=[]
        def run(command, **options):
            words=tuple(command[4:])  # executable --json --session fixture
            calls.append(words)
            if cleanup_exception and words==('led','off','all'):
                raise OSError('radio lost during cleanup')
            result=failures.get(words,{'ok':True})
            return SimpleNamespace(returncode=0 if result['ok'] else 1,
                                   stdout=json.dumps(result),stderr='')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            tool=root/'fake-vexaim';tool.touch()
            args=SimpleNamespace(tool=tool,output_dir=root/'results',session='fixture',
                transport='bluetooth',skip_camera=True,effects_ready=effects,
                motion_ready=False,kicker_ready=False,keep_session=False)
            with patch.object(HARNESS['subprocess'],'run',side_effect=run), \
                 patch.object(HARNESS['time'],'sleep'), \
                 contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                status=HARNESS['main'](args)
            report=json.loads(next(args.output_dir.glob('device-*.json')).read_text())
        return status,report,calls

    def test_effect_failure_still_cleans_up_every_effect(self):
        rejection={'ok':False,'rejected':True,'value':{'error':'unsupported_firmware: constant HAPPY'}}
        for cleanup_exception in (False,True):
            with self.subTest(cleanup_exception=cleanup_exception):
                status,report,calls=self.run_harness(
                    {('screen','show-emoji','happy'):rejection},effects=True,
                    cleanup_exception=cleanup_exception)
                self.assertEqual(status,1)
                self.assertFalse(report['completed'])
                self.assertEqual(calls[-3:],[('led','off','all'),('screen','hide-emoji'),('sound','stop')])
                self.assertEqual(bool(report.get('cleanup_errors')),cleanup_exception)

    def test_failed_read_cannot_be_reported_as_successful_acceptance(self):
        status,report,_=self.run_harness({('inertial','get-heading'):{'ok':False,'error':'bad frame'}})
        self.assertEqual(status,1)
        self.assertTrue(report['completed'])
        self.assertFalse(report['passed'])
        self.assertEqual(report['summary']['failed'],1)

    def test_unsupported_firmware_is_separate_from_failed_checks(self):
        result={'ok':False,'rejected':True,'value':{'error':'unsupported_firmware: robot.get_name'}}
        status,report,_=self.run_harness({('robot','name'):result})
        self.assertEqual(status,0)
        self.assertTrue(report['passed'])
        self.assertEqual(report['summary']['unsupported'],1)
        self.assertEqual(report['summary']['failed'],0)

    def test_failed_cleanup_is_reported_even_after_successful_effects(self):
        status,report,calls=self.run_harness({('led','off','all'):{'ok':False,'error':'stop lost'}},effects=True)
        self.assertEqual(status,1)
        self.assertTrue(report['cleanup_errors'])
        self.assertIn(('sound','stop'),calls)

if __name__=='__main__':unittest.main()
