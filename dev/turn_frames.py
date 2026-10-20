# /// script
# requires-python = ">=3.10"
# dependencies = ["opencv-python-headless==4.13.0.92"]
# ///
"""Local, target-free frame registration spike. Never a motor controller.

Usage: uv run dev/turn_frames.py before.jpg after.jpg --output dist/alignment.json
No uploads, image rewriting, scene prompts, or robot commands.
"""
import argparse
import json
from pathlib import Path
import time

import cv2
import numpy as np


def analyze(before, after):
    started = time.monotonic()
    result = dict(usable=False, robot_yaw_error_deg=None, physical_accuracy_verified=False,
                  automatic_correction_enabled=False,
                  limitation="Image registration does not separate robot yaw, translation, object motion or camera calibration error")
    if before is None or after is None or before.shape != after.shape or before.ndim != 2:
        raise ValueError("Supply two readable grayscale frames with identical dimensions")
    detector = cv2.ORB_create(nfeatures=1500)
    key_a, desc_a = detector.detectAndCompute(before, None)
    key_b, desc_b = detector.detectAndCompute(after, None)
    result["keypoints"] = [len(key_a), len(key_b)]
    if desc_a is None or desc_b is None:
        result["reason"] = "insufficient_scene_texture"
        return result
    matches = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(desc_a, desc_b, k=2)
    good = [pair[0] for pair in matches if len(pair)==2 and pair[0].distance < .7*pair[1].distance]
    result["matches"] = len(good)
    if len(good) < 30:
        result["reason"] = "insufficient_consistent_matches"
        return result
    points_a = np.float32([key_a[m.queryIdx].pt for m in good]).reshape(-1,1,2)
    points_b = np.float32([key_b[m.trainIdx].pt for m in good]).reshape(-1,1,2)
    transform, mask = cv2.findHomography(points_a, points_b, cv2.RANSAC, 2.0)
    if transform is None or mask is None or not np.isfinite(transform).all():
        result["reason"] = "no_consistent_scene_transform"
        return result
    inliers = mask.ravel().astype(bool)
    height,width = before.shape
    coverage = cv2.contourArea(cv2.convexHull(points_a[inliers]))/(width*height) if inliers.sum() >= 3 else 0
    predicted = cv2.perspectiveTransform(points_a, transform)
    residual = float(np.median(np.linalg.norm(predicted[inliers]-points_b[inliers],axis=2)))
    result.update(inlier_count=int(inliers.sum()),inlier_ratio=float(inliers.mean()),coverage_fraction=float(coverage),median_residual_px=residual)
    if inliers.sum()<30 or inliers.mean()<.7 or coverage<.12 or residual>2:
        result["reason"] = "scene_changed_or_matches_too_localized"
        return result
    grid = np.float32([[x*width,y*height] for x in (.25,.5,.75) for y in (.25,.5,.75)]).reshape(-1,1,2)
    displacement = cv2.perspectiveTransform(grid,transform)-grid
    if not np.isfinite(displacement).all():
        result["reason"] = "degenerate_transform"
        return result
    result.update(usable=True,reason="image_alignment_only",homography=transform.tolist(),
                  median_grid_displacement_px=float(np.median(np.linalg.norm(displacement,axis=2))),
                  median_horizontal_displacement_px=float(np.median(displacement[:,:,0])),
                  processing_ms=round((time.monotonic()-started)*1000,2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before",type=Path)
    parser.add_argument("after",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    report = analyze(cv2.imread(str(args.before),cv2.IMREAD_GRAYSCALE),cv2.imread(str(args.after),cv2.IMREAD_GRAYSCALE))
    report.update(before=str(args.before),after=str(args.after),capture_freshness_verified=False)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    main()
