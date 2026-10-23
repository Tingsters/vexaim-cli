"""Local image-matching controls with generated fixtures, never student photos."""
from pathlib import Path
import tempfile
import unittest

try:
    import cv2
    import numpy as np
except ImportError:
    cv2=None

from camera_search import ReferenceDetector


@unittest.skipIf(cv2 is None,'OpenCV is only a developer-test dependency')
class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        rng=np.random.default_rng(17)
        self.texture=rng.integers(0,256,(180,240),dtype=np.uint8)
        self.texture=cv2.GaussianBlur(self.texture,(3,3),0)
        reference=np.zeros((240,320),np.uint8);reference[30:210,40:280]=self.texture
        cv2.imwrite(str(self.root/'reference.png'),reference)
        self.detector=ReferenceDetector(self.root/'reference.png',(40,30,280,210),'controller')

    def test_translated_object_is_found_without_neural_inference(self):
        scene=np.zeros((480,640),np.uint8);scene[180:360,280:520]=self.texture
        cv2.imwrite(str(self.root/'scene.png'),scene)
        detections,_=self.detector.detect(self.root/'scene.png','controller')
        self.assertEqual(len(detections),1)
        self.assertAlmostEqual(detections[0].box[0],280,delta=4)
        self.assertAlmostEqual(detections[0].box[1],180,delta=4)

    def test_unrelated_texture_and_blank_scene_are_not_the_reference(self):
        rng=np.random.default_rng(81)
        for index,scene in enumerate((rng.integers(0,256,(480,640),dtype=np.uint8),np.zeros((480,640),np.uint8))):
            path=self.root/f'negative-{index}.png';cv2.imwrite(str(path),scene)
            detections,_=self.detector.detect(path,'controller')
            self.assertEqual(detections,[])

    def test_reference_cannot_be_silently_used_for_a_different_object(self):
        with self.assertRaises(ValueError):self.detector.detect(self.root/'reference.png','spinner')

    def test_blank_reference_is_rejected_before_a_search(self):
        path=self.root/'blank.png';cv2.imwrite(str(path),np.zeros((100,100),np.uint8))
        with self.assertRaises(ValueError):ReferenceDetector(path,(0,0,100,100),'controller')


if __name__=='__main__':unittest.main()
