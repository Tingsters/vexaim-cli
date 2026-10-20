//! Grab one frame from the AIM's USB (UVC) camera. Cross-platform via nokhwa
//! (V4L2 on Linux, Media Foundation on Windows, AVFoundation on macOS).
use nokhwa::{
    Camera,
    pixel_format::RgbFormat,
    query,
    utils::{
        ApiBackend, CameraFormat, FrameFormat, RequestedFormat, RequestedFormatType, Resolution,
    },
};

pub struct Snap {
    pub path: String,
    pub width: u32,
    pub height: u32,
    pub bytes: usize,
}

pub fn snap(output: Option<&str>) -> Result<Snap, String> {
    // macOS needs a camera-permission prompt before first use.
    nokhwa::nokhwa_initialize(|_| {});
    let cams = query(ApiBackend::Auto).map_err(|e| format!("cannot list cameras: {e}"))?;
    let aim: Vec<_> = cams
        .iter()
        .filter(|c| c.human_name().to_lowercase().contains("aim"))
        .collect();
    if aim.is_empty() {
        let names: Vec<_> = cams.iter().map(|c| c.human_name()).collect();
        return Err(format!(
            "no camera with 'AIM' in its name; found {names:?}. Is the robot plugged in? (macOS/Windows: allow camera access for this app)"
        ));
    }
    let want = CameraFormat::new(Resolution::new(640, 480), FrameFormat::MJPEG, 30);
    let mut last = String::new();
    for info in aim {
        // the AIM exposes two video nodes; only one streams, so try each
        let fmt = RequestedFormat::new::<RgbFormat>(RequestedFormatType::Exact(want));
        let mut cam = match Camera::new(info.index().clone(), fmt) {
            Ok(c) => c,
            Err(e) => {
                last = e.to_string();
                continue;
            }
        };
        if let Err(e) = cam.open_stream() {
            last = e.to_string();
            continue;
        }
        let mut frame = None;
        for _ in 0..8 {
            // first frames are dark/blurry while auto-exposure settles
            match cam.frame() {
                Ok(f) => frame = Some(f),
                Err(e) => last = e.to_string(),
            }
        }
        let Some(f) = frame else { continue };
        let path = output_path(output);
        let (w, h) = (f.resolution().width(), f.resolution().height());
        let bytes = if f.source_frame_format() == FrameFormat::MJPEG {
            trim_jpeg(f.buffer()).to_vec() // already a JPEG; drop the driver's zero padding
        } else {
            return Err(format!(
                "camera delivered {:?}, expected MJPEG",
                f.source_frame_format()
            ));
        };
        std::fs::write(&path, &bytes).map_err(|e| format!("{path}: {e}"))?;
        return Ok(Snap {
            path,
            width: w,
            height: h,
            bytes: bytes.len(),
        });
    }
    Err(format!("could not stream from the AIM camera: {last}"))
}

pub fn output_path(output: Option<&str>) -> String {
    output.map(String::from).unwrap_or_else(|| {
        let t = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        format!("vexaim-snap-{t}.jpg")
    })
}

/// V4L2 buffers can be larger than the JPEG they hold; cut after the last end-of-image marker
/// that precedes only padding.
fn trim_jpeg(b: &[u8]) -> &[u8] {
    let end = b.iter().rposition(|&c| c != 0).map(|i| i + 1).unwrap_or(0);
    &b[..end]
}

#[cfg(test)]
mod tests {
    use super::trim_jpeg;

    #[test]
    fn trims_zero_padding_after_eoi() {
        let mut v = vec![0xff, 0xd8, 1, 2, 3, 0xff, 0xd9];
        v.extend(vec![0u8; 100]);
        assert_eq!(trim_jpeg(&v), &[0xff, 0xd8, 1, 2, 3, 0xff, 0xd9]);
    }

    #[test]
    fn leaves_unpadded_jpeg_alone() {
        let v = [0xff, 0xd8, 9, 0xff, 0xd9];
        assert_eq!(trim_jpeg(&v), &v);
    }
}
