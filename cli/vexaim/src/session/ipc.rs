//! Local-only, current-user IPC. No TCP listener or credential files.
use super::failure;
use crate::repl::Fail;
use std::io;

pub fn valid_id(id: &str) -> bool {
    id.len() == 20 && id.starts_with("aim-") && id[4..].bytes().all(|b| b.is_ascii_hexdigit())
}

pub fn id_for(name: &str) -> Result<String, Fail> {
    // FNV-1a has a fixed definition across Rust versions. This is a namespace,
    // not authentication; OS permissions supply the access boundary.
    let user = user_identity().map_err(failure)?;
    let mut hash = 0xcbf29ce484222325u64;
    for byte in user.bytes().chain(Some(0)).chain(name.bytes()) {
        hash = (hash ^ u64::from(byte)).wrapping_mul(0x100000001b3);
    }
    Ok(format!("aim-{hash:016x}"))
}

#[cfg(unix)]
fn user_identity() -> io::Result<String> {
    // No privilege changes; this is just the process's effective UID.
    Ok(unsafe { libc::geteuid() }.to_string())
}

#[cfg(unix)]
fn socket_path(id: &str) -> io::Result<std::path::PathBuf> {
    use std::os::unix::fs::{DirBuilderExt, MetadataExt, PermissionsExt};
    let uid = unsafe { libc::geteuid() };
    // /tmp keeps the socket below macOS's 104-byte sockaddr_un limit.
    let root = std::path::PathBuf::from(format!("/tmp/vexaim-{uid}"));
    match std::fs::DirBuilder::new().mode(0o700).create(&root) {
        Ok(()) => {}
        Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {}
        Err(e) => return Err(e),
    }
    let metadata = std::fs::symlink_metadata(&root)?;
    if !metadata.is_dir() || metadata.uid() != uid || metadata.permissions().mode() & 0o077 != 0 {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "Session directory must be owned by this user and private (0700)",
        ));
    }
    Ok(root.join(id))
}

#[cfg(unix)]
pub type Stream = tokio::net::UnixStream;

#[cfg(unix)]
pub struct Listener {
    inner: tokio::net::UnixListener,
    path: std::path::PathBuf,
}

#[cfg(unix)]
impl Listener {
    pub async fn bind(id: &str) -> io::Result<Self> {
        use std::os::unix::fs::FileTypeExt;
        let path = socket_path(id)?;
        if let Ok(meta) = std::fs::symlink_metadata(&path) {
            if !meta.file_type().is_socket() {
                return Err(io::Error::new(
                    io::ErrorKind::PermissionDenied,
                    "Refusing to replace a non-socket session path",
                ));
            }
            match Stream::connect(&path).await {
                Ok(_) => {
                    return Err(io::Error::new(
                        io::ErrorKind::AddrInUse,
                        "Session already running",
                    ));
                }
                Err(e)
                    if matches!(
                        e.kind(),
                        io::ErrorKind::ConnectionRefused | io::ErrorKind::NotFound
                    ) =>
                {
                    std::fs::remove_file(&path)?;
                }
                Err(e) => return Err(e),
            }
        }
        let inner = tokio::net::UnixListener::bind(&path)?;
        Ok(Self { inner, path })
    }
    pub async fn accept(&mut self) -> io::Result<Stream> {
        self.inner.accept().await.map(|(s, _)| s)
    }
}

#[cfg(unix)]
impl Drop for Listener {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.path);
    }
}

#[cfg(unix)]
pub async fn connect(id: &str) -> io::Result<Stream> {
    Stream::connect(socket_path(id)?).await
}

