"""Independent search timing/coverage tests; no model, radio or robot required."""
import math
import unittest
from camera_search import Detection, estimate_field_of_view, search_headings, seek, select_target


class Clock:
    now = 0
    def __call__(self): return self.now


class Robot:
    def __init__(self, clock): self.clock, self.heading, self.actions = clock, 0, []
    def turn(self, degrees):
        self.actions.append(('turn', degrees)); self.heading += degrees; self.clock.now += abs(degrees)/90
    def observe(self):
        self.actions.append(('observe', self.heading)); self.clock.now += .5
        return {'path':str(self.heading), 'observation_id':str(len(self.actions)), 'width':640}
    def approach(self, mm): self.actions.append(('approach', mm))
    def stop(self): self.actions.append(('stop',))


class Detector:
    def __init__(self, clock, bearing=180, ambiguous=False): self.clock, self.bearing, self.ambiguous = clock, bearing, ambiguous
    def detect(self, path, query):
        self.clock.now += .1
        heading = float(path)
        difference = (self.bearing-heading+180)%360-180
        if abs(difference) > 25: return [], 100
        box = (280,100,360,200)
        result = [Detection(query,.8,box)]
        if self.ambiguous: result.append(Detection(query,.78,(20,100,100,200)))
        return result, 100


class SearchTests(unittest.TestCase):
    def test_full_sweep_covers_every_azimuth_with_overlap(self):
        for fov in (25, 50, 60, 90):
            headings = search_headings(fov)
            self.assertLess(headings[-1],360)
            for bearing in range(360):
                self.assertLessEqual(min(abs((bearing-h+180)%360-180) for h in headings),fov/2)

    def test_target_starting_behind_is_found_without_an_agent_round_trip(self):
        clock = Clock(); robot = Robot(clock)
        result = seek(robot,Detector(clock),'controller',60,clock=clock)
        self.assertEqual(result['outcome'],'approached')
        self.assertLess(result['elapsed_ms'],15000)
        self.assertIn(('approach',150),robot.actions)
        self.assertEqual(robot.actions[-1],('stop',))
        self.assertFalse(result['arrival_verified'])

    def test_absent_target_does_not_repeat_the_sweep_or_approach(self):
        clock = Clock(); robot = Robot(clock)
        class Empty:
            def detect(self,*args): return [],0
        result=seek(robot,Empty(),'absent',60,clock=clock)
        self.assertEqual(result['outcome'],'not_found')
        self.assertLess(sum(abs(a[1]) for a in robot.actions if a[0]=='turn'),360)
        self.assertFalse(any(a[0]=='approach' for a in robot.actions))

    def test_ambiguous_detections_do_not_authorize_movement(self):
        clock=Clock(); robot=Robot(clock)
        result=seek(robot,Detector(clock,bearing=0,ambiguous=True),'controller',60,clock=clock)
        self.assertEqual(result['outcome'],'ambiguous')
        self.assertEqual(robot.actions,[('observe',0),('stop',)])

    def test_slow_frame_expires_before_motion_even_when_a_target_was_found(self):
        clock=Clock(); robot=Robot(clock)
        def slow_observe():
            clock.now += 16
            return {'path':'0','observation_id':'fresh','width':640}
        robot.observe=slow_observe
        result=seek(robot,Detector(clock,bearing=0),'controller',60,clock=clock)
        self.assertEqual(result['outcome'],'timed_out')
        self.assertEqual(robot.actions,[('stop',)])

    def test_capture_failure_stops_and_never_replays_motion(self):
        clock=Clock(); robot=Robot(clock)
        def fail(): raise RuntimeError('capture interrupted')
        robot.observe=fail
        with self.assertRaisesRegex(RuntimeError,'interrupted'): seek(robot,Detector(clock),'controller',60,clock=clock)
        self.assertEqual(robot.actions,[('stop',)])

    def test_fov_fit_rejects_inconsistent_or_insufficient_measurements(self):
        fx=160/math.tan(math.radians(30))
        samples=[(160+fx*math.tan(math.radians(b)),b) for b in (-20,-10,10,20)]
        self.assertAlmostEqual(estimate_field_of_view(samples),60)
        with self.assertRaises(ValueError): estimate_field_of_view(samples[:1])
        with self.assertRaises(ValueError): estimate_field_of_view(samples+[(250,5)])


if __name__=='__main__': unittest.main()
