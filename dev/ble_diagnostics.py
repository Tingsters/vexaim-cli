"""Bounded Windows Bluetooth A/B investigation. No wheels, kicker or pairing.

Maintainer-only: uv run --no-project --with websocket-client==1.8.0 python
dev/ble_diagnostics.py --help. Reports/photos remain local and ignored.
"""
import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time
import urllib.request


class PhaseFailed(RuntimeError):
    pass


class Incomplete(RuntimeError):
    pass


class LowBattery(Incomplete):
    pass


def contain_children():
    """Put only this runner and its future children in a kill-on-exit job.

    Windows closes the job handle on process exit, including forced termination.
    The handle is deliberately NOT closed while this process is still running.
    Existing applications/owners are not part of this private job.
    """
    from ctypes import wintypes as w
    class Basic(ctypes.Structure):
        _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
            ('flags', w.DWORD), ('minimum', ctypes.c_size_t), ('maximum', ctypes.c_size_t),
            ('active', w.DWORD), ('affinity', ctypes.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]
    class Counters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]
    class Extended(ctypes.Structure):
        _fields_ = [('basic', Basic), ('io', Counters), ('process_memory', ctypes.c_size_t),
            ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
    kernel.CreateJobObjectW.restype = w.HANDLE
    kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
    kernel.GetCurrentProcess.restype = w.HANDLE
    handle = kernel.CreateJobObjectW(None, None)
    info = Extended()
    info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if (not handle or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info))
            or not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess())):
        raise Incomplete('Cannot contain unattended child processes: '+str(ctypes.get_last_error()))
    return handle


class Journal:
    def __init__(self, directory, monotonic=time.monotonic):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.clock = monotonic
        self.started = monotonic()
        self.events = self.directory / 'events.jsonl'

    def record(self, event, **data):
        row = dict(event=event, utc=datetime.now(timezone.utc).isoformat(),
                   elapsed_s=round(self.clock()-self.started, 3), **data)
        with self.events.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row)+'\n')
        print(json.dumps(row), flush=True)
        return row

    def save(self, result):
        target = self.directory / 'result.json'
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
        temporary.replace(target)


class Limits:
    def __init__(self, seconds=5400, clock=time.monotonic):
        self.clock = clock
        self.ends = clock()+seconds

    def check(self, battery=None, initial=False):
        if self.clock() >= self.ends:
            raise Incomplete('Whole-run deadline reached')
        if battery is not None and battery < (90 if initial else 20):
            raise LowBattery('Battery below initial 90% requirement' if initial else 'Battery below 20% stopping threshold')

    def timeout(self, seconds):
        self.check()
        return max(.1, min(seconds, self.ends-self.clock()))


class HostMonitor:
    def __init__(self, journal, duration=5500, require_bluetooth_only=False):
        self.journal = journal
        self.require_bluetooth_only = require_bluetooth_only
        self.began = time.monotonic()
        self.path = journal.directory / 'windows-events.jsonl'
        self.stop_file = journal.directory / 'monitor.stop'
        script = Path(__file__).with_name('windows-ble-monitor.ps1')
        self.process = subprocess.Popen(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', str(script), '-Output', str(self.path), '-StopFile', str(self.stop_file),
            '-DurationSeconds', str(duration)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)

    def rows(self):
        if not self.path.exists():
            return []
        rows = []
        for line in self.path.read_text(encoding='utf-8-sig').splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # The writer may currently be appending the last line.
        return rows

    def reset_count(self, since):
        boundary = datetime.fromisoformat(since.replace('Z', '+00:00'))
        return sum(row.get('event') == 'adapter_arrival_changed'
                   and datetime.fromisoformat(row['utc'].replace('Z', '+00:00')) >= boundary
                   for row in self.rows())

    def check(self):
        if self.process.poll() is not None:
            raise Incomplete('Windows metadata monitor stopped unexpectedly')
        rows = self.rows()
        if getattr(self, 'require_bluetooth_only', False) and any(row.get('aim_usb_present') is True for row in rows):
            raise Incomplete('An AIM USB data connection was detected; Bluetooth-only measurement invalidated')
        if rows:
            last = datetime.fromisoformat(rows[-1]['utc'].replace('Z', '+00:00'))
            if (datetime.now(timezone.utc)-last).total_seconds() > 20:
                raise Incomplete('Windows metadata monitor stopped progressing')
        elif time.monotonic()-self.began > 20:
            raise Incomplete('Windows metadata monitor produced no evidence')

    def verify_setup(self):
        deadline = time.monotonic()+20
        while time.monotonic() < deadline:
            self.check()
            if any(row.get('event') == 'monitor_health' and row.get('aim_usb_present') is False for row in self.rows()):
                return
            time.sleep(.2)
        raise Incomplete('USB-disconnected setup was not independently verified')

    def close(self):
        self.stop_file.touch()
        try:
            self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)


