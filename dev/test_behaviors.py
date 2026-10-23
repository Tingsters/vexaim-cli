"""Exercise the shipped controller in a small pose-dependent AIM world.

Models independent object geometry, magnetic attachment and delayed vision;
it does not claim to model actual optics, traction or Bluetooth timing.
"""
import contextlib
import io
import json
import math
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEVICE = ROOT / 'cli/vexaim/src/device.py'
BEHAVIORS = ROOT / 'cli/vexaim/src/behaviors.py'


class World:
    def __init__(self, objects=(), *, heading=0, held=None, blind_mm=100,
                 dropout=False, stalled=False, release_stuck=False,
                 frozen_timer=False, frozen_system=False, vision_delay_ms=0):
        self.ms = 0
        self.x = self.y = 0.0
        self.heading = float(heading)
        self.rotation = float(heading)
        self.held = held
        self.objects = [dict(kind=k, x=float(x), y=float(y)) for k, x, y in objects]
        self.blind_mm = blind_mm
        self.dropout = dropout
        self.stalled = stalled
        self.release_stuck = release_stuck
        self.frozen_timer = frozen_timer
        self.frozen_system = frozen_system
        self.vision_delay_ms = vision_delay_ms
        self.motion_state = None
        self.events = []
        self.calls = []
        self.possession_reads = 0
        self.flicker = False
        self.collect_enabled = True
        self.blocked_contact = False
        self.released_until = 0
        self.loop_limit = 0
        self.tags_need_settle = False
        self.still_since = 0
        self.possession_missing = False
        self.acceleration_ms = 0
        self.ns = self.namespace()
        self.robot = self.ns['robot']
        exec(compile(DEVICE.read_text(), str(DEVICE), 'exec'), self.ns)
        exec(compile(BEHAVIORS.read_text(), str(BEHAVIORS), 'exec'), self.ns)

    def log(self, name, *args):
        self.calls.append((round(self.ms), name, *args))

    def step(self, elapsed):
        if self.motion_state and not self.stalled:
            m = self.motion_state
            dt = min(elapsed, m['remaining']) if m['remaining'] is not None else elapsed
            angle = math.radians(self.heading + m.get('angle', 0))
            self.x += math.cos(angle) * m.get('speed', 0) * dt / 1000
            self.y += math.sin(angle) * m.get('speed', 0) * dt / 1000
            self.heading += m.get('turn', 0) * dt / 1000
            self.rotation += m.get('turn', 0) * dt / 1000
            if m['remaining'] is not None:
                m['remaining'] -= dt
                if m['remaining'] <= .01:
                    self.motion_state = None
                    self.still_since = self.ms + dt
            if self.held is None and self.collect_enabled and self.ms > self.released_until:
                for obj in self.objects:
                    if obj['kind'] not in ('BLUE_BARREL','ORANGE_BARREL','SPORTS_BALL'):
                        continue
                    distance, bearing = self.geometry(obj)
                    if distance <= 75 and abs(bearing) < 12:
                        if self.blocked_contact and abs((self.heading+180)%360-180)<20:
                            # A head-on contact pushes instead of attaching.
                            angle=math.radians(self.heading)
                            obj['x']=self.x+75*math.cos(angle)
                            obj['y']=self.y+75*math.sin(angle)
                            continue
                        self.held = obj['kind']
                        self.objects.remove(obj)
                        break
        self.ms += elapsed
        due = [item for item in self.events if item[0] <= self.ms]
        self.events = [item for item in self.events if item[0] > self.ms]
        for _, callback in due:
            callback()

    def wait(self, amount, units='MSEC'):
        amount *= 1000 if units == 'SECONDS' else 1
        while amount > 0:
            delta = min(20, amount)
            self.step(delta)
            amount -= delta
            if self.ms > 125000:
                raise RuntimeError('Independent world time limit')

    def geometry(self, obj):
        dx, dy = obj['x'] - self.x, obj['y'] - self.y
        angle = (math.degrees(math.atan2(dy, dx)) - self.heading + 180) % 360 - 180
        return math.hypot(dx, dy), angle

    def vision(self, target, count=8):
        self.log('vision', target)
        if self.vision_delay_ms:
            self.wait(self.vision_delay_ms)
        if self.dropout and self.ms >= (200 if self.dropout is True else self.dropout):
            return ()
        data = []
        is_tag = target == 'ALL_TAGS' or target.startswith('TAG')
        rotating = self.motion_state is not None and 'turn' in self.motion_state
        if is_tag and self.tags_need_settle and (rotating or self.ms-self.still_since < 240):
            return ()
        for obj in self.objects:
            if obj['kind'] != target and not (target == 'ALL_TAGS' and obj['kind'].startswith('TAG')):
                continue
            d, bearing = self.geometry(obj)
            if d < self.blind_mm or d > 1200 or abs(bearing) > 34:
                continue
            width = min(200, 4000 / d)
            height = min(200, 2400 / d + 20)
            center_y = min(230, 120 + 9000 / d)
            data.append(SimpleNamespace(exists=True, bearing=bearing, width=width,
                height=height, centerX=160+bearing*3, centerY=center_y,
                originX=160+bearing*3-width/2, originY=center_y-height/2,
                id=0, score=95, type=0, rotation=0))
        return tuple(sorted(data, key=lambda o: o.width, reverse=True)[:count])

    def possession(self, cargo):
        self.possession_reads += 1
        return self.held == cargo and not self.possession_missing and not (self.flicker and self.possession_reads % 5 == 0)

    def move(self, distance, angle, speed, units, blocking):
        self.log('move_for', distance, angle, speed, units)
        speed *= 2 if units == 'PERCENT' else 1
        duration = abs(distance) / speed * 1000 + self.acceleration_ms
        self.motion_state = dict(speed=abs(distance)/duration*1000, angle=angle, remaining=duration)
        if blocking:
            self.wait(duration)

    def move_at(self, angle, speed, units):
        self.log('move_at', angle, speed, units)
        self.motion_state = dict(speed=speed * (2 if units == 'PERCENT' else 1), angle=angle, remaining=None)

    def turn(self, direction, speed, units):
        self.log('turn', direction, speed, units)
        self.motion_state = dict(turn=speed * (-1 if direction == 'LEFT' else 1), remaining=None)

    def turn_to(self, heading, speed, units, blocking):
        self.log('turn_to', heading, speed, units)
        delta = (heading-self.heading+180) % 360-180
        duration = abs(delta)/speed*1000
        self.motion_state = dict(turn=speed * (-1 if delta < 0 else 1), remaining=duration)
        if blocking:
            self.wait(duration)

    def stop(self):
        self.log('stop')
        if self.motion_state is not None:
            self.still_since = self.ms
        self.motion_state = None

    def place(self):
        self.log('place')
        if not self.release_stuck and self.held:
            angle = math.radians(self.heading)
            self.objects.append(dict(kind=self.held,x=self.x+80*math.cos(angle),y=self.y+80*math.sin(angle)))
            self.held = None
            self.released_until = self.ms + 1500

    def namespace(self):
        world = self
        class Timer:
            def __init__(self): self.origin=world.ms
            def time(self, units='MSEC'):
                return 0 if world.frozen_timer else (world.ms-self.origin)/(1000 if units=='SECONDS' else 1)
            def reset(self): self.origin=world.ms
            def system(self): return 0 if world.frozen_system else world.ms
            def event(self, callback, delay): world.events.append((world.ms+delay,callback))
        class Thread:
            def __init__(self,fn,args): fn(*args)
        robot=SimpleNamespace(timer=Timer(),is_stopped=lambda:self.motion_state is None,
            inertial=SimpleNamespace(get_heading=lambda:self.heading%360,get_rotation=lambda:self.rotation,is_calibrating=lambda:False),
            vision=SimpleNamespace(get_data=self.vision,model_detection=lambda flag:self.log('models',flag),tag_detection=lambda flag:self.log('tags',flag)),
            move_for=self.move,move_at=self.move_at,turn=self.turn,turn_to=self.turn_to,
            stop_all_movement=self.stop,is_move_active=lambda:self.motion_state is not None and 'speed' in self.motion_state,
            is_turn_active=lambda:self.motion_state is not None and 'turn' in self.motion_state,
            get_x_position=lambda:self.x,get_y_position=lambda:self.y,kicker=SimpleNamespace(place=self.place))
        for cargo in ('BLUE_BARREL','ORANGE_BARREL','SPORTS_BALL'):
            fn=lambda cargo=cargo:self.possession(cargo)
            setattr(robot,'has_'+cargo.lower(),fn)
            setattr(robot.vision,'has_'+cargo.lower(),fn)
        constants='MSEC SECONDS MMPS DPS PERCENT LEFT RIGHT BLUE_BARREL ORANGE_BARREL SPORTS_BALL AIM_ROBOT ALL_TAGS'.split()+['TAG'+str(i) for i in range(38)]
        return dict(robot=robot,Timer=Timer,Thread=Thread,wait=self.wait,**{n:n for n in constants})

    def run(self, source, timeout_ms=30000):
        output=io.StringIO()
        error=None
        with contextlib.redirect_stdout(output):
            try:self.ns['_vx_behavior_exec'](source,timeout_ms)
            except Exception as ex:error=str(ex)
        return error,output.getvalue()


