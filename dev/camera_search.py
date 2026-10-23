"""Developer-only local perception/search prototype. No camera/network use on import.

Model downloads are explicit preparation; photographs are processed locally.
No new student CLI command or model dependency is installed by the workshop.
"""
import argparse
from dataclasses import dataclass, asdict
import json
import math
from pathlib import Path
import statistics
import time

MODEL = 'IDEA-Research/grounding-dino-tiny'
REVISION = 'a2bb814dd30d776dcf7e30523b00659f4f141c71'


def percentile(values, fraction=.95):
    if not values:
        return None
    values = sorted(values)
    return values[max(0, math.ceil(len(values)*fraction)-1)]


def search_headings(field_of_view, overlap=.2):
    """One sweep, including the initial view; no unbounded repeated revolutions."""
    if not 20 <= field_of_view <= 120 or not 0 < overlap < .5:
        raise ValueError('A measured horizontal field of view between 20 and 120 degrees is required')
    count = math.ceil(360/(field_of_view*(1-overlap)))
    return [i*360/count for i in range(count)]


def estimate_field_of_view(samples):
    """Fit pinhole focal length from native 320-wide detection centres/bearings.

    This is a test calibration, not an assertion that the JPEG has identical FOV.
    Callers must verify native/JPEG correspondence before using it for movement.
    """
    focal = []
    for center, bearing in samples:
        if abs(center-160) >= 15 and 3 <= abs(bearing) <= 40:
            value = (center-160)/math.tan(math.radians(bearing))
            if value > 0:
                focal.append(value)
    if len(focal) < 3:
        raise ValueError('At least three off-centre native calibration samples are required')
    median = statistics.median(focal)
    if max(abs(v-median)/median for v in focal) > .15:
        raise ValueError('Native bearing calibration is inconsistent')
    return math.degrees(2*math.atan(160/median))


@dataclass(frozen=True)
class Detection:
    label: str
    score: float
    box: tuple


def select_target(detections, minimum=.35):
    candidates = sorted((d for d in detections if d.score >= minimum), key=lambda d: d.score, reverse=True)
    if not candidates:
        return 'not_found', None
    if len(candidates) > 1 and candidates[0].score-candidates[1].score < .1:
        return 'ambiguous', None
    return 'found', candidates[0]


class ReferenceDetector:
    """Match an agent-selected reference crop locally, without a neural model.

    This is visual memory of an already identified object, not recognition of a
    never-seen object category. A changed view can legitimately fail to match.
    """
    def __init__(self, path, box, label):
        import cv2
        self.cv2,self.label=cv2,label
        image=cv2.imread(str(path),cv2.IMREAD_GRAYSCALE)
        if image is None: raise ValueError('Reference image cannot be decoded')
        x1,y1,x2,y2=map(int,box)
        if not (0<=x1<x2<=image.shape[1] and 0<=y1<y2<=image.shape[0]):
            raise ValueError('Reference crop must lie inside the image')
        self.reference=image[y1:y2,x1:x2]
        cv2.setNumThreads(4)
        self.features_engine=cv2.SIFT_create(nfeatures=800,contrastThreshold=.01)
        self.points,self.features=self.features_engine.detectAndCompute(self.reference,None)
        if self.features is None or len(self.features)<12:
            raise ValueError('Reference crop has too little texture for matching')

    def detect(self,path,query):
        import numpy as np
        cv2=self.cv2
        if query!=self.label: raise ValueError('A visual reference is bound to its original object label')
        began=time.perf_counter()
        image=cv2.imread(str(path),cv2.IMREAD_GRAYSCALE)
        if image is None: raise ValueError('Camera observation cannot be decoded')
        points,features=self.features_engine.detectAndCompute(image,None)
        result=[]
        if features is not None and len(features)>=12:
            matches=cv2.BFMatcher(cv2.NORM_L2).knnMatch(self.features,features,k=2)
            good=[pair[0] for pair in matches if len(pair)==2 and pair[0].distance<.7*pair[1].distance]
            if len(good)>=12:
                source=np.float32([self.points[m.queryIdx].pt for m in good])
                destination=np.float32([points[m.trainIdx].pt for m in good])
                transform,mask=cv2.findHomography(source,destination,cv2.RANSAC,3)
                if transform is not None and mask is not None and int(mask.sum())>=10 and mask.mean()>=.55:
                    h,w=self.reference.shape
                    corners=np.float32([[0,0],[w,0],[w,h],[0,h]]).reshape(-1,1,2)
                    projected=cv2.perspectiveTransform(corners,transform)
                    polygon=projected.reshape(-1,2)
                    area=abs(cv2.contourArea(projected))
                    if cv2.isContourConvex(projected) and 400<=area<=image.size*.9 and np.isfinite(polygon).all():
                        lower=polygon.min(axis=0);upper=polygon.max(axis=0)
                        if (lower>=0).all() and upper[0]<=image.shape[1] and upper[1]<=image.shape[0]:
                            result=[Detection(self.label,float(mask.mean()),tuple(map(float,(*lower,*upper))))]
        return result,(time.perf_counter()-began)*1000