class CliClient:
    def __init__(self, tool, name, limits, profile=None):
        self.tool, self.name, self.limits = str(Path(tool).resolve()), name, limits
        self.profile = profile
        self.env = os.environ.copy()
        self.env.pop('VEXAIM_DIAGNOSTIC_CONNECTION_PROFILE', None)
        if profile:
            self.env['VEXAIM_DIAGNOSTIC_CONNECTION_PROFILE'] = profile
        self.env['VEXAIM_DIAGNOSTIC_TOOL_PATH'] = self.tool
        self.session = None
        self.owner_pids = []

    def process_ids(self):
        # Do not read command lines or IPC credentials. Only our copied tool path.
        result = subprocess.run(['powershell.exe', '-NoProfile', '-Command',
            'Get-Process | Where-Object { $_.Path -eq $env:VEXAIM_DIAGNOSTIC_TOOL_PATH } | Select-Object -ExpandProperty Id | ConvertTo-Json -Compress'],
            env=self.env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise Incomplete('Cannot identify investigative owner processes')
        value = json.loads(result.stdout) if result.stdout.strip() else []
        return [value] if isinstance(value, int) else value

    def wait_owner_exit(self):
        from ctypes import wintypes as w
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        kernel.OpenProcess.restype = w.HANDLE
        kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        kernel.CloseHandle.argtypes = [w.HANDLE]
        deadline = time.monotonic()+18
        for pid in self.owner_pids:
            handle = kernel.OpenProcess(0x100000, False, pid)
            if handle:
                try:
                    remaining = max(0, round((deadline-time.monotonic())*1000))
                    if kernel.WaitForSingleObject(handle, remaining) != 0:
                        return False
                finally:
                    kernel.CloseHandle(handle)
            elif ctypes.get_last_error() != 87:  # ERROR_INVALID_PARAMETER: exited.
                return False
        return True

    def call(self, *args, timeout=120, cleanup=False):
        deadline = timeout if cleanup else self.limits.timeout(timeout)
        try:
            result = subprocess.run([self.tool, '--json', *args], env=self.env,
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=deadline)
        except subprocess.TimeoutExpired as error:
            raise PhaseFailed('CLI caller deadline expired; no command replayed') from error
        values = []
        for line in result.stdout.splitlines():
            if line.startswith('{'):
                try:
                    values.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        value = values[-1] if values else {}
        if result.returncode or value.get('ok') is not True:
            error = str(value.get('error', 'CLI returned no successful structured result'))
            if 'authentication' in error.lower() or 'credential' in error.lower():
                raise Incomplete('Authentication requires attendance; phase not resumed')
            raise PhaseFailed(error[:500])
        return value

    def start(self):
        if self.process_ids():
            raise Incomplete('An investigative owner already exists; refusing an ambiguous comparison')
        try:
            value = self.call('--name', self.name, 'session', 'start', '--persistent', '--takeover', timeout=75)
        finally:
            self.owner_pids = self.process_ids()
        self.session = value['session']
        if self.profile and value.get('keepalive', {}).get('connection_parameters', {}).get('requested') != self.profile:
            raise Incomplete('Diagnostic connection profile was not activated in the owner')
        return value

    def command(self, *args, **kwargs):
        return self.call('--session', self.session, *args, **kwargs)

    def close(self):
        try:
            if self.session is None:
                # A failed startup exits on its own. Never invent a named-close
                # interface or send a new command without a returned session ID.
                exited = self.wait_owner_exit() and not self.process_ids()
                return {'confirmed': exited, 'owner_exited': exited, 'startup_incomplete': True,
                    'power_cleanup_verified': False}
            # A failed measurement can end while the owner is automatically
            # reconnecting. Let that owner recover before requesting close:
            # v0.4's close ends the owner even if its initial stop cannot read.
            until = time.monotonic()+60
            while True:
                status = self.call('--session', self.session, 'session', 'status', timeout=10, cleanup=True)
                state = status.get('state')
                if state == 'ready':
                    live = self.call('--session', self.session, 'info', timeout=20, cleanup=True)
                    if live.get('robot_state', {}).get('stopped') is not True:
                        raise Incomplete('Cleanup could not verify live stopped state')
                    break
                if state not in ('reconnecting', 'degraded') or time.monotonic() >= until:
                    raise Incomplete('Cleanup could not recover a live connection in its finite budget')
                time.sleep(2)
            value = self.call('--session', self.session, 'session', 'close', timeout=30, cleanup=True)
            # v0.4 acknowledges stopped before final lease/GATT cleanup. Wait
            # for owner exit before handing the radio to another application.
            exited = self.wait_owner_exit()
            self.session = None
            return {'confirmed': value.get('ok') is True and exited, 'stopped': value.get('stopped'),
                'owner_exited': exited, 'power_cleanup_verified': False}
        except Exception as error:
            return {'confirmed': False, 'error': str(error)}


def official_ble_chunk(archive):
    """Locate the installed app's own lazy BLE bundle without extracting it."""
    import runpy
    files = runpy.run_path(str(Path(__file__).with_name('inspect-vexcode.py')))['files']
    with Path(archive).open('rb') as stream:
        first, header_size, object_size, json_size = struct.unpack('<IIII', stream.read(16))
        if first != 4 or not 0 < json_size < object_size <= header_size < 64*1024*1024:
            raise Incomplete('Unexpected official application archive')
        tree = json.loads(stream.read(json_size))
        candidates = [(name, entry) for name, entry in files(tree['files'])
            if 'vex-ble-device-manager' in name and name.endswith('.bundle.js')
            and not entry.get('unpacked') and not entry.get('link')]
        if len(candidates) != 1:
            raise Incomplete('Official Bluetooth source bundle is ambiguous or unavailable')
        name, entry = candidates[0]
        offset = 8+header_size+int(entry['offset'])
        count = int(entry['size'])
        if offset < 8+header_size or count < 0 or offset+count > Path(archive).stat().st_size:
            raise Incomplete('Official Bluetooth bundle is outside archive bounds')
        stream.seek(offset)
        text = stream.read(min(count, 4096)).decode('utf-8')
        match = re.search(r'\.push\(\[\["([^"\r\n]+)"\]', text)
        if not match:
            raise Incomplete('Official Bluetooth chunk registration is unsupported')
        return match[1]


class OfficialClient:
    """CDP observation of installed VEXcode; no copied proprietary source."""
    def __init__(self, name, port=9223, auth_code=None):
        self.name, self.port = name, port
        self.auth_code = auth_code
        self.socket = None
        self.process = None
        self.sequence = 0
        self.opened = False

    def evaluate(self, source, timeout=15):
        result = self.request('Runtime.evaluate', {'expression': source, 'awaitPromise': True,
            'returnByValue': True, 'userGesture': True}, timeout)
        if 'exceptionDetails' in result:
            raise Incomplete('Official application automation failed')
        return result.get('result', {}).get('value')

    def request(self, method, params, timeout=15):
        self.sequence += 1
        self.socket.settimeout(timeout)
        self.socket.send(json.dumps({'id': self.sequence, 'method': method, 'params': params}))
        while True:
            value = json.loads(self.socket.recv())
            if value.get('id') == self.sequence:
                if 'error' in value:
                    raise Incomplete('Official application automation failed')
                return value.get('result', {})

    def prepare(self):
        import websocket
        executable = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'VEX Robotics/VEXcode AIM/VEXcode AIM.exe'
        if not executable.exists():
            raise Incomplete('Official Windows VEXcode AIM is not installed')
        # Start only our own debug instance. Existing app must be closed up front.
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = subprocess.SW_HIDE
        self.process = subprocess.Popen([str(executable), '--remote-debugging-address=127.0.0.1',
            '--remote-debugging-port='+str(self.port)], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=info)
        deadline = time.monotonic()+45
        target = None
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise Incomplete('Official app did not start a private automation instance; close it during setup')
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{self.port}/json/list', timeout=2) as response:
                    targets = json.load(response)
                target = next((t for t in targets if t.get('type') == 'page' and 'app.asar/dist/index.html' in t.get('url', '')), None)
                if target:
                    break
            except (OSError, ValueError):
                pass
            time.sleep(.5)
        if not target:
            raise Incomplete('Official automation endpoint unavailable; setup incomplete')
        self.socket = websocket.create_connection(target['webSocketDebuggerUrl'], timeout=15, suppress_origin=True)
        self.request('Emulation.setFocusEmulationEnabled', {'enabled': True})
        ready = False
        while time.monotonic() < deadline:
            ready = self.evaluate("typeof self.webpackChunkwebapp!=='undefined' && !!window.electronAPI?.bluetooth")
            if ready:
                break
            time.sleep(.5)
        if not ready:
            raise Incomplete('Official application did not finish loading its Bluetooth interface')
        self.evaluate("self.webpackChunkwebapp.push([['ble_inspect_'+Date.now()],{},r=>{self.__bleRequire=r}]); true")
        chunk = official_ble_chunk(executable.parent/'resources/app.asar')
        self.evaluate('self.__bleRequire.e('+json.dumps(chunk)+').then(()=>true)')
        self.evaluate('''(() => {
          const C=self.__bleRequire('./node_modules/@vexcode/vex-ble-device-manager/dist_lib/src/VEXBLEDeviceManager.js').VEXBLEDeviceManager;
          const m=self.__bleModule=new C('AIM');
          self.__bleDiag={selected:false,lastNotification:0,count:0,subscriptions:[]};
          const original=BluetoothRemoteGATTCharacteristic.prototype.startNotifications;
          BluetoothRemoteGATTCharacteristic.prototype.startNotifications=async function(...args){
            self.__bleDiag.subscriptions.push(this.uuid);
            if(!this.__bleObserved){this.__bleObserved=true;this.addEventListener('characteristicvaluechanged',()=>{
              if(this.uuid==='6c7851a0-adf7-4de6-881d-1ce2cd0fecf9'){
                self.__bleDiag.lastNotification=Date.now();self.__bleDiag.count++;
              }
            });}return original.apply(this,args);
          };
          m.getLockCode=async()=>{self.__bleDiag.authFailed=true;};
          return {ready:!!m};
        })()''')
        self.evaluate('''window.electronAPI.bluetooth.onDownloadDeviceListUpdate(list=>{
          const d=list.find(x=>x.deviceName==='''+json.dumps(self.name)+''');
          if(d&&!self.__bleDiag.selected){self.__bleDiag.selected=true;window.electronAPI.bluetooth.selectDevice(d.deviceId)}
        }); true''')
        if self.auth_code is not None:
            # Only the already supplied setup credential, transiently in RAM.
            # Never request a new code, read the vault, or include this in logs.
            expected = [int(digit) for digit in self.auth_code]
            self.evaluate('''self.__bleModule.getLockCode=async()=>{
              self.__bleDiag.authAttempted=true;
              try {
                const characteristic=self.__bleModule.characteristics['08590f7e-db05-467e-8757-72f6faeb13e5'];
                let value=await characteristic.readValue();
                const expected='''+json.dumps(expected)+''';
                if(value.byteLength===4&&value.getUint32(0)===0xdeadface){
                  // Restore the existing credential on a fresh GATT link, just
                  // as the CLI does. Never overwrite a different owner's code.
                  await characteristic.writeValueWithResponse(new Uint8Array(expected));
                  await new Promise(resolve=>setTimeout(resolve,500));
                  value=await characteristic.readValue();
                  self.__bleDiag.authRestored=true;
                }
                const matched=value.byteLength===4&&expected.every((d,i)=>value.getUint8(i)===d);
                self.__bleDiag.authFailed=!matched;
                if(matched){
                  self.__bleModule.deviceInfo.unlocked=true;
                  await self.__bleModule.updateDeviceInfoOnConnect();
                }
              } catch (e) {self.__bleDiag.authFailed=true;self.__bleDiag.authErrorName=e?.name||'request_failed';}
            }; true''')
            self.auth_code = None

    def connect(self):
        self.opened = True
        self.evaluate('self.__bleModule.scanAndConnect().then(()=>true)', timeout=45)
        deadline = time.monotonic()+15
        while time.monotonic() < deadline:
            value = self.status()
            age = value.get('notification_age_ms')
            if value.get('connected') and isinstance(age, (int, float)) and age < 12000:
                return value
            time.sleep(.5)
        raise Incomplete('Official setup incomplete; no new pairing requested: '+json.dumps(value))

    def status(self):
        return self.evaluate('''(() => ({connected:self.__bleModule.getConnectionState()===2,
          notifications:self.__bleDiag.count,
          auth_failed:self.__bleDiag.authFailed===true,
          auth_attempted:self.__bleDiag.authAttempted===true,
          auth_restored:self.__bleDiag.authRestored===true,
          auth_error_name:self.__bleDiag.authErrorName||null,
          state:self.__bleModule.getConnectionState(),subscriptions:self.__bleDiag.subscriptions,
          notification_age_ms:self.__bleDiag.lastNotification?Date.now()-self.__bleDiag.lastNotification:null}))()''')

    def disconnect(self):
        if self.socket and self.opened:
            self.evaluate('(async()=>{await self.__bleModule.disconnect();return {connected:self.__bleModule.getConnectionState()===2}})()')
            self.opened = False

    def close(self):
        try:
            self.disconnect()
        finally:
            if self.socket:
                self.socket.close()
                self.socket = None
            if self.process and self.process.poll() is None:
                # Terminate only the application instance this runner launched.
                subprocess.run(['taskkill', '/PID', str(self.process.pid), '/T', '/F'],
                    capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
            self.process = None


class Runner:
    def __init__(self, journal, host, limits, sleep=time.sleep):
        self.journal, self.host, self.limits, self.sleep = journal, host, limits, sleep
        self.latest_battery = None
        self.phases = []

    def battery(self, state, initial=False):
        battery = state.get('robot_state', {}).get('battery_pct')
        if not isinstance(battery, (int, float)):
            raise Incomplete('No live battery reading')
        self.latest_battery = battery
        self.limits.check(battery, initial)
        if state['robot_state'].get('stopped') is not True:
            raise Incomplete('Stationary test found robot not stopped')
        return battery

    def wait(self, seconds, sample, strict=False):
        begin = self.journal.clock()
        since = datetime.now(timezone.utc).isoformat()
        outage = None
        first_reconnect = None
        interrupted = False
        next_print = begin
        while self.journal.clock()-begin < seconds:
            self.limits.check(self.latest_battery)
            self.host.check()
            value = sample()
            if value.get('state') in ('auth_required', 'program_running'):
                raise Incomplete('Unattended phase cannot acquire authentication/program ownership')
            healthy = value.get('healthy') is True
            reconnects = value.get('reconnects', 0)
            if first_reconnect is None:
                first_reconnect = reconnects
            interrupted = interrupted or not healthy or reconnects != first_reconnect
            if strict and (not healthy or reconnects != first_reconnect):
                raise PhaseFailed('Unsolicited link loss during confirmation')
            if not healthy:
                if outage is None:
                    outage = self.journal.clock()
                    self.journal.record('outage', state=value.get('state'))
                if self.journal.clock()-outage >= 90:
                    raise PhaseFailed('Automatic recovery exceeded 90 seconds')
            elif outage is not None:
                self.journal.record('recovered', outage_s=round(self.journal.clock()-outage, 3))
                outage = None
            resets = self.host.reset_count(since)
            interrupted = interrupted or resets > 0
            if resets >= (1 if strict else 2):
                raise PhaseFailed('Windows adapter re-enumerated during measurement')
            if self.journal.clock() >= next_print:
                self.journal.record('health', **value, adapter_arrivals=resets)
                next_print = self.journal.clock()+30
            self.sleep(min(2, max(0, seconds-(self.journal.clock()-begin))))
        if outage is not None:
            raise PhaseFailed('Phase ended with an unresolved outage')
        if interrupted:
            raise PhaseFailed('Comparison completed with a recovered interruption; not a stable pass')

    def phase(self, label, operation):
        self.journal.record('phase_begin', phase=label)
        row = dict(phase=label, outcome='failed')
        try:
            operation()
            row['outcome'] = 'passed'
        except Incomplete as error:
            if isinstance(error.__cause__, PhaseFailed):
                row.update(outcome='failed', error=str(error.__cause__), cleanup_error=str(error))
            else:
                row.update(outcome='incomplete', error=str(error))
            raise
        except Exception as error:
            row.update(error=str(error)[:500])
        finally:
            self.phases.append(row)
            self.journal.record('phase_end', **row)
            self.journal.save(self.result('running'))
        return row['outcome'] == 'passed'

    def cli_phase(self, label, client, seconds, initial=False, confirm=False):
        def operation():
            try:
                started = client.start()
                self.battery(client.command('info'), initial)
                measurement_start = datetime.now(timezone.utc).isoformat()
                initial_reconnects = started.get('keepalive', {}).get('reconnect_count', 0)
                self.journal.record('cli_ready', phase=label, battery_pct=self.latest_battery,
                    parameters=started.get('keepalive', {}).get('connection_parameters'))
                next_live = self.journal.clock()+60
                def sample():
                    nonlocal next_live
                    status = client.command('session', 'status', timeout=10)
                    if self.journal.clock() >= next_live and status.get('state') == 'ready':
                        self.battery(client.command('info', timeout=20))
                        next_live = self.journal.clock()+60
                    h = status.get('keepalive', {})
                    return dict(healthy=status.get('state') == 'ready' and h.get('healthy') is True,
                        state=status.get('state'), reconnects=h.get('reconnect_count', 0),
                        battery_pct=self.latest_battery, parameters=h.get('connection_parameters'))
                self.wait(seconds, sample, strict=confirm)
                self.battery(client.command('info'))
                if confirm:
                    for index in range(2):
                        image = client.command('camera', 'observe', '--output-dir', str(self.journal.directory/f'camera-{index}'))
                        if image.get('control_ready') is not True:
                            raise PhaseFailed('Camera did not restore control readiness')
                        self.journal.record('camera', path=image.get('path'), width=image.get('width'), height=image.get('height'))
                    client.command('exec', '--timeout', '15', "robot.screen.clear_screen(BLUE); robot.screen.set_pen_color(WHITE); robot.screen.draw_circle(120,120,45); print('display complete')")
                    lcd = client.command('screen', 'screenshot', str(self.journal.directory/'lcd.png'))
                    if lcd.get('control_ready') is not True:
                        raise PhaseFailed('LCD capture did not restore control readiness')
                    self.journal.record('lcd', path=lcd.get('path'), width=lcd.get('width'), height=lcd.get('height'))
                    client.command('stop')
                    self.battery(client.command('info'))
                final = client.command('session', 'status')
                if (self.host.reset_count(measurement_start)
                        or final.get('keepalive', {}).get('reconnect_count', 0) != initial_reconnects):
                    raise PhaseFailed('Link/adapter reset during measurement or final functional checks')
            finally:
                pending = sys.exception()
                if pending is not None:
                    self.journal.record('cli_error', phase=label, error=str(pending)[:500])
                cleanup = client.close()
                self.journal.record('cli_cleanup', phase=label, **cleanup)
                if not cleanup['confirmed']:
                    raise Incomplete('Connection cleanup was not confirmed; further clients were not started') from pending
        return self.phase(label, operation)

    def official_phase(self, official, seconds):
        def operation():
            try:
                official.prepare()
                official.connect()
                self.journal.record('setup_verified', unattended=True, later_attendance_required=False)
                def sample():
                    value = official.status()
                    age = value.get('notification_age_ms')
                    return dict(healthy=value.get('connected') is True and isinstance(age, (int, float)) and age < 12000,
                        state='connected' if value.get('connected') else 'disconnected', notifications=value.get('notifications'))
                self.wait(seconds, sample)
            finally:
                official.close()
        return self.phase('official-vexcode', operation)

    def result(self, outcome, **extra):
        return dict(outcome=outcome, phases=self.phases, battery_pct=self.latest_battery,
            human_interventions_after_setup=0, unattended=True, **extra)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--released', required=True, type=Path)
    parser.add_argument('--candidate', required=True, type=Path)
    parser.add_argument('--name', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--stationary-ready', action='store_true')
    parser.add_argument('--official-seconds', type=int, default=180)
    parser.add_argument('--comparison-seconds', type=int, default=300)
    parser.add_argument('--confirmation-seconds', type=int, default=3600)
    parser.add_argument('--baseline-seconds', type=int, default=0)
    parser.add_argument('--baseline-only', action='store_true')
    parser.add_argument('--recovery-test-exe', type=Path)
    parser.add_argument('--official-auth-stdin', action='store_true', help='Read the existing setup code once from stdin; never request a new code unattended')
    parser.add_argument('--candidate-only', action='store_true', help='Separate follow-up measurement of the OS-default candidate; never relabel an earlier failed comparison')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Windows-only host investigation')
    if not args.baseline_only and not args.stationary_ready:
        parser.error('Complete physical setup before --stationary-ready')
    if args.baseline_only and args.baseline_seconds <= 0:
        parser.error('A host baseline needs a positive duration')
    if min(args.official_seconds, args.comparison_seconds, args.confirmation_seconds) <= 0 or args.baseline_seconds < 0:
        parser.error('Measurement durations must be positive')
    if (args.output/'events.jsonl').exists() or (args.output/'result.json').exists():
        parser.error('Use a fresh output directory; failed runs are never overwritten')
    setup_code = None
    if args.official_auth_stdin:
        setup_code = sys.stdin.readline().strip()
        if not re.fullmatch(r'[0-9]{4}', setup_code):
            parser.error('Supply four setup digits on stdin; no credential is logged')
    journal = Journal(args.output)
    job_handle = contain_children()  # Kept open until Windows exits this runner.
    limits = Limits()
    host = HostMonitor(journal, require_bluetooth_only=not args.baseline_only)
    runner = Runner(journal, host, limits)
    outcome, extra = 'incomplete', {}
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
        journal.record('configuration', harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            official_seconds=args.official_seconds, comparison_seconds=args.comparison_seconds,
            confirmation_seconds=args.confirmation_seconds, whole_run_seconds=5400)
        for label, path in [('released', args.released), ('candidate', args.candidate)]:
            journal.record('binary', label=label, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        if args.baseline_seconds:
            runner.phase('host-only-baseline', lambda: runner.wait(args.baseline_seconds, lambda: {'healthy': True}))
        if args.baseline_only:
            outcome = 'baseline_complete'
        else:
            host.verify_setup()
            journal.record('physical_setup', robot_usb_connected=False, robot_power='battery_or_external_power_without_data')
            # The operator is present for preflight; absence is never treated as pairing consent.
            preflight = CliClient(args.candidate if args.candidate_only else args.released, args.name, limits,
                'os-default' if args.candidate_only else None)
            runner.cli_phase('setup-live-check', preflight, 0, initial=True)
            if runner.phases[-1]['outcome'] != 'passed':
                raise Incomplete('Initial connection verification failed')
            if args.candidate_only:
                official_ok, released_ok = None, None
                journal.record('setup_verified', unattended=True, later_attendance_required=False,
                    scope='candidate-only follow-up; official and released controls not repeated')
            else:
                official = OfficialClient(args.name, auth_code=setup_code)
                setup_code = None
                official_ok = runner.official_phase(official, args.official_seconds)
                released_ok = runner.cli_phase('released-throughput', CliClient(args.released, args.name, limits), args.comparison_seconds)
            candidate_ok = runner.cli_phase('candidate-os-default', CliClient(args.candidate, args.name, limits, 'os-default'), args.comparison_seconds)
            extra.update(official_passed=official_ok, released_passed=released_ok, candidate_passed=candidate_ok,
                comparison_scope='candidate-only' if args.candidate_only else 'full-comparison')
            if released_ok:
                selected = CliClient(args.released, args.name, limits)
                extra['selected_configuration'] = 'released-on-current-host-path'
            elif candidate_ok:
                selected = CliClient(args.candidate, args.name, limits, 'os-default')
                extra['selected_configuration'] = 'candidate-os-default'
            else:
                raise PhaseFailed('Neither CLI configuration was stable; hardware/driver evidence requires analysis')
            passed = runner.cli_phase('uninterrupted-confirmation', selected, args.confirmation_seconds, confirm=True)
            outcome = 'passed' if passed else 'failed'
            if passed and args.recovery_test_exe:
                def recover():
                    env = selected.env.copy()
                    env['VEXAIM_STATIONARY_READY'] = 'yes'
                    env['VEXAIM_STATIONARY_NAME'] = args.name
                    result = subprocess.run([str(args.recovery_test_exe.resolve()), '--exact',
                        'session::robot::acceptance::stationary_closed_link_recovers_without_pairing_or_movement',
                        '--ignored', '--nocapture'], stdin=subprocess.DEVNULL, capture_output=True,
                        text=True, env=env, timeout=limits.timeout(120))
                    evidence = None
                    for line in result.stdout.splitlines():
                        if '{' in line:
                            try:
                                value, _ = json.JSONDecoder().raw_decode(line[line.index('{'):])
                                if value.get('event') == 'controlled_reconnect_passed':
                                    evidence = value
                            except ValueError:
                                pass
                    if result.returncode or evidence is None:
                        raise PhaseFailed('Controlled reconnection did not return passing evidence')
                    runner.battery(evidence)
                    journal.record('controlled_recovery', recovery_ms=evidence.get('recovery_ms'),
                        battery_pct=runner.latest_battery)
                if not runner.phase('controlled-recovery', recover):
                    outcome = 'failed'
    except Incomplete as error:
        extra['reason'] = str(error)
    except Exception as error:
        outcome, extra['reason'] = 'failed', str(error)[:500]
    finally:
        try:
            host.close()
        except Exception:
            outcome, extra['monitor_cleanup'] = 'incomplete', 'Process containment releases remaining children on exit'
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        result = runner.result(outcome, **extra)
        journal.save(result)
        journal.record('finished', **result)
    return 0 if outcome in ('passed', 'baseline_complete') else 2 if outcome == 'incomplete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
