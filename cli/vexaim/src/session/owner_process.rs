//! Start a persistent owner without inheriting a PowerShell capture pipe.
#[cfg(unix)]
pub(super) fn spawn(args: &[&str]) -> std::io::Result<std::process::Child> {
    use std::{
        os::unix::process::CommandExt,
        process::{Command, Stdio},
    };
    Command::new(std::env::current_exe()?)
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .process_group(0)
        .spawn()
}

#[cfg(windows)]
pub(super) use windows::spawn;

#[cfg(windows)]
mod windows {
    use std::{
        ffi::OsStr,
        io,
        os::windows::{
            ffi::OsStrExt,
            io::{AsRawHandle, FromRawHandle, OwnedHandle},
        },
        ptr,
    };
    use windows_sys::Win32::{
        Foundation::{CloseHandle, WAIT_OBJECT_0, WAIT_TIMEOUT},
        System::Threading::{
            CREATE_NO_WINDOW, CreateProcessW, GetExitCodeProcess, PROCESS_INFORMATION,
            STARTUPINFOW, TerminateProcess, WaitForSingleObject,
        },
    };

    pub(in super::super) struct Owner(OwnedHandle);
    impl Owner {
        pub(in super::super) fn try_wait(&mut self) -> io::Result<Option<u32>> {
            // SAFETY: the owned process handle remains valid for both calls.
            unsafe {
                match WaitForSingleObject(self.0.as_raw_handle(), 0) {
                    WAIT_TIMEOUT => Ok(None),
                    WAIT_OBJECT_0 => {
                        let mut code = 0;
                        if GetExitCodeProcess(self.0.as_raw_handle(), &mut code) == 0 {
                            return Err(io::Error::last_os_error());
                        }
                        Ok(Some(code))
                    }
                    _ => Err(io::Error::last_os_error()),
                }
            }
        }
        pub(in super::super) fn kill(&mut self) -> io::Result<()> {
            // SAFETY: this handle refers to the child this wrapper created.
            if unsafe { TerminateProcess(self.0.as_raw_handle(), 1) } == 0 {
                return Err(io::Error::last_os_error());
            }
            Ok(())
        }
    }

    fn quote(argument: &OsStr) -> io::Result<Vec<u16>> {
        // Windows CRT quoting; preserve Unicode, empty arguments and literal
        // quotes/backslashes. No command interpreter participates.
        let mut out = vec![34];
        let mut slashes = 0;
        for unit in argument.encode_wide() {
            match unit {
                0 => {
                    return Err(io::Error::new(
                        io::ErrorKind::InvalidInput,
                        "NUL in owner argument",
                    ));
                }
                92 => {
                    slashes += 1;
                    continue;
                }
                34 => out.extend(std::iter::repeat_n(92, slashes * 2 + 1)),
                _ => out.extend(std::iter::repeat_n(92, slashes)),
            }
            out.push(unit);
            slashes = 0;
        }
        out.extend(std::iter::repeat_n(92, slashes * 2));
        out.push(34);
        Ok(out)
    }

    fn launch(program: &OsStr, args: &[&str]) -> io::Result<Owner> {
        let mut application: Vec<u16> = program.encode_wide().collect();
        if application.contains(&0) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "NUL in owner path",
            ));
        }
        application.push(0);
        let mut command = quote(program)?;
        for argument in args {
            command.push(32);
            command.extend(quote(OsStr::new(argument))?);
        }
        command.push(0);
        if command.len() > 32767 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "Owner command too long",
            ));
        }
        // SAFETY: these Win32 structures contain only integers and pointers;
        // all input buffers remain alive and the command line is writable.
        unsafe {
            let mut startup: STARTUPINFOW = std::mem::zeroed();
            startup.cb = std::mem::size_of::<STARTUPINFOW>() as u32;
            let mut process: PROCESS_INFORMATION = std::mem::zeroed();
            // Rust's stable Command API inherits unrelated inheritable handles.
            // PowerShell capture pipes must not stay open in the long-lived owner.
            // No handles are inherited, no console is opened, and the owner uses
            // private IPC rather than standard streams. Environment/cwd inherit.
            if CreateProcessW(
                application.as_ptr(),
                command.as_mut_ptr(),
                ptr::null(),
                ptr::null(),
                0,
                CREATE_NO_WINDOW,
                ptr::null(),
                ptr::null(),
                &startup,
                &mut process,
            ) == 0
            {
                return Err(io::Error::last_os_error());
            }
            CloseHandle(process.hThread);
            Ok(Owner(OwnedHandle::from_raw_handle(process.hProcess)))
        }
    }

    pub(in super::super) fn spawn(args: &[&str]) -> io::Result<Owner> {
        launch(std::env::current_exe()?.as_os_str(), args)
    }

    #[cfg(test)]
    mod tests {
        use super::*;
        #[test]
        fn arguments_preserve_spaces_unicode_quotes_and_trailing_slashes() {
            let quoted = |s: &str| String::from_utf16(&quote(OsStr::new(s)).unwrap()).unwrap();
            assert_eq!(quoted(""), "\"\"");
            assert_eq!(quoted("a b"), "\"a b\"");
            assert_eq!(quoted(r#"a\"b\"#), r#""a\\\"b\\""#);
            assert_eq!(quoted("机器人"), "\"机器人\"");
            assert!(quote(OsStr::new("bad\0name")).is_err());
        }

        #[test]
        #[ignore = "child fixture, launched only by owner_does_not_inherit_capture_handles"]
        fn sleeping_child() {
            std::thread::sleep(std::time::Duration::from_secs(3));
        }

        #[test]
        fn owner_does_not_inherit_capture_handles() {
            use std::{io::Read, sync::mpsc, time::Duration};
            use windows_sys::Win32::Foundation::{HANDLE_FLAG_INHERIT, SetHandleInformation};
            let (mut reader, writer) = io::pipe().unwrap();
            // SAFETY: writer owns a live pipe handle. Model the inheritable
            // capture handle supplied by PowerShell, unrelated to child stdio.
            assert_ne!(
                unsafe {
                    SetHandleInformation(
                        writer.as_raw_handle(),
                        HANDLE_FLAG_INHERIT,
                        HANDLE_FLAG_INHERIT,
                    )
                },
                0
            );
            let mut child = launch(
                std::env::current_exe().unwrap().as_os_str(),
                &[
                    "--exact",
                    "session::owner_process::windows::tests::sleeping_child",
                    "--ignored",
                ],
            )
            .unwrap();
            drop(writer);
            let (tx, rx) = mpsc::channel();
            let read = std::thread::spawn(move || {
                let _ = tx.send(reader.read(&mut [0u8; 1]));
            });
            let eof = rx.recv_timeout(Duration::from_secs(1));
            let alive = child.try_wait().unwrap().is_none();
            if alive {
                child.kill().unwrap();
            }
            read.join().unwrap();
            assert!(
                alive,
                "child fixture must still be running while capture reaches EOF"
            );
            assert_eq!(
                eof.unwrap().unwrap(),
                0,
                "capture must reach EOF independently of the owner lifetime"
            );
        }
    }
}
