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
    let image = capture(None)?;
    let (width, height) = crate::observation::validate(&image).map_err(|e| e.to_string())?;
    let path = output_path(output);
    crate::observation::save(std::path::Path::new(&path), &image).map_err(|e| e.to_string())?;
    Ok(Snap {
        path,
        width,
        height,
        bytes: image.len(),
    })
}

pub fn capture(camera_index: Option<u32>) -> Result<Vec<u8>, String> {
    // macOS needs a camera-permission prompt before first use.
    nokhwa::nokhwa_initialize(|_| {});
    let cams = query(ApiBackend::Auto).map_err(|e| format!("cannot list cameras: {e}"))?;
    let aim: Vec<_> = cams
        .iter()
        .filter(|c| {
            c.human_name().to_lowercase().contains("aim")
                && camera_index.is_none_or(|n| c.index().as_index().ok() == Some(n))
        })
        .collect();
    if aim.is_empty() {
        let names: Vec<_> = cams.iter().map(|c| c.human_name()).collect();
        return Err(format!(
            "no camera with 'AIM' in its name; found {names:?}. Is the robot plugged in? (macOS/Windows: allow camera access for this app)"
        ));
    }
    // With one connected AIM the sole camera group belongs to that robot. With
    // multiple devices the caller must supply an explicit OS camera binding.
    if camera_index.is_none() && crate::repl::devices().map_err(|e| e.to_string())?.len() != 1 {
        return Err(
            "Ambiguous AIM camera ownership; select --camera-index N for this robot".into(),
        );
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
        let bytes = if f.source_frame_format() == FrameFormat::MJPEG {
            trim_jpeg(f.buffer()).to_vec() // already a JPEG; drop the driver's zero padding
        } else {
            // Some drivers (observed: macOS AVFoundation) hand back raw frames such as YUYV
            // even when MJPEG was requested; decode them and encode our own JPEG.
            let rgb = f
                .decode_image::<RgbFormat>()
                .map_err(|e| format!("cannot decode {:?} camera frame: {e}", f.source_frame_format()))?;
            encode_jpeg(rgb.width(), rgb.height(), rgb.as_raw())?
        };
        crate::observation::validate(&bytes).map_err(|e| e.to_string())?;
        return Ok(bytes);
    }
    Err(format!("could not stream from the AIM camera: {last}"))
}

pub fn output_path(output: Option<&str>) -> String {
    output.map(String::from).unwrap_or_else(|| {
        let t = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        format!("vexaim-snap-{t}-{}.jpg", std::process::id())
    })
}

/// Encode packed RGB8 pixels as a JPEG.
fn encode_jpeg(width: u32, height: u32, rgb: &[u8]) -> Result<Vec<u8>, String> {
    let mut out = Vec::new();
    image::codecs::jpeg::JpegEncoder::new_with_quality(&mut out, 90)
        .encode(rgb, width, height, image::ExtendedColorType::Rgb8)
        .map_err(|e| format!("cannot encode camera frame as JPEG: {e}"))?;
    Ok(out)
}

/// V4L2 buffers can be larger than the JPEG they hold; cut after the last end-of-image marker
/// that precedes only padding.
fn trim_jpeg(b: &[u8]) -> &[u8] {
    let end = b.iter().rposition(|&c| c != 0).map(|i| i + 1).unwrap_or(0);
    &b[..end]
}

#[cfg(test)]
mod tests {
    use super::{encode_jpeg, trim_jpeg};

    #[test]
    fn encodes_raw_rgb_as_valid_jpeg() {
        let rgb = vec![128u8; 64 * 48 * 3];
        let jpeg = encode_jpeg(64, 48, &rgb).unwrap();
        assert_eq!(crate::observation::validate(&jpeg).unwrap(), (64, 48));
    }

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
