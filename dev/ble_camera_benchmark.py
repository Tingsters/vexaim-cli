"""Short, Bluetooth-only camera experiment. Setup once; never prompt mid-run.

Reports and photographs stay in the ignored output directory. No Wi-Fi, pairing,
firmware changes, driver changes or saved projects. Movement is opt-in and gated
by capture timing, measured geometry and separately verified recognition quality.
"""
import argparse
import asyncio
import ctypes
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import time

from ble_diagnostics import CliClient, HostMonitor, Incomplete, Journal, Limits, contain_children
from camera_search import percentile


class CameraLimits(Limits):
    def __init__(self,seconds=840,clock=time.monotonic,initial_minimum=90):
        super().__init__(seconds,clock)
        self.initial_minimum=initial_minimum
    def check(self, battery=None, initial=False):
        if self.clock() >= self.ends:
            raise Incomplete('Short camera investigation deadline reached')
        minimum=self.initial_minimum if initial else 25
        if battery is not None and battery < minimum:
            raise Incomplete(f'Charge {battery}% is below the {minimum}% threshold; no later restart requested')


def timing_feasible(frame_ms, inference_ms, fov, goal_ms=15000):
    """Optimistic worst-bearing bound: excludes settle/RPC overhead, so failure is decisive."""
    sectors = math.ceil(360/(fov*.8))
    estimate = sectors*(frame_ms+inference_ms)+(360-360/sectors)/90*1000
    return {'sectors':sectors, 'optimistic_search_ms':estimate, 'goal_ms':goal_ms,
        'feasible':estimate <= goal_ms, 'includes_agent_planning':False,
        'includes_cold_start':False, 'arrival_verified':False}


def saved_setup_code(vault, device_id, platform=sys.platform):
    """Read only this robot's existing entry, including Rust keyring's mapping.

    Rust keyring 3 uses username.service on Windows; Python keyring uses
    username@service and historically also service alone. Verify the username
    for every exact target; never enumerate or migrate unrelated credentials.
    """
    service='vexaim.bluetooth'
    if platform=='win32':
        for target in (f'{device_id}.{service}',service,f'{device_id}@{service}'):
            credential=vault._read_credential(target)
            if credential and str(credential.get('UserName','')).casefold()==device_id.casefold():
                value=credential.value
                return value if len(value)==4 and value.isascii() and value.isdecimal() else None
        return None
    return vault.get_password(service,device_id)


class CameraClient(CliClient):
    def __init__(self, tool, name, limits, journal, directory, mode=None, profile='os-default', window='legacy', pacing='legacy'):
        super().__init__(tool, name, limits, profile if mode else None)
        self.journal = journal
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.timing_path = self.directory/'capture-timing.jsonl'
        for key in list(self.env):
            if key.startswith('VEXAIM_DIAGNOSTIC_CAPTURE_'):
                del self.env[key]
        if mode:
            self.env.update(VEXAIM_DIAGNOSTIC_CAPTURE_AUTH=mode,
                VEXAIM_DIAGNOSTIC_CAPTURE_WINDOW=window,
                VEXAIM_DIAGNOSTIC_CAPTURE_PACING=pacing,
                VEXAIM_DIAGNOSTIC_CAPTURE_BLOCK_MS='1500',
                VEXAIM_DIAGNOSTIC_CAPTURE_TOTAL_MS='60000',
                VEXAIM_DIAGNOSTIC_CAPTURE_REPORT=str(self.timing_path.resolve()))

    def start(self):
        value=super().start()
        if not self.owner_pids:
            # A stable session identity may reuse a workshop owner from another binary.
            # Do not benchmark the wrong executable or close a process outside our job.
            self.session=None
            raise Incomplete('An existing workshop owner was reused; no investigative owner was created')
        return value

    def capture(self, index):
        started=time.monotonic()
        value=self.command('camera','observe','--output-dir',str(self.directory/f'frame-{index}'),timeout=65)
        if value.get('transport')!='bluetooth' or value.get('control_ready') is not True:
            raise Incomplete('Capture did not return verified Bluetooth control readiness')
        self.limits.check(value.get('after',{}).get('battery_pct'))
        row={k:value.get(k) for k in ('observation_id','path','bytes','width','height','sha256','latency_ms')}
        row['call_ms']=(time.monotonic()-started)*1000
        traces=self.traces()
        if traces: row['capture_timing']=traces[-1]
        summary={k:v for k,v in row.items() if k!='capture_timing'}
        if traces: summary['capture_elapsed_ms']=traces[-1].get('elapsed_ms')
        self.journal.record('camera_frame', **summary)
        return row

    def traces(self):
        if not self.timing_path.exists(): return []
        return [json.loads(line) for line in self.timing_path.read_text(encoding='utf-8').splitlines() if line.strip()]

    def close(self):
        """Interrupt an outstanding capture, then await this owner's actual exit."""
        try:
            if self.session is None:
                return {'confirmed':self.wait_owner_exit() and not self.process_ids(), 'startup_incomplete':True}
            # Stop/close are priority requests. Never queue info behind a stalled transfer.
            self.call('--session',self.session,'stop',timeout=8,cleanup=True)
            value=self.call('--session',self.session,'session','close',timeout=12,cleanup=True)
            exited=self.wait_owner_exit()
            self.session=None
            return {'confirmed':bool(value.get('ok') and exited), 'stopped':value.get('stopped'),
                'owner_exited':exited, 'power_cleanup_verified':False}
        except Exception as error:
            return {'confirmed':False, 'error':str(error)[:300], 'power_cleanup_verified':False}


