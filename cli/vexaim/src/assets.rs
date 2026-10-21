//! Restricted AIM assets. No user/system program vendor is reachable here.
use crate::{device::fail, repl::Fail};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{path::Path, time::Duration};
use vex_v5_serial::{
    Connection,
    protocol::{VEX_CRC32, Version, cdc2::file::*},
};

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AssetRequest {
    pub kind: String,
    pub operation: String,
    pub slot: Option<u8>,
    pub file: Option<String>,
    pub output: Option<String>,
    pub replace: bool,
}
impl AssetRequest {
    pub fn validate(&self) -> Result<(), Fail> {
        if !["image", "sound"].contains(&self.kind.as_str())
            || !["list", "upload", "download", "delete"].contains(&self.operation.as_str())
        {
            return Err(fail(
                "assets image|sound list|upload|download|delete [SLOT] [--file FILE] [--output FILE] [--replace]",
            ));
        }
        if self.operation != "list" && !self.slot.is_some_and(|n| (1..=10).contains(&n)) {
            return Err(fail("Asset slot must be 1..10"));
        }
        if self.operation == "upload" {
            let file = self
                .file
                .as_ref()
                .ok_or_else(|| fail("Upload needs --file FILE"))?;
            validate_file(&self.kind, Path::new(file))?;
        }
        if self.operation == "download" && self.output.is_none() {
            return Err(fail("Download needs --output FILE"));
        }
        for path in [&self.file, &self.output].into_iter().flatten() {
            if !Path::new(path).is_absolute() {
                return Err(fail("Asset paths must be absolute before IPC"));
            }
        }
        Ok(())
    }
}
pub fn validate_file(kind: &str, path: &Path) -> Result<Vec<u8>, Fail> {
    let max = if kind == "image" {
        10 * 1024 * 1024
    } else {
        50 * 1024
    };
    if std::fs::metadata(path).map_err(fail)?.len() > max {
        return Err(fail(format!("Asset exceeds {max} bytes")));
    }
    let bytes = std::fs::read(path).map_err(fail)?;
    if kind == "image" {
        if !bytes.starts_with(b"\x89PNG\r\n\x1a\n") {
            return Err(fail("Custom images must be PNG"));
        }
        let mut reader =
            image::ImageReader::with_format(std::io::Cursor::new(&bytes), image::ImageFormat::Png);
        let mut limits = image::Limits::default();
        limits.max_image_width = Some(4096);
        limits.max_image_height = Some(4096);
        limits.max_alloc = Some(64 * 1024 * 1024);
        reader.limits(limits);
        reader.decode().map_err(fail)?;
    } else {
        mp3_ms(&bytes)?;
    }
    Ok(bytes)
}
fn mp3_ms(bytes: &[u8]) -> Result<u64, Fail> {
    let mut pos = 0;
    if bytes.starts_with(b"ID3") {
        if bytes.len() < 10 || bytes[6..10].iter().any(|n| n & 128 != 0) {
            return Err(fail("Invalid MP3 ID3 header"));
        }
        pos = 10
            + bytes[6..10]
                .iter()
                .fold(0usize, |a, n| (a << 7) | usize::from(*n));
    }
    let mut seconds = 0.;
    let mut frames = 0;
    while pos + 4 <= bytes.len() {
        if bytes.len() - pos == 128 && &bytes[pos..pos + 3] == b"TAG" {
            break;
        }
        let h = u32::from_be_bytes(bytes[pos..pos + 4].try_into().unwrap());
        let version = (h >> 19) & 3;
        let layer = (h >> 17) & 3;
        let bitrate = ((h >> 12) & 15) as usize;
        let sr = ((h >> 10) & 3) as usize;
        if h >> 21 != 0x7ff
            || version == 1
            || layer != 1
            || bitrate == 0
            || bitrate == 15
            || sr == 3
        {
            return Err(fail("Invalid or unsupported MPEG Layer III frame"));
        }
        let rate = [44100, 48000, 32000][sr]
            / if version == 3 {
                1
            } else if version == 2 {
                2
            } else {
                4
            };
        let kbps = if version == 3 {
            [
                0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0,
            ][bitrate]
        } else {
            [
                0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0,
            ][bitrate]
        };
        let len = if version == 3 { 144000 } else { 72000 } * kbps / rate + ((h >> 9) & 1) as usize;
        if len < 4 || pos + len > bytes.len() {
            return Err(fail("Truncated MP3 frame"));
        }
        seconds += if version == 3 { 1152. } else { 576. } / rate as f64;
        pos += len;
        frames += 1;
    }
    if frames == 0 || seconds > 10. {
        return Err(fail("Custom sounds must be valid MP3, at most 10 seconds"));
    }
    Ok((seconds * 1000.).ceil() as u64)
}
fn vendor(kind: &str) -> FileVendor {
    if kind == "image" {
        FileVendor::AimImage
    } else {
        FileVendor::AimSound
    }
}
pub async fn list<C: Connection>(conn: &mut C, kind: &str) -> Result<Value, Fail> {
    let count = conn
        .handshake(
            DirectoryFileCountPacket {
                vendor: vendor(kind),
                reserved: 0,
            },
            Duration::from_secs(3),
            0,
        )
        .await
        .map_err(fail)?
        .map_err(fail)?
        .count;
    if count > 64 {
        return Err(fail("Unexpected AIM asset directory size"));
    }
    let mut entries = Vec::new();
    for index in 0..count {
        let entry = conn
            .handshake(
                DirectoryEntryPacket {
                    file_index: index as u8,
                    reserved: 0,
                },
                Duration::from_secs(3),
                0,
            )
            .await
            .map_err(fail)?
            .map_err(fail)?;
        entries.push(
            json!({"file_name":entry.file_name.to_string(),"bytes":entry.size,"crc32":entry.crc}),
        );
    }
    Ok(json!({"kind":kind,"entries":entries,"slots":10,"slot_encoding_verified":false}))
}
pub async fn transfer<C: Connection>(
    conn: &mut C,
    r: &AssetRequest,
    name: &str,
    encoding_verified: bool,
) -> Result<Value, Fail> {
    // The native constant must resolve to a plain filename. Never guess a slot
    // filename or allow it to select a system namespace/path.
    if name.is_empty()
        || name.len() > 23
        || !name
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'.' | b'-'))
    {
        return Err(fail(
            "Firmware did not provide a usable asset slot filename",
        ));
    }
    let file_name = name.try_into().map_err(fail)?;
    let metadata = conn
        .handshake(
            FileMetadataPacket {
                vendor: vendor(&r.kind),
                reserved: 0,
                file_name,
            },
            Duration::from_secs(3),
            0,
        )
        .await
        .map_err(fail)?
        .map_err(fail)?;
    if r.operation == "delete" {
        conn.handshake(
            FileErasePacket {
                vendor: vendor(&r.kind),
                reserved: 0,
                file_name: name.try_into().map_err(fail)?,
            },
            Duration::from_secs(3),
            0,
        )
        .await
        .map_err(fail)?
        .map_err(fail)?;
        return Ok(json!({"ok":true,"deleted":r.slot}));
    }
    if r.operation == "upload" {
        if !encoding_verified {
            return Err(fail(
                "Asset encoding is unverified for this firmware; upload is disabled. Use the official AIM image/sound uploader; playback/display commands work independently.",
            ));
        }
        if metadata.is_some() && !r.replace {
            return Err(fail("Slot occupied; use --replace to overwrite it"));
        }
        let bytes = validate_file(&r.kind, Path::new(r.file.as_ref().unwrap()))?;
        vex_v5_serial::commands::file::upload_file(
            conn,
            name.try_into().map_err(fail)?,
            FileMetadata {
                extension: if r.kind == "image" { "png" } else { "mp3" }
                    .try_into()
                    .unwrap(),
                extension_type: ExtensionType::Binary,
                timestamp: 0,
                version: Version {
                    major: 0,
                    minor: 0,
                    build: 0,
                    beta: 0,
                },
            },
            vendor(&r.kind),
            &bytes,
            FileTransferTarget::Qspi,
            0,
            None,
            FileExitAction::DoNothing,
            None::<fn(f32)>,
        )
        .await
        .map_err(|e| {
            fail(format!(
                "Upload may be partial; no retry or rollback claimed: {e}"
            ))
        })?;
        let read = download(conn, &r.kind, name, bytes.len() as u32).await?;
        if read != bytes {
            return Err(fail("Asset readback mismatch; slot may be partial"));
        }
        return Ok(json!({"ok":true,"slot":r.slot,"bytes":bytes.len(),"readback_verified":true}));
    }
    let meta = metadata.ok_or_else(|| fail("Asset slot is empty"))?;
    let bytes = download(conn, &r.kind, name, meta.size).await?;
    if VEX_CRC32.checksum(&bytes) != meta.crc32 {
        return Err(fail("Asset CRC mismatch; existing destination preserved"));
    }
    let path = Path::new(r.output.as_ref().unwrap());
    use std::io::Write;
    let mut temp = tempfile::NamedTempFile::new_in(path.parent().unwrap()).map_err(fail)?;
    temp.write_all(&bytes).map_err(fail)?;
    temp.as_file().sync_all().map_err(fail)?;
    temp.persist(path).map_err(fail)?;
    Ok(json!({"ok":true,"path":path,"bytes":bytes.len(),"crc32":meta.crc32}))
}
async fn download<C: Connection>(
    conn: &mut C,
    kind: &str,
    name: &str,
    size: u32,
) -> Result<Vec<u8>, Fail> {
    if size == 0 || size > 10 * 1024 * 1024 {
        return Err(fail("Asset size outside transfer bounds"));
    }
    let init = conn
        .handshake(
            FileTransferInitializePacket {
                operation: FileTransferOperation::Read,
                target: FileTransferTarget::Qspi,
                vendor: vendor(kind),
                options: FileTransferOptions::None,
                file_size: size,
                load_address: 0,
                write_file_crc: 0,
                metadata: FileMetadata {
                    extension: "ini".try_into().unwrap(),
                    extension_type: ExtensionType::Binary,
                    timestamp: 0,
                    version: Version {
                        major: 0,
                        minor: 0,
                        build: 0,
                        beta: 0,
                    },
                },
                file_name: name.try_into().map_err(fail)?,
            },
            Duration::from_secs(3),
            0,
        )
        .await
        .map_err(fail)?
        .map_err(fail)?;
    if init.file_size != size {
        return Err(fail("Asset size changed during transfer"));
    }
    let chunk = usize::from(init.window_size.saturating_sub(14)).min(216) / 4 * 4;
    if chunk == 0 {
        return Err(fail("Invalid asset transfer window"));
    }
    let deadline = std::time::Instant::now() + Duration::from_secs(120);
    let mut bytes = Vec::new();
    while bytes.len() < size as usize {
        if std::time::Instant::now() >= deadline {
            return Err(fail("Asset transfer timed out"));
        }
        let count = chunk.min((size as usize - bytes.len()).div_ceil(4) * 4);
        let reply = conn
            .handshake(
                FileDataReadPacket {
                    address: bytes.len() as u32,
                    size: count as u16,
                },
                Duration::from_secs(3),
                0,
            )
            .await
            .map_err(fail)?
            .map_err(fail)?;
        let needed = count.min(size as usize - bytes.len());
        if reply.address != bytes.len() as u32
            || reply.data.len() < needed
            || reply.data.len() > count
        {
            return Err(fail("Asset block address/length mismatch"));
        }
        bytes.extend_from_slice(&reply.data[..needed]);
    }
    Ok(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn bounds_and_validation() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("bad.mp3");
        std::fs::write(&path, b"not an mp3").unwrap();
        assert!(validate_file("sound", &path).is_err());
        assert!(mp3_ms(b"ID3\0").is_err());
        assert!(
            AssetRequest {
                kind: "firmware".into(),
                operation: "upload".into(),
                slot: Some(1),
                file: Some(path.to_string_lossy().into()),
                output: None,
                replace: false
            }
            .validate()
            .is_err()
        );
    }
}
