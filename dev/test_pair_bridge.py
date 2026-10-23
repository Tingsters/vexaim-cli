"""Exercise the shipped Windows pairing helper against a stdin-only fake CLI."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

SCRIPT = Path(__file__).parents[1] / 'skill/vex-aim/scripts/pair.ps1'


@unittest.skipUnless(os.name == 'nt' and shutil.which('powershell.exe'), 'Windows PowerShell fixture')
class PairBridge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory(prefix='vexaim pairing fixture ')
        cls.executable = Path(cls.fixture.name) / 'fake cli.exe'
        source = ('public class Pair { public static int Main(string[] args) { '
                  'System.Console.Error.WriteLine("Read the four-digit code on the selected robot LCD"); '
                  'var value=System.Console.ReadLine(); '
                  'return value!=null && value.Length==4 ? 0 : 1; } }')
        command = "Add-Type -TypeDefinition '" + source + "' -OutputType ConsoleApplication -OutputAssembly '" + str(cls.executable).replace("'", "''") + "'"
        result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', command], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.fixture.cleanup()

    def call(self, *args, input=None):
        result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                 '-File', str(SCRIPT), *args], input=input,
                                capture_output=True, text=True, timeout=12)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.lstrip('\ufeff'))

    def test_abandoned_pair_request_expires_without_a_pin_file(self):
        # The broker owns its finite wait; closing a chat must not leave a helper
        # or pairing child waiting forever.
        started = self.call('-Action', 'Start', '-Name', 'AIM-TEST',
                            '-Tool', str(self.executable), '-WaitSeconds', '1')
        directory = Path(started['directory'])
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                state = self.call('-Action', 'Status', '-Directory', str(directory))
                if state['state'] == 'failed':
                    break
                time.sleep(.1)
            self.assertEqual(state['state'], 'failed', state)
            self.assertFalse((directory / 'code.txt').exists())
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    def test_code_reaches_original_process_without_a_pin_file(self):
        with tempfile.TemporaryDirectory(prefix='vexaim pairing test ') as temp:
            started = self.call('-Action', 'Start', '-Name', 'AIM-TEST', '-Tool', str(self.executable))
            directory = Path(started['directory'])
            try:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    state = self.call('-Action', 'Status', '-Directory', str(directory))
                    if state['state'] in ('waiting', 'failed'):
                        break
                    time.sleep(.1)
                self.assertEqual(state['state'], 'waiting', state)
                code = '0427'  # Synthetic fixture input, never a robot credential.
                submitted = self.call('-Action', 'Submit', '-Directory', str(directory), input=code+'\n')
                self.assertTrue(submitted['submitted'])
                while time.monotonic() < deadline:
                    state = self.call('-Action', 'Status', '-Directory', str(directory))
                    if state['state'] in ('paired', 'failed'):
                        break
                    time.sleep(.1)
                self.assertEqual(state['state'], 'paired', state)
                for path in directory.iterdir():
                    self.assertNotIn(code, path.read_text(encoding='utf-8-sig'))
            finally:
                shutil.rmtree(directory, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