class Behaviors(unittest.TestCase):
    CONFIG='behaviors.configure(move_mmps=150,turn_dps=45,contact_mmps=200,timeout_ms=30000)\n'
    PLAY='behaviors.configure(move_mmps=150,turn_dps=45,tag_turn_dps=90,contact_mmps=200,timeout_ms=30000,verification="contact")\n'

    def test_tags_need_stationary_views_in_both_search_directions(self):
        for target,position,direction in [('TAG0',(0,450),'RIGHT'),('TAG12',(0,-450),'LEFT'),('ALL_TAGS',(-450,0),'RIGHT')]:
            world=World([('TAG12' if target=='ALL_TAGS' else target,*position)],blind_mm=0)
            world.tags_need_settle=True
            error,out=world.run(self.PLAY+'behaviors.find('+target+','+direction+')')
            self.assertIsNone(error,out+'\n'+str(error))
            self.assertIn('stationary_views',out)
            self.assertFalse(any(c[1]=='turn' for c in world.calls),'Tag search must stop between views')
            self.assertLess(world.ms,15000)
            self.assertIsNone(world.motion_state)

    def test_stationary_tag_search_is_bounded_when_marker_absent(self):
        world=World()
        error,out=world.run(self.PLAY+'behaviors.find(TAG0)')
        self.assertIn('not_found',error)
        self.assertLessEqual(sum(c[1]=='turn_to' for c in world.calls),7)
        self.assertLessEqual(abs(world.rotation),360)
        self.assertLess(world.ms,15000)

    def test_fast_game_keeps_going_when_held_cargo_disappears_from_detector(self):
        world=World([('BLUE_BARREL',350,0),('TAG0',0,450)],blind_mm=0)
        world.tags_need_settle=True
        world.possession_missing=True
        error,out=world.run(self.PLAY+'pickup=behaviors.collect(BLUE_BARREL)\ndelivery=behaviors.deliver(BLUE_BARREL,TAG0)\nprint(pickup)\nprint(delivery)\nprint("celebrate")')
        self.assertIsNone(error,out+'\n'+str(error))
        self.assertIsNone(world.held,'Physical simulated cargo was released')
        self.assertIn('contact_assumed',out)
        self.assertIn('place_assumed',out)
        self.assertIsNone(world.ns['pickup']['collected'])
        self.assertIsNone(world.ns['delivery']['delivered'])
        self.assertTrue(world.ns['delivery']['completed'])
        self.assertIn('celebrate',out)
        self.assertFalse(any(c[1]=='move_for' and c[2] in (40,60,80) for c in world.calls))
        self.assertNotIn('contact_retry',out)
        self.assertLess(world.ms,20000)

    def test_contact_limit_can_end_a_play_attempt_without_claiming_attachment(self):
        world=World([('BLUE_BARREL',55,0)],blind_mm=0,stalled=True)
        error,out=world.run(self.PLAY+'pickup=behaviors.collect(BLUE_BARREL)')
        self.assertIsNone(error,out+'\n'+str(error))
        self.assertIsNone(world.held)
        self.assertIsNone(world.ns['pickup']['collected'])
        self.assertTrue(world.ns['pickup']['completed'])
        self.assertLess(world.ms,4000)

    def test_contact_policy_cannot_skip_missing_target_or_invent_carried_cargo(self):
        for body,expected in [('behaviors.collect(BLUE_BARREL)','not_found'),('behaviors.deliver(BLUE_BARREL,TAG0)','cargo_required')]:
            world=World()
            error,out=world.run(self.PLAY+body)
            self.assertIn(expected,error)
            self.assertFalse(any(c[1]=='place' for c in world.calls))

    def test_play_contact_still_obeys_shared_deadline(self):
        world=World([('BLUE_BARREL',55,0)],blind_mm=0,stalled=True)
        error,out=world.run('behaviors.configure(verification="contact",timeout_ms=600)\nbehaviors.collect(BLUE_BARREL)\nprint("celebrate")')
        self.assertIn('deadline',error)
        self.assertNotIn('celebrate',out)
        self.assertLess(world.ms,800)
        self.assertIsNone(world.motion_state)

    def test_play_release_can_finish_without_fabricating_release_confirmation(self):
        world=World([('TAG0',55,0)],held='BLUE_BARREL',blind_mm=0,release_stuck=True)
        error,out=world.run(self.PLAY+'result=behaviors.deliver(BLUE_BARREL,TAG0)\nprint("celebrate")')
        self.assertIsNone(error,out+'\n'+str(error))
        self.assertEqual(world.held,'BLUE_BARREL')
        self.assertTrue(world.ns['result']['completed'])
        self.assertIsNone(world.ns['result']['delivered'])
        self.assertIn('place_assumed',out)
        self.assertIn('celebrate',out)

    def test_tag_view_pause_still_obeys_frozen_clock_watchdog(self):
        world=World(frozen_timer=True,frozen_system=True)
        error,out=world.run('behaviors.configure(timeout_ms=400)\nbehaviors.find(TAG0)')
        self.assertIn('deadline',error)
        self.assertLess(world.ms,600)
        self.assertIsNone(world.motion_state)

    def test_short_reverse_allows_native_acceleration_without_fixed_delay(self):
        world=World(held='BLUE_BARREL')
        world.acceleration_ms=800
        context=world.ns['_VxBehaviors']().begin()
        try:
            context.configure(move_mmps=150)
            self.assertTrue(context.retained('BLUE_BARREL'))
        finally:context.close()
        self.assertLess(world.ms,1500)

    def test_collects_all_cargo_from_different_directions(self):
        for cargo in ('BLUE_BARREL','ORANGE_BARREL','SPORTS_BALL'):
            for position in ((350,0),(0,350),(-350,0)):
                with self.subTest(cargo=cargo,position=position):
                    world=World([(cargo,*position)])
                    error,out=world.run(self.CONFIG+'behaviors.collect('+cargo+')')
                    self.assertIsNone(error,out+'\n'+str(error))
                    self.assertEqual(world.held,cargo)
                    self.assertIsNone(world.motion_state)
                    self.assertLess(world.ms,15000)

    def test_target_drops_below_camera_before_width_threshold(self):
        world=World([('BLUE_BARREL',320,0)],blind_mm=105)
        error,out=world.run(self.CONFIG+'behaviors.collect(BLUE_BARREL)')
        self.assertIsNone(error,out+'\n'+str(error))
        self.assertIn('contacting',out)
        self.assertEqual(world.held,'BLUE_BARREL')

    def test_missing_target_is_one_sweep_not_sixty_seconds(self):
        world=World()
        error,out=world.run(self.CONFIG+'behaviors.collect(BLUE_BARREL)')
        self.assertIn('not_found',error)
        self.assertLessEqual(world.rotation,363)
        self.assertLess(world.ms,10000)
        self.assertEqual(sum(c[1]=='turn' for c in world.calls),1)
        self.assertIsNone(world.motion_state)

    def test_far_target_loss_never_starts_blind_contact(self):
        world=World([('BLUE_BARREL',600,0)],dropout=800)
        error,out=world.run(self.CONFIG+'behaviors.collect(BLUE_BARREL)')
        self.assertIn('target_lost_before_contact',error)
        self.assertNotIn('contacting',out)
        self.assertIsNone(world.motion_state)

    def test_crop_loss_before_normal_contact_width_commits_finite_stroke(self):
        world=World([('BLUE_BARREL',320,0)],blind_mm=190)
        actual=world.vision
        def tilted_barrel(target,count=8):
            objects=actual(target,count)
            for obj in objects:
                obj.width *= 2
                obj.originY=60
                obj.height=30
            return objects
        world.robot.vision.get_data=tilted_barrel
        error,out=world.run(self.CONFIG+'behaviors.collect(BLUE_BARREL)')
        self.assertIsNone(error,out+'\n'+str(error))
        self.assertIn('contacting',out)
        self.assertEqual(world.held,'BLUE_BARREL')

    def test_requested_cargo_already_held_with_empty_frame(self):
        world=World(held='BLUE_BARREL')
        error,out=world.run(self.CONFIG+'behaviors.collect(BLUE_BARREL)')
        self.assertIsNone(error,out)
        self.assertFalse(any(c[1] in ('move_for','move_at','turn') for c in world.calls))

    def test_wrong_cargo_rejected_without_motion(self):
        world=World(held='ORANGE_BARREL')
        error,out=world.run(self.CONFIG+'behaviors.collect(BLUE_BARREL)')
        self.assertIn('wrong_cargo',error)
        self.assertFalse(any(c[1] in ('move_for','move_at','turn') for c in world.calls))

    def test_tag_and_robot_have_different_stand_offs(self):
        for target,distance,expected_move in [('TAG0',55,False),('AIM_ROBOT',36,True)]:
            world=World([(target,distance,0)],blind_mm=0)
            error,out=world.run(self.CONFIG+'behaviors.approach('+target+')')
            # Tag width 72 already exceeds 60; AIM width 111 is below 140.
            self.assertEqual(any(c[1]=='move_at' for c in world.calls),expected_move)
            self.assertIsNone(error,out+'\n'+str(error))

    def test_named_macro_uses_the_same_controller_and_reports_progress(self):
        world=World(held='BLUE_BARREL')
        action=dict(command='macro get-blue-barrel',method='_vx_macro',kind='macro',
                    args=['collect',{'constant':'BLUE_BARREL'}],timeout=3,no_wait=False)
        result=world.ns['_vx_dispatch'](action)
        job=result['action']
        self.assertEqual(job['state'],'completed')
        self.assertTrue(job['value']['collected'])
        self.assertTrue(job['stopped_confirmed'])

    def test_cancel_during_native_read_cannot_dispatch_another_move(self):
        world=World()
        job={'cancel_requested':False}
        context=world.ns['_VxBehaviors'](30000,job)
        context.begin()
        def cancelled(*args):
            job['cancel_requested']=True
            return ()
        world.robot.vision.get_data=cancelled
        try:
            with self.assertRaisesRegex(RuntimeError,'cancelled'):
                context.find('BLUE_BARREL')
        finally:context.close()
        self.assertFalse(any(c[1]=='turn' for c in world.calls))

    def test_collect_deliver_and_effect_share_single_context(self):
        world=World([('ORANGE_BARREL',350,0),('TAG0',0,450)],blind_mm=0)
        error,out=world.run(self.CONFIG+'behaviors.collect(ORANGE_BARREL)\nbehaviors.deliver(ORANGE_BARREL,TAG0)\nprint("celebrate")')
        self.assertIsNone(error,out+'\n'+str(error))
        self.assertIsNone(world.held)
        self.assertEqual(sum(c[1]=='place' for c in world.calls),1)
        self.assertIn('celebrate',out)
        self.assertLess(world.ms,30000)

    def test_missing_marker_does_not_place_or_celebrate(self):
        world=World(held='BLUE_BARREL')
        error,out=world.run(self.CONFIG+'behaviors.deliver(BLUE_BARREL,TAG0)\nprint("celebrate")')
        self.assertIn('not_found',error)
        self.assertNotIn('celebrate',out)
        self.assertFalse(any(c[1]=='place' for c in world.calls))
        self.assertEqual(world.held,'BLUE_BARREL')

    def test_release_failure_prevents_success_effect(self):
        world=World([('TAG0',55,0)],held='BLUE_BARREL',blind_mm=0,release_stuck=True)
        error,out=world.run(self.CONFIG+'behaviors.deliver(BLUE_BARREL,TAG0)\nprint("celebrate")')
        self.assertIn('release_not_confirmed',error)
        self.assertNotIn('celebrate',out)

    def test_intermittent_possession_is_tolerated(self):
        world=World([('TAG0',55,0)],held='BLUE_BARREL',blind_mm=0)
        world.flicker=True
        error,out=world.run(self.CONFIG+'behaviors.deliver(BLUE_BARREL,TAG0)')
        self.assertIsNone(error,out+'\n'+str(error))

    def test_no_magnet_contact_has_only_one_retry(self):
        world=World([('BLUE_BARREL',250,0)],blind_mm=0)
        world.collect_enabled=False
        error,out=world.run(self.CONFIG+'behaviors.collect(BLUE_BARREL)')
        self.assertIsNotNone(error)
        self.assertLessEqual(out.count('"phase": "contact_retry"'),1)
        self.assertLessEqual(sum(c[1]=='move_for' and c[2]==200 for c in world.calls),2)
        self.assertIsNone(world.motion_state)

    def test_single_retry_changes_contact_angle_with_holonomic_motion(self):
        world=World([('BLUE_BARREL',300,0)],blind_mm=0)
        world.blocked_contact=True
        error,out=world.run(self.CONFIG+'behaviors.collect(BLUE_BARREL)')
        self.assertIsNone(error,out+'\n'+str(error))
        self.assertEqual(world.held,'BLUE_BARREL')
        self.assertEqual(out.count('"phase": "contact_retry"'),1)
        self.assertTrue(any(c[1]=='move_for' and c[2:4]==(80,90) for c in world.calls))

    def test_system_clock_bounds_a_frozen_private_timer(self):
        world=World(frozen_timer=True)
        error,out=world.run('behaviors.configure(timeout_ms=500)\nbehaviors.find(BLUE_BARREL)')
        self.assertIn('deadline',error)
        self.assertLess(world.ms,700)
        self.assertIsNone(world.motion_state)

    def test_callback_stops_even_when_both_reported_clocks_freeze(self):
        world=World(frozen_timer=True,frozen_system=True)
        error,out=world.run('behaviors.configure(timeout_ms=500)\nbehaviors.find(BLUE_BARREL)')
        self.assertIn('deadline',error)
        self.assertLess(world.ms,700)
        self.assertIsNone(world.motion_state)

    def test_slow_sdk_call_records_failure_and_does_not_start_movement(self):
        world=World(vision_delay_ms=1500)
        error,out=world.run('behaviors.configure(timeout_ms=500)\nbehaviors.find(BLUE_BARREL)')
        self.assertIn('vision.get_data',error)
        self.assertFalse(any(c[1]=='turn' for c in world.calls))

    def test_obsolete_callback_cannot_stop_next_activity(self):
        world=World(held='BLUE_BARREL')
        self.assertIsNone(world.run('behaviors.configure(timeout_ms=500)\nbehaviors.collect(BLUE_BARREL)')[0])
        before=len(world.calls)
        self.assertIsNone(world.run('behaviors.configure(timeout_ms=2000)\nrobot.move_at(0,80,MMPS)\nwait(700,MSEC)')[0])
        stops=[c for c in world.calls[before:] if c[1]=='stop']
        self.assertEqual(len(stops),1,'Only the second activity cleanup may stop')

    def test_student_cannot_redirect_final_cleanup_by_rebinding_global(self):
        world=World()
        error,out=world.run('behaviors = None\nrobot.move_at(0,80,MMPS)\nraise RuntimeError("boom")')
        self.assertIn('boom',error)
        self.assertIsNone(world.motion_state)

    def test_expired_body_cannot_report_activity_success(self):
        world=World()
        error,out=world.run('behaviors.configure(timeout_ms=300)\nwait(500,MSEC)')
        self.assertIn('deadline',error)
        self.assertNotIn('behavior_complete',out)

    def test_invalid_configuration_does_not_move(self):
        for source in ('behaviors.configure(move_mmps=201)','behaviors.configure(turn_dps=float("nan"))',
                       'behaviors.configure(timeout_ms=60000)','behaviors.collect(TAG0)',
                       'behaviors.configure(verification="guess")','behaviors.configure(tag_turn_dps=151)'):
            world=World()
            error,out=world.run(source)
            self.assertIsNotNone(error)
            self.assertFalse(any(c[1] in ('move_for','move_at','turn') for c in world.calls))


if __name__ == '__main__':
    unittest.main()
