"""Developer hardware acceptance using a released binary; no Python packages.

Stationary by default. Photos/reports stay in the ignored .vexaim directory.
Physical flags are explicit operator declarations; an agent must obtain physical
readiness and announce the actions before enabling them. This does not test AI
recognition: the agent must separately open returned camera paths in its turn.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('tool',type=Path)
parser.add_argument('--transport',choices=['usb','bluetooth'],default='usb')
parser.add_argument('--name')
parser.add_argument('--device',type=int)
parser.add_argument('--session')
parser.add_argument('--camera-index',type=int)
parser.add_argument('--output-dir',type=Path,default=Path('.vexaim/acceptance'))
parser.add_argument('--skip-camera',action='store_true')
parser.add_argument('--motion-ready',action='store_true',help='Operator confirms clear floor and supervision: 15 degree right turn, 50 mm forward, 20 mm left strafe, brief low-speed vector move')
parser.add_argument('--kicker-ready',action='store_true',help='Operator confirms front clearance: one soft kick and one place action')
parser.add_argument('--effects-ready',action='store_true',help='Allow brief blue LEDs, quiet chirp, emoji and drawing')
parser.add_argument('--keep-session',action='store_true')

def check_outcome(check):
    value=check['result']
    if check['exit_code']==0 and value.get('ok') is True:
        return 'passed'
    nested=value.get('value')
    detail=value.get('error') or (nested.get('error','') if isinstance(nested,dict) else '')
    if value.get('rejected') is True and detail.startswith('unsupported_firmware:'):
        return 'unsupported'
    return 'failed'

def main(args):
    tool=args.tool.resolve(strict=True)
    output=args.output_dir.resolve()
    output.mkdir(parents=True,exist_ok=True)
    report={'schema_version':1,'started_at_unix_ms':int(time.time()*1000),'transport':args.transport,
            'checks':[],'hardware_accuracy_verified':False,'visual_effects_verified':False}
    session=args.session
    def call(words,session_id=None,selection=None):
        print('Checking: '+' '.join(words),file=sys.stderr)
        command=[str(tool),'--json']
        command+=['--session',session_id] if session_id else selection or []
        result=subprocess.run(command+words,capture_output=True,encoding='utf-8',errors='replace',timeout=150)
        values=[json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        value=values[-1] if values else {'ok':False,'error':result.stderr}
        report['checks'].append({'command':words,'exit_code':result.returncode,'result':value})
        return value
    def require(value):
        if not value.get('ok'):raise RuntimeError(value.get('error') or str(value))
        return value
    try:
        if not session:
            selection=['--transport',args.transport]
            if args.name:selection+=['--name',args.name]
            if args.device is not None:selection+=['--device',str(args.device)]
            session=require(call(['session','start'],selection=selection))['session']
        report['session']=session
        cached=require(call(['session','status'],session))
        report['transport']=cached.get('transport',args.transport)
        report['tool_version']=cached.get('tool_version')
        # Capture immediately after startup, before the longer capability sweep.
        if not args.skip_camera:
            words=['camera','observe','--output-dir',str(output/'captures')]
            if args.camera_index is not None:words+=['--camera-index',str(args.camera_index)]
            observation=require(call(words,session))
            if not observation.get('control_ready'):raise RuntimeError('Image is valid but postcapture control is not ready')
            report['agent_image_handoff_required']=observation['path']
            print('Open this image with the agent image reader: '+observation['path'],file=sys.stderr)
        require(call(['info'],session))
        require(call(['capabilities','--live'],session))
        commands=[['robot','name'],['robot','battery'],['timer','time'],['sound','is-active']]
        commands += [['inertial',method] for method in ['get-heading','get-rotation','get-roll','get-pitch','get-yaw','is-calibrating']]
        commands += [['inertial','get-acceleration',axis] for axis in ['forward','rightward','downward']]
        commands += [['inertial','get-turn-rate',axis] for axis in ['x_axis','y_axis','z_axis']]
        commands += [['cargo',method] for method in ['has-any-barrel','has-orange-barrel','has-blue-barrel','has-sports-ball']]
        commands += [['vision','get-data'],['vision','object-count'],['vision','largest-object']]
        commands += [['controller',method] for method in ['is-connected','get-battery-level','axis1-position','axis2-position','axis1-value','axis2-value','button-up','button-down','button-left','button-right','button-stick']]
        commands += [['screen',method] for method in ['pressing','x-position','y-position','get-row','get-column']]
        commands += [['battery',method] for method in ['level','voltage','current','status']]
        commands += [['link','is-connected'],['link','is-message-available']]
        for words in commands:
            value=call(words,session)
            if value.get('needs_check'):
                state=require(call(['info'],session))
                if not state['robot_state']['stopped']:raise RuntimeError('Stopped state not confirmed')
        if args.effects_ready:
            print('Effects: blue LEDs, a quiet chirp, happy emoji and a circle; no wheels/kicker.',file=sys.stderr)
            try:
                for words in [['led','on','all','blue'],['sound','play','chirp','10'],['screen','show-emoji','happy'],['screen','draw-circle','120','120','20']]:require(call(words,session))
                time.sleep(.3)
            finally:
                # Cleanup every effect even when another command is unsupported.
                for words in [['led','off','all'],['screen','hide-emoji'],['sound','stop']]:
                    try:
                        value=call(words,session)
                        if not value.get('ok'):report.setdefault('cleanup_errors',[]).append(str(value))
                    except Exception as error:report.setdefault('cleanup_errors',[]).append(str(error))
            if report.get('cleanup_errors'):raise RuntimeError('Some effects could not be cleaned up; inspect cleanup_errors')
        if args.motion_ready:
            actions=[['motion','turn-for','right','15'],['forward','50'],['strafe','left','20'],['motion','move-with-vectors','0','10','0','--duration','300ms']]
            for words in actions:
                print('Supervised movement: '+' '.join(words),file=sys.stderr)
                require(call(words,session))
                state=require(call(['info'],session))
                if not state['robot_state']['stopped']:raise RuntimeError('Motion ended without stopped confirmation')
        if args.kicker_ready:
            print('Actuator: one SOFT kick, then place; keep the front clear.',file=sys.stderr)
            require(call(['kicker','kick','soft'],session));require(call(['kicker','place'],session))
        report['completed']=True
    except Exception as error:
        report['completed']=False;report['error']=str(error)
    finally:
        if session and not args.session and not args.keep_session:
            try:call(['session','close'],session)
            except Exception as error:report['close_error']=str(error)
        report['summary']={key:0 for key in ('passed','unsupported','failed')}
        for check in report['checks']:
            check['outcome']=check_outcome(check)
            report['summary'][check['outcome']]+=1
        report['unsupported_or_failed_commands']=[c['command'] for c in report['checks'] if c['outcome']!='passed']
        report['passed']=bool(report.get('completed') and not report['summary']['failed']
                              and not report.get('cleanup_errors') and not report.get('close_error'))
        path=output/('device-'+str(uuid.uuid4())+'.json')
        path.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
        print(json.dumps({'ok':report['passed'],'completed':report.get('completed',False),
                          'summary':report['summary'],'report':str(path),'session':session}))
    return 0 if report['passed'] else 1

if __name__=='__main__':sys.exit(main(parser.parse_args()))