class GroundingDetector:
    def __init__(self, download=False, threads=4, short_edge=480):
        import torch
        from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
        torch.set_num_threads(threads)
        self.torch = torch
        self.short_edge = short_edge
        kwargs = dict(revision=REVISION, local_files_only=not download, trust_remote_code=False)
        self.processor = AutoProcessor.from_pretrained(MODEL, **kwargs)
        self.model = AutoModelForZeroShotObjectDetection.from_pretrained(
            MODEL, use_safetensors=True, **kwargs).to('cpu').eval()

    def detect(self, path, query):
        from PIL import Image
        query = query.strip().lower().rstrip('.')+'.'
        if not query.strip('.'):
            raise ValueError('An object description is required')
        with Image.open(path) as source:
            image = source.convert('RGB')
        started = time.monotonic()
        inputs = self.processor(images=image, text=query, return_tensors='pt',
            size={'shortest_edge':self.short_edge, 'longest_edge':round(self.short_edge*5/3)})
        with self.torch.inference_mode():
            outputs = self.model(**inputs)
        results = self.processor.post_process_grounded_object_detection(
            outputs, inputs.input_ids, box_threshold=.25, text_threshold=.25,
            target_sizes=[(image.height, image.width)])[0]
        labels = results.get('text_labels', results.get('labels', []))
        detections = [Detection(str(label), float(score), tuple(float(v) for v in box))
            for label, score, box in zip(labels, results['scores'], results['boxes'])]
        return detections, (time.monotonic()-started)*1000


def seek(robot, detector, query, field_of_view, *, seconds=15, clock=time.monotonic):
    """Duck-typed robot adapter; all physical access stays in the bounded runner.

    Views are acquired stopped. Inference has no language-model round trips.
    A useful 150 mm approach follows a unique target; this does not assert arrival.
    """
    started = clock()
    observations = []
    outcome = 'not_found'
    try:
        previous = 0
        for heading in search_headings(field_of_view):
            if clock()-started >= seconds:
                outcome = 'timed_out'
                break
            if heading != previous:
                robot.turn(heading-previous)
            previous = heading
            image = robot.observe()
            detections, inference_ms = detector.detect(image['path'], query)
            state, target = select_target(detections)
            observations.append({'heading':heading, 'observation_id':image['observation_id'],
                'inference_ms':inference_ms, 'state':state})
            if clock()-started >= seconds:
                outcome = 'timed_out'
                break
            if state == 'ambiguous':
                outcome = 'ambiguous'
                break
            if target:
                x = (target.box[0]+target.box[2])/2
                focal = image['width']/(2*math.tan(math.radians(field_of_view/2)))
                bearing = math.degrees(math.atan((x-image['width']/2)/focal))
                if abs(bearing) > 5:
                    robot.turn(bearing)
                if clock()-started >= seconds:
                    outcome = 'timed_out'
                    break
                # An initial approach is measured separately from reaching/collecting an object.
                robot.approach(150)
                outcome = 'approached'
                break
        return {'outcome':outcome, 'elapsed_ms':(clock()-started)*1000,
            'observations':observations, 'arrival_verified':False}
    finally:
        robot.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true', help='Download pinned model weights; no robot access')
    parser.add_argument('--image', action='append', type=Path, default=[])
    parser.add_argument('--query', default='a video game controller')
    parser.add_argument('--short-edge', type=int, choices=(320, 480, 640, 800), default=480)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    began = time.monotonic()
    detector = GroundingDetector(download=args.prepare, short_edge=args.short_edge)
    report = {'model':MODEL, 'revision':REVISION, 'device':'cpu', 'threads':4,
        'load_ms':(time.monotonic()-began)*1000, 'images':[]}
    for path in args.image:
        detections, duration = detector.detect(path, args.query)
        report['images'].append({'path':str(path.resolve()), 'inference_ms':duration,
            'detections':[asdict(d) for d in detections]})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'ok':True, 'report':str(args.output.resolve()), 'load_ms':report['load_ms'],
        'inference_ms':[v['inference_ms'] for v in report['images']]}))


if __name__ == '__main__':
    main()
