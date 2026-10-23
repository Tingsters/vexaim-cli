"""Short, front-loaded acceptance through an existing Bluetooth owner.

No pairing, reconnection, user prompts, program uploads or automatic motion
replays. Default is stationary. Motion requires --motion-ready at invocation.
All results/photos remain local; missing targets end the batch.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time

TIMING = '''import json
clock = Timer()
origin = robot.timer.system()
ticks = []
def tick():
    ticks.append(robot.timer.system() - origin)
robot.timer.event(tick, 400)
wait(15, MSEC)
reads = []
for _ in range(6):
    before = robot.timer.system()
    data = robot.vision.get_data(BLUE_BARREL, 4)
    seen = [bool(data[n].exists) for n in range(min(4,len(data)))]
    robot.has_blue_barrel()
    reads.append(robot.timer.system()-before)
    wait(100,MSEC)
print(json.dumps({'system_ms':robot.timer.system()-origin,
    'timer_ms':clock.time(MSEC),'callback_ms':ticks,'read_ms':reads,
    'stopped':robot.is_stopped()}))
'''


def last_result(text):
    rows=[]
    for line in text.splitlines():
        try:
            value=json.loads(line)
            if isinstance(value,dict):rows.append(value)
        except ValueError:pass
    return next((r for r in reversed(rows) if r.get('event')=='result' or 'ok' in r),{})


def timing_passed(result):
    measurement=result.get('measurement') or {}
    callbacks=measurement.get('callback_ms',[])
    return (result.get('ok') is True and measurement.get('stopped') is True
        and len(callbacks)==1 and 300<=callbacks[0]<=700
        and 500<=measurement.get('system_ms',0)<=1500
        and abs(measurement.get('system_ms',0)-measurement.get('timer_ms',-10000))<=100
        and len(measurement.get('read_ms',[]))==6
        and max(measurement['read_ms'])<500)


def run(args, runner=subprocess.run):
    output=args.output_dir.resolve();output.mkdir(parents=True,exist_ok=True)
    report={'passed':False,'scope':'Bluetooth AIM behavior acceptance',
            'motion_ready':args.motion_ready,'samples':[],
            'physical_attachment_independently_verified':False}
    began=time.monotonic()
    def call(label,words,source=None,seconds=90):
        command=[str(args.tool.resolve()),'--json','--session',args.session]+words
        if source is not None:
            path=output/(label+'.py');path.write_text(source,encoding='utf-8')
            command+=['-f',str(path)]
        response=runner(command,capture_output=True,text=True,timeout=seconds)
        (output/(label+'.jsonl')).write_text(response.stdout,encoding='utf-8')
        (output/(label+'.stderr')).write_text(response.stderr,encoding='utf-8')
        result=last_result(response.stdout)
        report['samples'].append({'label':label,'result':result,'exit_code':response.returncode})
        if not result.get('ok') or response.returncode:
            raise RuntimeError(label+': '+str(result.get('error') or result.get('stderr') or 'failed'))
        return result
    try:
        status=call('status',['session','status'])
        if status.get('transport')!='bluetooth':raise RuntimeError('Bluetooth session required')
        live=call('before',['info'])
        state=live.get('robot_state',{})
        if state.get('stopped') is not True or state.get('battery_pct',0)<35:
            raise RuntimeError('Need stopped robot and at least 35% battery; no further setup will be requested')
        timing=call('timing',['exec','--timeout','8'],TIMING,seconds=75)
        if not timing_passed(timing):raise RuntimeError('Stationary timing/callback gate failed')
        smoke=call('behavior-smoke',['exec','--behaviors','--timeout','5'],
                   'behaviors.configure(timeout_ms=1000)\nprint("helpers ready")\n')
        if args.motion_ready:
            source=('import json\nbehaviors.configure(move_mmps=150,turn_dps=45,contact_mmps=200,timeout_ms=30000)\n'
                    'pickup=behaviors.collect('+args.cargo+')\n')
            if args.tag is not None:
                source+='delivery=behaviors.deliver('+args.cargo+',Tagdesc('+str(args.tag)+'))\n'
                source+='print(json.dumps({"pickup":pickup,"delivery":delivery}))\n'
            else:source+='print(json.dumps({"pickup":pickup}))\n'
            result=call('cargo',['exec','--behaviors','--timeout','40'],source,seconds=110)
            measurement=result.get('measurement') or {}
            if not measurement.get('pickup',{}).get('collected'):
                raise RuntimeError('No collection evidence')
            if args.tag is not None and not measurement.get('delivery',{}).get('delivered'):
                raise RuntimeError('No release evidence')
        after=call('after',['info'])
        if after.get('robot_state',{}).get('stopped') is not True:
            raise RuntimeError('Final stopped state not confirmed')
        report['passed']=True
    except (RuntimeError,OSError,subprocess.TimeoutExpired) as error:
        report['error']=str(error)
        # A stop is not a replay. Leave the persistent owner available to its user.
        try:call('stop',['stop'],seconds=15)
        except Exception as cleanup:report['cleanup_error']=str(cleanup)
    finally:
        report['elapsed_s']=round(time.monotonic()-began,3)
        (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tool',type=Path,required=True)
    parser.add_argument('--session',required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--motion-ready',action='store_true',help='Initial setup completed; allow collection and optional delivery')
    parser.add_argument('--cargo',choices=('BLUE_BARREL','ORANGE_BARREL','SPORTS_BALL'),default='BLUE_BARREL')
    parser.add_argument('--tag',type=int,choices=range(38))
    args=parser.parse_args()
    report=run(args)
    print(json.dumps({'passed':report['passed'],'report':str((args.output_dir/'report.json').resolve())}))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
