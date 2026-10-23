"""Independent fake AIM: method signatures, scheduling, watchdog and callbacks."""
import contextlib
import io
import json
import re
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

RUNTIME = Path(__file__).resolve().parents[1] / 'cli/vexaim/src/device.py'

class DeviceRuntime(unittest.TestCase):
    def setUp(self):
        self.t = 0
        self.calls = []
        self.threads = []
        self.active_until = 0
        self.stalled = False
        test = self
        class Timer:
            def __init__(self): self.start = test.t
            def time(self, unit): return test.t - self.start
            def reset(self): self.start = test.t
        class Thread:
            def __init__(self, fn, args): test.threads.append((fn, args))
        def wait(n, unit):
            self.t += n
            # Reset the PUBLIC timer repeatedly during a stalled action.
            robot.timer.reset()
        def move_for(distance, angle, velocity, units, blocking):
            self.calls.append(('move', distance, angle, velocity, units, blocking))
            self.active_until = self.t + 200
        def turn_for(direction, angle, velocity, units, blocking):
            self.calls.append(('turn', direction, angle, velocity, units, blocking))
            self.active_until = self.t + 200
        def vectors(forward, rightward, rotation):
            self.calls.append(('vectors', forward, rightward, rotation))
            self.active_until = self.t + 50000
        def stop():
            self.calls.append(('stop',))
            self.active_until = self.t
            self.stalled = False
        robot = SimpleNamespace(
            move_for=move_for, turn_for=turn_for, move_with_vectors=vectors,
            timer=Timer(), stop_all_movement=stop,
            is_stopped=lambda: self.t >= self.active_until and not self.stalled,
            is_move_active=lambda: self.t < self.active_until or self.stalled,
            is_turn_active=lambda: False,
            get_x_position=lambda: 0, get_y_position=lambda: 0,
            inertial=SimpleNamespace(is_calibrating=lambda: False, get_heading=lambda: 90, get_rotation=lambda: 450),
            led=SimpleNamespace(on=lambda *a: self.calls.append(('led', *a))),
            vision=SimpleNamespace(get_data=lambda target, count: [], has_sports_ball=lambda: False),
            screen=SimpleNamespace(print_at=lambda text, *, x, y: self.calls.append(('print_at', text, x, y))),
        )
        self.ns = dict(robot=robot, Timer=Timer, Thread=Thread, wait=wait, MSEC=0, DPS='dps', MMPS='mmps', RIGHT='right', LEFT='left', BLUE='blue', ALL_LEDS=6, ALL_AIOBJS=100)
        exec(compile(RUNTIME.read_text(), str(RUNTIME), 'exec'), self.ns)
        behavior_runtime = RUNTIME.with_name('behaviors.py')
        exec(compile(behavior_runtime.read_text(), str(behavior_runtime), 'exec'), self.ns)

    def action(self, method='robot.move_for', args=None, kind='motion', **options):
        return dict(command='test', method=method, args=[200,90] if args is None else args, kind=kind,
                    timeout=1, duration_ms=None, no_wait=False, velocity=None,
                    velocity_units=None, sample_ms=None, **options)

    def dispatch(self, action): return self.ns['_vx_dispatch'](action)
    def finish(self):
        fn, args = self.threads.pop(0)
        fn(*args)

    def test_native_signature_and_no_wait_survives_caller(self):
        a = self.action()
        result = self.dispatch(a)
        self.assertEqual(self.calls, [])
        self.finish()
        self.assertEqual(self.calls[0], ('move', 200, 90, 80, 'mmps', False))
        self.assertEqual(self.ns['_vx_action_status'](result['action']['id'])['state'], 'completed')

    def test_full_turn_preserved(self):
        self.dispatch(self.action('robot.turn_for', [{'constant':'LEFT'}, 360]))
        self.finish()
        self.assertEqual(self.calls[0], ('turn', 'left', 360, 30, 'dps', False))

    def test_vectors_no_host_mixer_and_stops(self):
        a = self.action('robot.move_with_vectors', [0,25,-20], 'continuous')
        a['duration_ms'] = 200
        result = self.dispatch(a)
        self.finish()
        self.assertEqual(self.calls[0], ('vectors',0,25,-20))
        self.assertTrue(self.ns['_vx_action_status'](result['action']['id'])['stopped_confirmed'])

    def test_conflicting_motion_rejected_but_lights_allowed(self):
        self.dispatch(self.action())
        self.assertTrue(self.dispatch(self.action())['rejected'])
        self.dispatch(self.action('robot.led.on', [{'constant':'ALL_LEDS'},{'constant':'BLUE'}], 'write'))
        self.assertEqual(self.calls, [('led',6,'blue')])

    def test_public_timer_cannot_defeat_deadline(self):
        result = self.dispatch(self.action())
        self.stalled = True
        self.finish()
        job = self.ns['_vx_action_status'](result['action']['id'])
        self.assertEqual(job['state'], 'failed')
        self.assertIn('deadline',job['error'])
        self.assertLessEqual(self.t,1100)
        self.assertEqual(self.calls[-1], ('stop',))

    def test_empty_vision_is_empty_not_index_error(self):
        result = self.dispatch(self.action('robot.vision.get_data',[{'constant':'ALL_AIOBJS'},8],'vision'))
        self.assertEqual(result, {'value': []})

    def test_collect_requires_the_requested_cargo_class(self):
        for requested, held in [('ORANGE_BARREL', 'BLUE_BARREL'),
                                ('BLUE_BARREL', 'ORANGE_BARREL'),
                                ('SPORTS_BALL', 'BLUE_BARREL'),
                                ('ORANGE_BARREL', 'SPORTS_BALL'),
                                ('ORANGE_BARREL', 'ORANGE_BARREL'),
                                ('BLUE_BARREL', 'BLUE_BARREL'),
                                ('SPORTS_BALL', 'SPORTS_BALL')]:
            with self.subTest(requested=requested, held=held):
                self.setUp()
                for name in ('ORANGE_BARREL', 'BLUE_BARREL', 'SPORTS_BALL'):
                    self.ns[name] = name
                vision = self.ns['robot'].vision
                vision.get_data = lambda *args: [SimpleNamespace(exists=True, centerX=160, width=30)]
                vision.has_any_barrel = lambda: held.endswith('BARREL')
                vision.has_sports_ball = lambda: held == 'SPORTS_BALL'
                vision.has_orange_barrel = lambda: held == 'ORANGE_BARREL'
                vision.has_blue_barrel = lambda: held == 'BLUE_BARREL'
                self.ns['robot'].move_at = lambda *args: self.calls.append(('move_at', *args))
                result = self.dispatch(self.action('_vx_macro',
                    ['collect', {'constant': requested}], 'macro'))
                self.finish()
                job = self.ns['_vx_action_status'](result['action']['id'])
                if requested == held:
                    self.assertEqual(job['state'], 'completed')
                    self.assertTrue(job['value']['collected'])
                else:
                    self.assertEqual(job['state'], 'failed')
                    self.assertIn('wrong_cargo', job['error'])
                    self.assertIsNone(job.get('value'))
                self.assertTrue(job['stopped_confirmed'])

    def test_vision_dispatch_with_aim_micropython_string_semantics(self):
        # Live AIM core 1.22.0 rejects tuple suffixes, unlike desktop Python.
        class AimString(str):
            def endswith(self, suffix):
                if not isinstance(suffix, str):
                    raise TypeError("can't convert 'tuple' object to str implicitly")
                return super().endswith(suffix)
        objects = [SimpleNamespace(exists=False), SimpleNamespace(exists=True, width=42)]
        self.ns['robot'].vision.get_data = lambda target, count: objects
        self.ns['robot'].vision.take_snapshot = lambda target, count: objects
        for method in ('get_data', 'take_snapshot'):
            with self.subTest(method=method):
                result = self.dispatch(self.action(AimString('robot.vision.' + method),
                                                   [{'constant':'ALL_AIOBJS'},8], 'vision'))
                self.assertEqual(len(result['value']), 1)
                self.assertEqual(result['value'][0]['width'], 42)

    def test_vision_properties_and_missing_firmware(self):
        self.assertEqual(self.ns['_vx_plain'](SimpleNamespace(exists=True,width=42))['width'],42)
        result=self.dispatch(self.action('robot.link.is_connected', [], 'read'))
        self.assertTrue(result['rejected'])
        self.assertIn('unsupported_firmware',result['error'])

    def test_screen_print_at_uses_keyword_coordinates(self):
        self.dispatch(self.action('robot.screen.print_at',['hello',20,30],'print-at'))
        self.assertEqual(self.calls,[('print_at','hello',20,30)])

    def test_large_results_are_paced_and_remain_json(self):
        value={'items':list(range(1000))}
        out=io.StringIO()
        with contextlib.redirect_stdout(out): self.ns['_vx_print'](value)
        self.assertEqual(json.loads(out.getvalue()),value)
        self.assertGreater(self.t,100)

    def test_small_results_have_no_pacing_delay(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out): self.ns['_vx_print']({'value':1})
        self.assertEqual(json.loads(out.getvalue()),{'value':1})
        self.assertEqual(self.t,0)

    def test_oversized_result_rejected_before_partial_output(self):
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaisesRegex(RuntimeError,'16 KiB'):
                self.ns['_vx_print']({'items':'x'*16384})
        self.assertEqual(out.getvalue(),'')

    def test_result_limit_and_chunk_boundaries_count_utf8_bytes(self):
        self.ns['_vx_json'] = SimpleNamespace(dumps=lambda value:json.dumps(value,ensure_ascii=False))
        class Output(io.StringIO):
            def write(self, text):
                self_max = len(text.encode('utf-8'))
                if self_max > 128:
                    raise AssertionError('Console write exceeds byte budget')
                return super().write(text)
        out = Output()
        value = {'text': '\U0001f642\u673a\u5668\u4eba' * 100}
        with contextlib.redirect_stdout(out): self.ns['_vx_print'](value)
        self.assertEqual(json.loads(out.getvalue()),value)
        with contextlib.redirect_stdout(out):
            with self.assertRaisesRegex(RuntimeError,'16 KiB'):
                self.ns['_vx_print']({'text':'\U0001f642'*5000})

    def test_cancel_before_dispatch_never_starts_motors(self):
        result=self.dispatch(self.action())
        self.ns['_vx_action_cancel'](result['action']['id'])
        self.finish()
        self.assertFalse(any(c[0]=='move' for c in self.calls))

    def test_completion_is_published_only_after_delayed_stop(self):
        robot=self.ns['robot']
        original_wait=self.ns['wait']
        states=[]
        def delayed_stop():
            self.active_until=self.t+200
        robot.stop_all_movement=delayed_stop
        result=self.dispatch(self.action())
        identifier=result['action']['id']
        def watch_wait(n,unit):
            states.append(self.ns['_vx_action_status'](identifier)['state'])
            original_wait(n,unit)
        self.ns['wait']=watch_wait
        self.finish()
        self.assertTrue(all(s=='running' for s in states))
        self.assertTrue(self.ns['_vx_action_status'](identifier)['stopped_confirmed'])

    def test_missing_selector_rejects_without_transmitting(self):
        result=self.dispatch(self.action('robot.vision.get_data',[{'constant':'MISSING'},8],'vision'))
        self.assertTrue(result['rejected'])
        self.assertEqual(self.calls,[])

    def test_vision_selector_on_sensor_object_is_supported(self):
        self.ns['robot'].vision.ALL_AIOBJECTS=99
        self.assertEqual(self.ns['_vx_arg']({'constant':'ALL_AIOBJECTS'}),99)

    def test_one_stick_uses_actual_constructor(self):
        self.ns['Onestick']=lambda:SimpleNamespace(is_connected=lambda:True)
        result=self.dispatch(self.action('onestick.is_connected',[],'read'))
        self.assertEqual(result,{'value':True})

    def test_emoji_uses_firmware_exported_aliases(self):
        happy = object()
        forward = object()
        self.ns['Emoji'] = SimpleNamespace(HAPPY=happy)
        self.ns['EmojiLook'] = SimpleNamespace(LOOK_FORWARD=forward)
        self.ns['robot'].screen.show_emoji = lambda emoji, look:self.calls.append(('emoji',emoji,look))
        result = self.dispatch(self.action('robot.screen.show_emoji',
            [{'constant':'HAPPY'},{'constant':'LOOK_FORWARD'}], 'write'))
        self.assertEqual(result,{'value':None})
        self.assertEqual(self.calls,[('emoji',happy,forward)])

    def test_timer_watch_rearms_and_deactivates_callbacks(self):
        pending=[]
        self.ns['robot'].timer.event=lambda callback,delay:pending.append((self.t+delay,callback))
        original_wait=self.ns['wait']
        def wait(n,unit):
            original_wait(n,unit)
            for due,callback in pending[:]:
                if self.t>=due:
                    pending.remove((due,callback));callback()
        self.ns['wait']=wait
        action=self.action('_vx_watch',['timer.event'],'events')
        action['duration_ms']=200
        for _ in range(2):
            result=self.dispatch(action)
            self.assertEqual(len(result['value']['events']),1)
        watcher=self.ns['_vx_watchers']['timer.event']
        watcher['callback']()
        self.assertEqual(len(watcher['events']),1)
        self.assertFalse(watcher['active'])

    def test_thread_constructor_failure_does_not_leave_ghost_motion(self):
        def broken_thread(*args):raise RuntimeError('thread unavailable')
        self.ns['Thread']=broken_thread
        with self.assertRaisesRegex(RuntimeError,'thread unavailable'):self.dispatch(self.action())
        self.assertFalse(self.ns['_vx_busy']())
        self.assertEqual(self.calls,[])

    def test_direction_and_acceleration_constants_do_not_resolve_as_sounds(self):
        del self.ns['LEFT']
        self.ns['TurnType']=SimpleNamespace(LEFT='turn-left')
        self.ns['AccelerationType']=SimpleNamespace(FORWARD='acceleration-forward')
        self.ns['SoundType']=SimpleNamespace(LEFT='sound-left',FORWARD='sound-forward')
        self.assertEqual(self.ns['_vx_arg']({'constant':'LEFT'}),'turn-left')
        self.assertEqual(self.ns['_vx_arg']({'constant':'FORWARD'}),'acceleration-forward')

