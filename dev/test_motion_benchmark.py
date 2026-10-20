import runpy
from pathlib import Path
import unittest

evaluate = runpy.run_path(str(Path(__file__).with_name("benchmark-motion.py")))["evaluate"]


class IndependentEvidence(unittest.TestCase):
    def dataset(self):
        trials, observations = [], []
        for speed in (60,90):
            for angle in (-360,-180,-90,90,180,360):
                for i in range(5):
                    label = f"{speed}-{angle}-{i}"
                    trials.append(dict(trial=label,kind="turn",speed=speed,requested_deg=angle))
                    observations.append(dict(trial=label,measured_turn_deg=angle,robot_displaced=False))
        return dict(surface="test",trials=trials), dict(source="physical_angle_reference",observations=observations)

    def test_fastest_requires_every_direction_angle_and_five_independent_samples(self):
        report, observations = self.dataset()
        self.assertEqual(evaluate(report,observations)["fastest_passing_speed"],90)
        observations["observations"][-1]["measured_turn_deg"] += 6
        self.assertEqual(evaluate(report,observations)["fastest_passing_speed"],60)
        observations["observations"] = observations["observations"][1:]
        self.assertIsNone(evaluate(report,observations)["fastest_passing_speed"])

    def test_imu_or_displacement_cannot_validate_physical_accuracy(self):
        report, observations = self.dataset()
        observations["source"] = "robot_imu"
        with self.assertRaises(ValueError):
            evaluate(report,observations)
        observations["source"] = "external_video"
        for item in observations["observations"]:
            item["robot_displaced"] = True
        self.assertIsNone(evaluate(report,observations)["fastest_passing_speed"])
