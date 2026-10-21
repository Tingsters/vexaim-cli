//! Local immutable image artifacts, shared by USB and Bluetooth.
use crate::{device::fail, repl::Fail};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    io::Write,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

pub fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}
pub fn absolute(path: impl AsRef<Path>) -> Result<PathBuf, Fail> {
    let path = path.as_ref();
    Ok(if path.is_absolute() {
        path.to_owned()
    } else {
        std::env::current_dir().map_err(fail)?.join(path)
    })
}
pub fn validate(bytes: &[u8]) -> Result<(u32, u32), Fail> {
    if bytes.len() > 4 * 1024 * 1024
        || !bytes.starts_with(&[255, 216])
        || !bytes.ends_with(&[255, 217])
    {
        return Err(fail(
            "Incomplete or oversized JPEG; previous artifact preserved",
        ));
    }
    let mut decoder =
        image::ImageReader::with_format(std::io::Cursor::new(bytes), image::ImageFormat::Jpeg);
    let mut limits = image::Limits::default();
    limits.max_image_width = Some(1024);
    limits.max_image_height = Some(1024);
    limits.max_alloc = Some(16 * 1024 * 1024);
    decoder.limits(limits);
    let decoded = decoder
        .decode()
        .map_err(|e| fail(format!("JPEG decoder rejected frame: {e}")))?;
    Ok((decoded.width(), decoded.height()))
}
pub fn save(path: &Path, bytes: &[u8]) -> Result<(), Fail> {
    validate(bytes)?;
    let parent = path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    let mut file = tempfile::NamedTempFile::new_in(parent).map_err(fail)?;
    file.write_all(bytes).map_err(fail)?;
    file.as_file().sync_all().map_err(fail)?;
    file.persist(path).map_err(fail)?;
    Ok(())
}
pub fn store(
    dir: &Path,
    bytes: &[u8],
    identity: Value,
    transport: &str,
    requested: u64,
    before: Value,
    after: Value,
    ready: bool,
    detections: Option<Value>,
) -> Result<Value, Fail> {
    let (width, height) = validate(bytes)?;
    if (width, height) != (640, 480) {
        return Err(fail(
            "Camera observation must be native 640x480; an LCD framebuffer is not a camera observation",
        ));
    }
    let dir = absolute(dir)?;
    std::fs::create_dir_all(&dir).map_err(fail)?;
    let mut file = tempfile::Builder::new()
        .prefix("observation-")
        .suffix(".jpg")
        .tempfile_in(&dir)
        .map_err(fail)?;
    file.write_all(bytes).map_err(fail)?;
    file.as_file().sync_all().map_err(fail)?;
    let (_, path) = file.keep().map_err(fail)?;
    let received = now_ms();
    Ok(
        json!({"ok":true,"schema_version":1,"observation_id":path.file_stem().unwrap().to_string_lossy(),"path":path,"mime_type":"image/jpeg","width":width,"height":height,"bytes":bytes.len(),"sha256":format!("{:x}",Sha256::digest(bytes)),"robot":identity,"transport":transport,"host_requested_at_unix_ms":requested,"host_received_at_unix_ms":received,"latency_ms":received.saturating_sub(requested),"timestamp_source":"host request/receipt, not sensor exposure","before":before,"after":after,"control_ready":ready,"detections":detections,"coordinate_spaces":{"camera":[640,480],"native_detections":[320,240],"lcd":[240,240]}}),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    fn jpeg() -> Vec<u8> {
        let image = image::RgbImage::new(640, 480);
        let mut bytes = Vec::new();
        image::codecs::jpeg::JpegEncoder::new(&mut bytes)
            .encode_image(&image)
            .unwrap();
        bytes
    }
    #[test]
    fn decode_atomic_and_immutable() {
        let dir = tempfile::tempdir().unwrap();
        let bytes = jpeg();
        let a = store(
            dir.path(),
            &bytes,
            json!({}),
            "fake",
            now_ms(),
            Value::Null,
            Value::Null,
            false,
            None,
        )
        .unwrap();
        let b = store(
            dir.path(),
            &bytes,
            json!({}),
            "fake",
            now_ms(),
            Value::Null,
            Value::Null,
            true,
            None,
        )
        .unwrap();
        assert_ne!(a["path"], b["path"]);
        assert_eq!(a["sha256"], b["sha256"]);
        assert_eq!(a["control_ready"], false);
        let path = PathBuf::from(a["path"].as_str().unwrap());
        assert!(path.is_absolute());
        assert!(save(&path, &bytes[..bytes.len() / 2]).is_err());
        assert_eq!(std::fs::read(path).unwrap(), bytes);
    }
    #[test]
    fn corrupt_payload_rejected() {
        let mut bytes = jpeg();
        bytes[0] = 0;
        assert!(validate(&bytes).is_err());
        assert!(validate(&[255, 216, 255, 192, 0, 8, 8, 1, 224, 2, 128, 255, 217]).is_err());
    }
}