async def python_reference(name, output):
    """Existing independently validated protocol, OS-default parameters, no Python program."""
    from bleak import BleakClient, BleakScanner
    spec=importlib.util.spec_from_file_location('camera_reference',Path(__file__).with_name('ble-feasibility.py'))
    probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)
    found=await BleakScanner.discover(timeout=5,return_adv=True)
    matches=[device for device,adv in found.values() if (adv.local_name or device.name)==name]
    if len(matches)!=1: raise Incomplete('Python reference could not select exactly the setup robot')
    async with BleakClient(matches[0],timeout=10,pair=False) as client:
        identity={}
        for field,short in [('model','2a24'),('hardware','2a27'),('firmware','2a26')]:
            identity[field]=bytes(await client.read_gatt_char(f'0000{short}-0000-1000-8000-00805f9b34fb')).decode().rstrip('\0')
        if identity['model']!='AIM' or identity['hardware']!='REV1' or identity['firmware'] not in ('1.0.0.b0','1.0.4.b0'):
            raise Incomplete('Python reference rejected an unverified robot/firmware')
        current=bytes(await client.read_gatt_char(probe.PAIRING))
        if current==probe.UNPAIRED:
            # Same setup robot and OS vault only; never request a new pairing code.
            saved=saved_setup_code(probe.native_credential_store(),matches[0].address.upper())
            if saved is None: raise Incomplete('Python reference needs authentication; no pairing prompt requested')
            expected=probe.decode_pin(saved)
            await client.write_gatt_char(probe.PAIRING,expected,response=True)
            current=bytes(await client.read_gatt_char(probe.PAIRING))
            if current!=expected: raise Incomplete('Existing authentication was not accepted')
        if len(current)!=4 or any(v>9 for v in current): raise Incomplete('Reference authentication is invalid')
        report={}
        began=time.monotonic()
        await asyncio.wait_for(probe.check_screen_capture(client,inspect_buffer=True,output_file=output,
            result=report,layer=8,native_camera=True,keep_system_notifications=False,transfer_timeout=45),55)
        final=bytes(await client.read_gatt_char(probe.PAIRING))
        if final!=current: raise Incomplete('Pairing changed during reference capture')
        if not report.get('buffer_read_complete'): raise Incomplete('Reference did not return a complete frame')
        # Full image decode is independent of the probe's header validation.
        from PIL import Image
        with Image.open(output) as image:
            image.load()
            if image.size!=(640,480): raise Incomplete('Reference image has wrong dimensions')
        return {'identity':identity,'mtu':client.mtu_size,'call_ms':(time.monotonic()-began)*1000,
            'bytes':output.stat().st_size,'timing':report,'path':str(output.resolve())}