#[cfg(windows)]
fn user_identity() -> io::Result<String> {
    use windows_sys::Win32::{
        Foundation::{CloseHandle, LocalFree},
        Security::Authorization::ConvertSidToStringSidW,
        Security::{GetTokenInformation, TOKEN_QUERY, TOKEN_USER, TokenUser},
        System::Threading::{GetCurrentProcess, OpenProcessToken},
    };
    unsafe {
        let mut token = std::ptr::null_mut();
        if OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token) == 0 {
            return Err(io::Error::last_os_error());
        }
        let result = (|| {
            let mut needed = 0;
            GetTokenInformation(token, TokenUser, std::ptr::null_mut(), 0, &mut needed);
            if needed == 0 {
                return Err(io::Error::last_os_error());
            }
            let mut data = vec![0usize; (needed as usize).div_ceil(std::mem::size_of::<usize>())];
            if GetTokenInformation(
                token,
                TokenUser,
                data.as_mut_ptr().cast(),
                needed,
                &mut needed,
            ) == 0
            {
                return Err(io::Error::last_os_error());
            }
            let user = &*data.as_ptr().cast::<TOKEN_USER>();
            let mut sid = std::ptr::null_mut();
            if ConvertSidToStringSidW(user.User.Sid, &mut sid) == 0 {
                return Err(io::Error::last_os_error());
            }
            let mut len = 0;
            while *sid.add(len) != 0 {
                len += 1;
            }
            let result = String::from_utf16_lossy(std::slice::from_raw_parts(sid, len));
            LocalFree(sid.cast());
            Ok(result)
        })();
        CloseHandle(token);
        result
    }
}

#[cfg(windows)]
fn pipe_name(id: &str) -> String {
    format!(r"\\.\pipe\vexaim-{id}")
}

#[cfg(windows)]
fn create_pipe(
    id: &str,
    first: bool,
) -> io::Result<tokio::net::windows::named_pipe::NamedPipeServer> {
    use windows_sys::Win32::{
        Foundation::LocalFree,
        Security::{
            Authorization::{
                ConvertStringSecurityDescriptorToSecurityDescriptorW, SDDL_REVISION_1,
            },
            SECURITY_ATTRIBUTES,
        },
    };
    let sid = user_identity()?;
    // Only this Windows SID; protected DACL, no inherited Everyone/admin grants.
    let sddl: Vec<u16> = format!("D:P(A;;GA;;;{sid})")
        .encode_utf16()
        .chain(Some(0))
        .collect();
    unsafe {
        let mut descriptor = std::ptr::null_mut();
        if ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl.as_ptr(),
            SDDL_REVISION_1,
            &mut descriptor,
            std::ptr::null_mut(),
        ) == 0
        {
            return Err(io::Error::last_os_error());
        }
        let attributes = SECURITY_ATTRIBUTES {
            nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
            lpSecurityDescriptor: descriptor,
            bInheritHandle: 0,
        };
        let result = tokio::net::windows::named_pipe::ServerOptions::new()
            .first_pipe_instance(first)
            .reject_remote_clients(true)
            .create_with_security_attributes_raw(
                pipe_name(id),
                (&attributes as *const SECURITY_ATTRIBUTES)
                    .cast_mut()
                    .cast(),
            );
        LocalFree(descriptor);
        result
    }
}

#[cfg(windows)]
pub type Stream = tokio::net::windows::named_pipe::NamedPipeServer;

#[cfg(windows)]
pub struct Listener {
    next: Option<Stream>,
    id: String,
}

#[cfg(windows)]
impl Listener {
    pub async fn bind(id: &str) -> io::Result<Self> {
        Ok(Self {
            next: Some(create_pipe(id, true)?),
            id: id.to_string(),
        })
    }
    pub async fn accept(&mut self) -> io::Result<Stream> {
        let server = self.next.as_ref().unwrap();
        server.connect().await?;
        let replacement = create_pipe(&self.id, false)?;
        Ok(self.next.replace(replacement).unwrap())
    }
}

#[cfg(windows)]
pub async fn connect(id: &str) -> io::Result<tokio::net::windows::named_pipe::NamedPipeClient> {
    // All instances can briefly be busy while the listener installs its replacement.
    for _ in 0..20 {
        match tokio::net::windows::named_pipe::ClientOptions::new().open(pipe_name(id)) {
            Ok(pipe) => return Ok(pipe),
            Err(e) if e.raw_os_error() == Some(231) => {
                tokio::time::sleep(std::time::Duration::from_millis(10)).await
            }
            Err(e) => return Err(e),
        }
    }
    Err(io::Error::new(
        io::ErrorKind::WouldBlock,
        "Session pipe busy",
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn ids_are_local_and_cannot_escape_the_ipc_namespace() {
        assert!(valid_id(&id_for("AIM6518").unwrap()));
        assert_ne!(id_for("AIM6518").unwrap(), id_for("AIM6519").unwrap());
        for id in ["../other", "aim-../../other", "", "aim-123"] {
            assert!(!valid_id(id));
        }
    }
}
