import unittest
import cv2
import numpy as np
from turn_frames import analyze


class FrameRegistration(unittest.TestCase):
    def test_blank_scene_does_not_claim_calibration(self):
        blank = np.zeros((480,640),dtype=np.uint8)
        result = analyze(blank,blank)
        self.assertFalse(result["usable"])
        self.assertFalse(result["automatic_correction_enabled"])
        self.assertIsNone(result["robot_yaw_error_deg"])

    def test_known_image_shift_is_measured_without_inventing_robot_yaw(self):
        image = np.random.default_rng(4).integers(0,256,(480,640),dtype=np.uint8)
        shifted = cv2.warpAffine(image,np.float32([[1,0,20],[0,1,0]]),(640,480))
        result = analyze(image,shifted)
        self.assertTrue(result["usable"])
        self.assertAlmostEqual(result["median_horizontal_displacement_px"],20,delta=1)
        self.assertIsNone(result["robot_yaw_error_deg"])
        self.assertFalse(result["physical_accuracy_verified"])

    def test_different_scene_does_not_authorize_a_correction(self):
        rng = np.random.default_rng(12)
        before = rng.integers(0,256,(480,640),dtype=np.uint8)
        after = rng.integers(0,256,(480,640),dtype=np.uint8)
        self.assertFalse(analyze(before,after)["usable"])


if __name__ == "__main__":
    unittest.main()
