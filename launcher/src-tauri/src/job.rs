//! Windows only: service processes run in a Job Object that the OS closes when
//! the launcher process ends, so a crash or a forced quit never leaves the
//! local service (or anything it started) running in the background.

use std::ffi::c_void;
use std::io;
use std::mem::{size_of, zeroed};
use std::os::windows::io::AsRawHandle;
use std::os::windows::process::CommandExt;
use std::process::{Child, Command};
use std::ptr::null;
use std::sync::OnceLock;

use windows_sys::Win32::Foundation::{CloseHandle, HANDLE, INVALID_HANDLE_VALUE};
use windows_sys::Win32::System::Diagnostics::ToolHelp::{
    CreateToolhelp32Snapshot, Thread32First, Thread32Next, TH32CS_SNAPTHREAD, THREADENTRY32,
};
use windows_sys::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
    SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};
use windows_sys::Win32::System::Threading::{
    OpenThread, ResumeThread, CREATE_SUSPENDED, THREAD_SUSPEND_RESUME,
};

/// The handle is kept as an integer so it can live in a static. It is never
/// closed here: the OS closes it, and kills the job, when the launcher exits.
static JOB: OnceLock<Option<usize>> = OnceLock::new();

fn job() -> Option<HANDLE> {
    JOB.get_or_init(create_kill_on_close_job)
        .map(|job| job as HANDLE)
}

fn create_kill_on_close_job() -> Option<usize> {
    // SAFETY: plain Win32 calls on a handle this function owns.
    unsafe {
        let job = CreateJobObjectW(null(), null());
        if job.is_null() {
            return None;
        }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        let configured = SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &info as *const _ as *const c_void,
            size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        );
        if configured == 0 {
            CloseHandle(job);
            return None;
        }
        Some(job as usize)
    }
}

/// Spawns `command` suspended, adds it to the job and only then lets it run,
/// so processes it starts right away belong to the job as well.
pub fn spawn_in_job(command: &mut Command, creation_flags: u32) -> io::Result<Child> {
    command.creation_flags(creation_flags | CREATE_SUSPENDED);
    let mut child = command.spawn()?;
    // A service outside the job would outlive a crashed launcher, so it never
    // runs; nested jobs are supported on every Windows version Tauri targets.
    let assigned = match job() {
        // SAFETY: the child handle stays valid while `child` is alive.
        Some(job) => unsafe { AssignProcessToJobObject(job, child.as_raw_handle() as HANDLE) != 0 },
        None => false,
    };
    if !assigned {
        let error = io::Error::last_os_error();
        let _ = child.kill();
        let _ = child.wait();
        return Err(io::Error::other(format!("无法把服务进程加入启动器的进程组: {error}")));
    }
    if let Err(error) = resume_process(child.id()) {
        let _ = child.kill();
        let _ = child.wait();
        return Err(error);
    }
    Ok(child)
}

fn resume_process(pid: u32) -> io::Result<()> {
    // SAFETY: the snapshot and thread handles are closed before returning.
    unsafe {
        let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
        if snapshot == INVALID_HANDLE_VALUE {
            return Err(io::Error::last_os_error());
        }
        let mut entry: THREADENTRY32 = zeroed();
        entry.dwSize = size_of::<THREADENTRY32>() as u32;
        let mut resumed = false;
        let mut more = Thread32First(snapshot, &mut entry) != 0;
        while more {
            if entry.th32OwnerProcessID == pid {
                let thread = OpenThread(THREAD_SUSPEND_RESUME, 0, entry.th32ThreadID);
                if !thread.is_null() {
                    resumed |= ResumeThread(thread) != u32::MAX;
                    CloseHandle(thread);
                }
            }
            more = Thread32Next(snapshot, &mut entry) != 0;
        }
        CloseHandle(snapshot);
        if resumed {
            Ok(())
        } else {
            Err(io::Error::other("无法恢复新建的服务进程"))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::env;
    use std::io::{BufRead, BufReader};
    use std::process::Stdio;
    use std::time::Duration;
    use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
    use windows_sys::Win32::System::Threading::{
        OpenProcess, WaitForSingleObject, PROCESS_SYNCHRONIZE,
    };

    const CHILD_MODE_ENV: &str = "COURSE_NAVIGATOR_JOB_TEST_LAUNCHER";
    const CREATE_NO_WINDOW: u32 = 0x08000000;

    fn long_running_command() -> Command {
        let mut command = Command::new("cmd");
        command
            .args(["/C", "ping -n 60 127.0.0.1"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        command
    }

    fn process_exits_within(pid: u32, timeout: Duration) -> bool {
        // SAFETY: the process handle is closed before returning.
        unsafe {
            let process = OpenProcess(PROCESS_SYNCHRONIZE, 0, pid);
            if process.is_null() {
                return true;
            }
            let exited = WaitForSingleObject(process, timeout.as_millis() as u32) == WAIT_OBJECT_0;
            CloseHandle(process);
            exited
        }
    }

    #[test]
    fn spawned_process_runs_after_resume() {
        let mut child = spawn_in_job(&mut long_running_command(), CREATE_NO_WINDOW).expect("spawn");
        assert!(!process_exits_within(child.id(), Duration::from_millis(300)));
        let _ = child.kill();
        let _ = child.wait();
    }

    /// Plays the launcher: start a service in the job, report its pid, wait.
    #[test]
    fn job_test_launcher_process() {
        if env::var_os(CHILD_MODE_ENV).is_none() {
            return;
        }
        let child = spawn_in_job(&mut long_running_command(), CREATE_NO_WINDOW).expect("spawn");
        println!("SERVICE_PID={}", child.id());
        std::thread::sleep(Duration::from_secs(60));
    }

    #[test]
    fn services_die_when_the_launcher_is_killed() {
        let mut launcher = Command::new(env::current_exe().expect("test binary"))
            .args(["job::tests::job_test_launcher_process", "--exact", "--nocapture"])
            .env(CHILD_MODE_ENV, "1")
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .expect("start launcher stand-in");
        let stdout = launcher.stdout.take().expect("stdout");
        let pid = BufReader::new(stdout)
            .lines()
            .map_while(Result::ok)
            .find_map(|line| line.strip_prefix("SERVICE_PID=").map(|pid| pid.trim().parse::<u32>()))
            .expect("service pid line")
            .expect("numeric pid");
        assert!(!process_exits_within(pid, Duration::from_millis(300)));

        // An abrupt end, like a crash or Task Manager, never runs cleanup code.
        launcher.kill().expect("kill launcher stand-in");
        let _ = launcher.wait();
        assert!(process_exits_within(pid, Duration::from_secs(5)));
    }
}