class ReplPreamble(unittest.TestCase):
    def test_existing_robot_does_not_skip_missing_api_imports(self):
        self.check_preamble(existing=True)

    def test_new_robot_is_constructed_only_once_across_prepared_calls(self):
        self.check_preamble(existing=False)

    def check_preamble(self, existing):
        rust=RUNTIME.with_name('repl.rs').read_text()
        literal=re.search(r'pub const PREAMBLE: &str = ("(?:\\.|[^"\\])*");',rust).group(1)
        preamble=json.loads(literal)
        constructors=[]
        robot=object()
        vex=ModuleType('vex')
        def construct():
            constructors.append(True)
            return robot
        vex.Robot=construct
        constants=ModuleType('vex_globals')
        constants.ALL_LEDS=6;constants.HAPPY=object()
        namespace={'student_value':42}
        if existing:namespace['robot']=robot
        with patch.dict(sys.modules,{'vex':vex,'vex_globals':constants}):
            exec(preamble,namespace)
            # Simulate a retained robot with API globals removed between calls.
            del namespace['ALL_LEDS']
            exec(preamble,namespace)
        self.assertIs(namespace['robot'],robot)
        self.assertEqual(namespace['ALL_LEDS'],6)
        self.assertIs(namespace['HAPPY'],constants.HAPPY)
        self.assertEqual(namespace['student_value'],42)
        self.assertEqual(len(constructors),0 if existing else 1)

if __name__=='__main__': unittest.main()