class Investigation:
    def __init__(self,args,journal,host,limits):
        self.args,self.journal,self.host,self.limits=args,journal,host,limits
        self.phases=[]

    def phase(self,label,tool,mode=None,count=1,initial=False,profile='os-default',duration=0):
        directory=self.journal.directory/label
        window=getattr(self.args,'capture_window','legacy') if mode=='operation' else 'legacy'
        pacing=getattr(self.args,'capture_pacing','legacy') if mode=='operation' else 'legacy'
        client=CameraClient(tool,self.args.name,self.limits,self.journal,directory,mode,profile,window,pacing)
        phase={'phase':label,'outcome':'incomplete','frames':[]}
        self.phases.append(phase)
        self.journal.record('phase_begin',phase=label)
        since=datetime.now(timezone.utc).isoformat()
        try:
            start=client.start()
            if isinstance(start,dict):
                phase['connection_parameters']=start.get('keepalive',{}).get('connection_parameters')
            info=client.command('info',timeout=12)
            state=info.get('robot_state',{})
            phase['initial_battery_pct']=state.get('battery_pct')
            if state.get('stopped') is not True: raise Incomplete('Robot must be stationary at setup')
            self.limits.check(state.get('battery_pct'),initial=initial)
            if state.get('battery_pct') is None: raise Incomplete('No live battery reading')
            if initial: self.journal.record('setup_verified',unattended=True,human_interventions_after_setup=0,battery_pct=state['battery_pct'])
            index=0
            started=time.monotonic()
            while index<count or (duration and time.monotonic()-started<duration):
                self.host.check();self.limits.check()
                frame=client.capture(index)
                phase['frames'].append(frame)
                index+=1
                if self.host.reset_count(since): raise Incomplete('Radio reset observed; configuration rejected')
                # A single image taking longer than the entire goal already disproves this configuration.
                if frame['call_ms']>15000 and count>1 and not duration:
                    phase['shortened']='One complete frame already exceeds the full search goal'
                    break
            phase['observed_seconds']=time.monotonic()-started
            if mode and not client.traces(): raise Incomplete('Candidate did not emit capture instrumentation')
            phase['outcome']='passed'
            return phase
        except Exception as error:
            phase.update(outcome='failed',error=str(error)[:500])
            raise
        finally:
            phase['capture_traces']=client.traces()
            phase['cleanup']=client.close()
            if not phase['cleanup']['confirmed']:
                phase.update(outcome='incomplete',cleanup_uncertain=True)
            self.journal.record('phase_end',phase=label,outcome=phase['outcome'],
                frame_count=len(phase['frames']),cleanup=phase['cleanup'],error=phase.get('error'))
            self.journal.save({'outcome':'running','phases':self.phases})
            if phase.get('cleanup_uncertain'): raise Incomplete('Cleanup uncertain; no next connection attempted')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name',required=True)
    parser.add_argument('--released',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--setup-confirmed',action='store_true')
    parser.add_argument('--duration-seconds',type=int,default=900,help='Whole run including 60-second cleanup reserve, 180..900')
    parser.add_argument('--initial-minimum-pct',type=int,default=90,help='Explicit stationary short-run threshold, 35..90; running floor stays 25')
    parser.add_argument('--capture-window',choices=('legacy','payload'),default='legacy',help='Candidate-only, source-backed advertised payload-window experiment')
    parser.add_argument('--capture-pacing',choices=('legacy','reply'),default='legacy',help='Candidate-only reply-paced read experiment; never changes ordinary writes')
    args=parser.parse_args()
    if not args.setup_confirmed: parser.error('Verify the single physical setup before running hardware tests')
    if sys.platform!='win32': parser.error('This is a Windows hardware investigation')
    if not 180<=args.duration_seconds<=900 or not 35<=args.initial_minimum_pct<=90:
        parser.error('Invalid short-run budget or initial charge threshold')
    if args.output_dir.exists() and any(args.output_dir.iterdir()): parser.error('Use a new output directory; existing measurements must not be overwritten')
    journal=Journal(args.output_dir)
    job=contain_children()
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    # 14 minutes for phases, with a final minute reserved for cleanup.
    limits=CameraLimits(args.duration_seconds-60,initial_minimum=args.initial_minimum_pct)
    host=HostMonitor(journal,duration=args.duration_seconds,require_bluetooth_only=True)
    runner=Investigation(args,journal,host,limits)
    result={'outcome':'incomplete','human_interventions_after_setup':0,'goal_seconds':15,
        'motion_run':False,'recognition_acceptance':'not_yet_verified','phases':runner.phases}
    result.update(duration_seconds=args.duration_seconds,initial_minimum_pct=args.initial_minimum_pct)
    try:
        for label,path in [('released',args.released),('candidate',args.candidate)]:
            journal.record('binary',label=label,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        journal.record('configuration',harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            duration_seconds=args.duration_seconds,initial_minimum_pct=args.initial_minimum_pct)
        host.verify_setup()
        runner.phase('released-baseline',args.released,count=1,initial=True)
        runner.phase('candidate-packet-auth',args.candidate,mode='packet')
        candidate=runner.phase('candidate-operation-auth',args.candidate,mode='operation',count=3)
        since=datetime.now(timezone.utc).isoformat()
        reference_timeout=limits.timeout(75)
        try:
            reference=asyncio.run(asyncio.wait_for(python_reference(args.name,journal.directory/'python-reference.jpg'),reference_timeout))
        except Incomplete as error:
            # The independent client has closed its GATT connection on exit.
            # Missing setup credentials must not block the independent CLI comparison.
            if 'authentication' not in str(error).lower():raise
            reference={'outcome':'unavailable','reason':str(error)}
        if host.reset_count(since): raise Incomplete('Python reference coincided with a radio reset')
        result['python_reference']=reference
        journal.record('python_reference',**reference)
        frame_ms=percentile([f['call_ms'] for f in candidate['frames']])
        # Most generous permitted FOV avoids rejecting a candidate on a guessed narrow lens.
        result['best_case_gate']=timing_feasible(frame_ms,0,120)
        result['measured_frame_ms']=frame_ms
        result['balanced_comparison']='not_needed'
        balanced_feasible=False
        if not result['best_case_gate']['feasible']:
            balanced=runner.phase('candidate-balanced-operation',args.candidate,mode='operation',profile='balanced',count=1)
            result['balanced_comparison']={'experimental_only':True,'frame_ms':balanced['frames'][0]['call_ms'],
                'best_case_gate':timing_feasible(balanced['frames'][0]['call_ms'],0,120)}
            balanced_feasible=result['balanced_comparison']['best_case_gate']['feasible']
        baseline=runner.phases[1]['frames'][0]['call_ms']
        if frame_ms<baseline*.85 and limits.ends-time.monotonic()>=360:
            runner.phase('operation-auth-stability',args.candidate,mode='operation',duration=300)
            result['stability_screen']='passed: five minutes of repeated captures, OS-default policy'
        else:
            result['stability_screen']='not_run: no useful improvement or insufficient remaining short-test budget'
        result['outcome']='measurement_complete'
        result['motion_skipped_reason']='Recognition and measured JPEG field of view must pass before physical search acceptance'
        result['goal_verified']=False
        if not result['best_case_gate']['feasible'] and not balanced_feasible:
            result['outcome']='goal_not_met'
            result['motion_skipped_reason']='Measured paths exceed the goal even with zero-cost inference and optimistic 120-degree FOV'
    except Exception as error:
        result.update(outcome='incomplete',error=str(error)[:500])
    finally:
        host.close()
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        journal.save(result)
        journal.record('finished',outcome=result['outcome'],motion_run=False,report=str(journal.directory/'result.json'))
    return 0 if result['outcome']=='measurement_complete' else 1


if __name__=='__main__': raise SystemExit(main())
