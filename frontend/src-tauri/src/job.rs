use std::process::Child;
#[cfg(windows)]
pub struct BackendJob(isize);
#[cfg(not(windows))]
pub struct BackendJob;
impl BackendJob {
    pub fn new() -> Result<Self, String> {
        #[cfg(windows)] unsafe {
            use windows_sys::Win32::{Foundation::CloseHandle, System::JobObjects::*};
            let handle = CreateJobObjectW(std::ptr::null(), std::ptr::null());
            if handle.is_null() { return Err(format!("Не удалось создать группу процессов: {}", std::io::Error::last_os_error())); }
            let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if SetInformationJobObject(handle, JobObjectExtendedLimitInformation, &info as *const _ as *const std::ffi::c_void, std::mem::size_of_val(&info) as u32) == 0 {
                let error = std::io::Error::last_os_error(); CloseHandle(handle);
                return Err(format!("Не удалось включить завершение дочерних процессов: {error}"));
            }
            // The handle is non-inheritable and owned once by this RAII value.
            Ok(Self(handle as isize))
        }
        #[cfg(not(windows))] { Ok(Self) }
    }
    pub fn attach(&self, child: &Child) -> Result<(), String> {
        #[cfg(windows)] unsafe {
            use std::os::windows::io::AsRawHandle;
            use windows_sys::Win32::System::JobObjects::AssignProcessToJobObject;
            if AssignProcessToJobObject(self.0 as _, child.as_raw_handle()) == 0 {
                return Err(format!("Не удалось изолировать группу процессов сервиса: {}", std::io::Error::last_os_error()));
            }
        }
        #[cfg(not(windows))] let _ = child;
        Ok(())
    }
}
#[cfg(windows)]
impl Drop for BackendJob {
    fn drop(&mut self) { unsafe { windows_sys::Win32::Foundation::CloseHandle(self.0 as _); } }
}

#[cfg(all(test, windows))]
mod tests {
    use super::*;
    use std::{os::windows::process::CommandExt, process::{Command, Stdio}, time::{Duration, Instant}};
    #[test]
    fn closing_job_terminates_owned_backend_process() {
        let mut child = Command::new("powershell.exe").args(["-NoProfile", "-NonInteractive", "-Command", "Start-Sleep -Seconds 30"])
            .creation_flags(0x08000000).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null()).spawn().unwrap();
        let job = BackendJob::new().unwrap();
        job.attach(&child).unwrap();
        drop(job);
        let end = Instant::now() + Duration::from_secs(2);
        let mut terminated = false;
        while Instant::now() < end {
            if child.try_wait().unwrap().is_some() { terminated = true; break; }
            std::thread::sleep(Duration::from_millis(20));
        }
        let _ = child.kill(); let _ = child.wait(); // Always clean up the test's own process, even on RED.
        assert!(terminated, "Owned backend must exit when the job handle closes");
    }
}
