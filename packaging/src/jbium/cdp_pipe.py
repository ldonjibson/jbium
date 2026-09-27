"""
════════════════════════════════════════════════════════════
CDP over --remote-debugging-pipe
════════════════════════════════════════════════════════════

Why not --remote-debugging-port: that flag opens an unauthenticated
HTTP/WebSocket endpoint on 127.0.0.1, and any page the browser loads
can fetch('http://127.0.0.1:<port>/json/version') across the port
range to detect CDP automation. --remote-debugging-pipe opens no
socket at all — the browser talks CDP over two inherited file
descriptors, which nothing inside the browser can reach.

Protocol, as implemented by the pinned tree's
content/browser/devtools/devtools_pipe_handler.cc (ASCIIZ mode,
the default when the switch has no value):

- the browser READS commands from fd 3 and WRITES responses/events
  to fd 4, on every platform (on Windows it maps CRT fds 3/4 to
  handles with _get_osfhandle(); there is no separate handle switch
  in this version);
- each message is one JSON object terminated by a single NUL byte;
- when the browser's read end hits EOF (we close our write end), it
  treats that as the client disconnecting and shuts down.

All page traffic is multiplexed over this one connection using
flattened sessions (Target.attachToTarget {flatten: true}); every
page-level command and event carries its "sessionId".

Dependency on patch 001: in the pinned tree, --remote-debugging-pipe
turns on Blink's AutomationControlled runtime feature
(content/child/runtime_features.cc), whose page-visible effect is
Navigator::webdriver() returning true. Patch 001 replaces that getter's
body with "return false", which is what keeps navigator.webdriver
false under this transport. A stock Chrome driven this way reports
navigator.webdriver === true.
"""

import asyncio
import json
import logging
import os
import struct
import subprocess
import sys
import threading
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Fixed by the browser (devtools_pipe_handler.cc / devtools_agent_host.cc).
_BROWSER_READ_FD = 3
_BROWSER_WRITE_FD = 4

# Serializes the "mark pipe handles inheritable -> spawn -> close" window
# so two launches from different threads can never inherit each other's
# pipe ends.
_SPAWN_LOCK = threading.Lock()


class CDPPipeConnection:
    """
    One CDP connection over the browser's debugging pipe.

    Replies are matched to pending commands by message id; events are
    routed to the handler registered for their sessionId (one per
    attached page). A dedicated reader thread does the blocking pipe
    reads and hands complete messages to the event loop, so the loop
    itself never blocks on the browser.
    """

    def __init__(self, read_fd: int, write_fd: int):
        self._read_fd = read_fd
        self._write_fd = write_fd
        self._loop = asyncio.get_running_loop()

        self._next_id = 0
        # id -> (future, method, sessionId)
        self._pending: Dict[int, Tuple[asyncio.Future, str, Optional[str]]] = {}
        # sessionId -> callback(method, params)
        self._session_handlers: Dict[str, Callable[[str, dict], None]] = {}

        self._closed = False
        self._close_reason = "connection closed"
        self._write_lock = threading.Lock()

        self._reader = threading.Thread(
            target=self._read_loop, name="jbium-cdp-pipe-reader", daemon=True
        )
        self._reader.start()

    # ─────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────

    @property
    def closed(self) -> bool:
        return self._closed

    def register_session(self, session_id: str, handler: Callable[[str, dict], None]):
        """Route events carrying `session_id` to `handler(method, params)`."""
        self._session_handlers[session_id] = handler

    def unregister_session(self, session_id: str):
        self._session_handlers.pop(session_id, None)

    async def send(
        self,
        method: str,
        params: Optional[dict] = None,
        session_id: Optional[str] = None,
        timeout: float = 30,
        label: str = "browser-level",
    ) -> dict:
        """Send one command and wait for its reply."""

        if self._closed:
            raise RuntimeError(f"CDP pipe is closed ({self._close_reason}); cannot send {method!r}")

        self._next_id += 1
        msg_id = self._next_id

        message = {"id": msg_id, "method": method}
        if params:
            message["params"] = params
        if session_id:
            message["sessionId"] = session_id

        fut = self._loop.create_future()
        self._pending[msg_id] = (fut, method, session_id)

        # json.dumps escapes every control character (including NUL)
        # inside strings, so the only raw NUL on the wire is the
        # terminator.
        try:
            self._write(json.dumps(message).encode("utf-8") + b"\0")
        except OSError as e:
            self._pending.pop(msg_id, None)
            raise RuntimeError(f"CDP pipe write failed for {method!r}: {e}") from e

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            # Bare asyncio.TimeoutError has no message (str(e) == "") --
            # naming the command that actually hung keeps it diagnosable.
            raise TimeoutError(f"CDP command {method!r} timed out after {timeout:g}s ({label})") from None

    def close(self):
        """
        Close our write end. The browser sees EOF on its command pipe,
        treats it as the client going away, and starts shutting down;
        the reader thread then sees EOF on the reply pipe and closes the
        read end itself (closing an fd another thread is blocked reading
        is unsafe, so only the reader thread ever closes it).
        """

        if self._write_fd is not None:
            with self._write_lock:
                fd, self._write_fd = self._write_fd, None
            try:
                os.close(fd)
            except OSError:
                pass
        self._mark_closed("closed by driver")

    # ─────────────────────────────────────────────
    # Internals
    # ─────────────────────────────────────────────

    def _write(self, data: bytes):
        # Blocking write from the event-loop thread. Commands are small
        # and the browser drains its command pipe on a dedicated thread,
        # so this does not stall the loop in practice.
        with self._write_lock:
            if self._write_fd is None:
                raise OSError("write end already closed")
            view = memoryview(data)
            while view:
                written = os.write(self._write_fd, view)
                view = view[written:]

    def _read_loop(self):
        buf = bytearray()
        reason = "browser closed the pipe"
        try:
            while True:
                chunk = os.read(self._read_fd, 1 << 20)
                if not chunk:
                    break
                scan_from = len(buf)
                buf += chunk
                # Only scan the newly arrived bytes for terminators —
                # large replies (screenshots, page HTML) arrive in many
                # chunks, and rescanning from the start each time would
                # be quadratic.
                start = 0
                nul = buf.find(0, scan_from)
                while nul != -1:
                    raw = bytes(buf[start:nul])
                    if raw:
                        self._post(self._dispatch, raw)
                    start = nul + 1
                    nul = buf.find(0, start)
                if start:
                    del buf[:start]
        except OSError as e:
            reason = f"pipe read failed: {e}"
        finally:
            try:
                os.close(self._read_fd)
            except OSError:
                pass
            self._post(self._on_disconnect, reason)

    def _post(self, fn, arg):
        try:
            self._loop.call_soon_threadsafe(fn, arg)
        except RuntimeError:
            # Event loop already closed (interpreter shutdown) — nothing
            # left to deliver to.
            pass

    def _dispatch(self, raw: bytes):
        try:
            message = json.loads(raw)
        except ValueError:
            logger.warning(f"Discarding malformed CDP message ({len(raw)} bytes)")
            return

        msg_id = message.get("id")
        if msg_id is not None:
            entry = self._pending.pop(msg_id, None)
            if entry:
                fut, method, _ = entry
                if not fut.done():
                    if "error" in message:
                        fut.set_exception(RuntimeError(f"CDP error ({method}): {message['error']}"))
                    else:
                        fut.set_result(message.get("result", {}))
            return

        method = message.get("method")
        if not method:
            return
        params = message.get("params", {})

        if method == "Target.detachedFromTarget":
            detached = params.get("sessionId")
            if detached:
                self._fail_session(detached, "target detached")
                handler = self._session_handlers.pop(detached, None)
                if handler:
                    self._call_handler(handler, method, params)
            return

        session_id = message.get("sessionId")
        if session_id:
            handler = self._session_handlers.get(session_id)
            if handler:
                self._call_handler(handler, method, params)

    @staticmethod
    def _call_handler(handler, method, params):
        try:
            handler(method, params)
        except Exception:
            logger.exception(f"Error in CDP event handler for {method}")

    def _fail_session(self, session_id: str, reason: str):
        for msg_id, (fut, method, sid) in list(self._pending.items()):
            if sid == session_id:
                self._pending.pop(msg_id, None)
                if not fut.done():
                    fut.set_exception(RuntimeError(f"CDP session closed ({reason}) during {method!r}"))

    def _mark_closed(self, reason: str):
        if not self._closed:
            self._closed = True
            self._close_reason = reason
        for msg_id, (fut, method, _) in list(self._pending.items()):
            self._pending.pop(msg_id, None)
            if not fut.done():
                fut.set_exception(RuntimeError(f"CDP pipe closed ({reason}) during {method!r}"))

    def _on_disconnect(self, reason: str):
        logger.debug(f"CDP pipe disconnected: {reason}")
        self._mark_closed(reason)


# ─────────────────────────────────────────────
# Spawning a browser with the debugging pipe on fds 3/4
# ─────────────────────────────────────────────

def spawn_with_cdp_pipe(args: List[str], env: Dict[str, str]):
    """
    Launch `args` with a CDP pipe on the child's fds 3 (commands in) and
    4 (replies out), stdout/stderr piped back, and stdin on the null
    device. Returns (process, read_fd, write_fd), where read_fd/write_fd
    are the parent's ends, ready for CDPPipeConnection.

    `process` is a subprocess.Popen on POSIX; on Windows it is a
    _WindowsProcess exposing the subset of the Popen API the driver
    uses (pid, stdout, stderr, poll, wait, terminate, kill).
    """

    # cmd_*: parent -> browser (browser reads fd 3)
    # res_*: browser -> parent (browser writes fd 4)
    cmd_read, cmd_write = os.pipe()
    res_read, res_write = os.pipe()
    try:
        if sys.platform == "win32":
            process = _spawn_windows(args, env, cmd_read, res_write)
        else:
            process = _spawn_posix(args, env, cmd_read, res_write)
    except BaseException:
        for fd in (cmd_read, cmd_write, res_read, res_write):
            try:
                os.close(fd)
            except OSError:
                pass
        raise

    # The child holds its own copies now. Closing ours is what lets each
    # side see EOF when the other goes away.
    os.close(cmd_read)
    os.close(res_write)
    return process, res_read, cmd_write


def _spawn_posix(args, env, child_read_fd, child_write_fd):
    import fcntl

    # Park the child ends well above 4 (close-on-exec) so the dup2 onto
    # 3/4 below can never clobber one of them mid-way.
    hi_read = fcntl.fcntl(child_read_fd, fcntl.F_DUPFD_CLOEXEC, 10)
    hi_write = fcntl.fcntl(child_write_fd, fcntl.F_DUPFD_CLOEXEC, 10)

    # Popen creates internal pipes of its own (stdout/stderr and its
    # exec-error pipe) while spawning. If fd 3 or 4 happened to be free
    # in this process, one of those could land there and be overwritten
    # by the dup2 in the child. Occupying any free fd <= 4 first rules
    # that out.
    placeholders = []
    try:
        while True:
            fd = os.open(os.devnull, os.O_RDONLY)
            if fd > _BROWSER_WRITE_FD:
                os.close(fd)
                break
            placeholders.append(fd)

        def _map_pipe_fds():
            # Runs in the child between fork and exec. dup2 clears
            # close-on-exec on the target, so 3/4 survive into the
            # browser; hi_read/hi_write are close-on-exec and vanish.
            os.dup2(hi_read, _BROWSER_READ_FD)
            os.dup2(hi_write, _BROWSER_WRITE_FD)

        return subprocess.Popen(
            args,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # close_fds (the default) runs after preexec_fn and closes
            # every fd >= 3 except these two.
            pass_fds=(_BROWSER_READ_FD, _BROWSER_WRITE_FD),
            preexec_fn=_map_pipe_fds,
        )
    finally:
        for fd in placeholders:
            os.close(fd)
        os.close(hi_read)
        os.close(hi_write)


def _spawn_windows(args, env, child_read_fd, child_write_fd):
    """
    Windows has no fork/dup2. The browser's CRT populates fds 0-4 from
    the parent's STARTUPINFO.lpReserved2 block (the same mechanism the
    MSVC CRT uses for _spawn* fd inheritance, and that libuv uses to
    hand a child extra stdio slots). Python's subprocess cannot fill
    lpReserved2, so this calls CreateProcessW directly.
    """

    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.c_void_p),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
        wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
        ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION),
    ]
    kernel32.CreateProcessW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    STARTF_USESTDHANDLES = 0x00000100
    CREATE_UNICODE_ENVIRONMENT = 0x00000400
    # CRT per-fd flags (ucrt internal lowio: FOPEN / FPIPE / FDEV).
    FOPEN, FPIPE, FDEV = 0x01, 0x08, 0x40

    out_read, out_write = os.pipe()
    err_read, err_write = os.pipe()
    null_fd = os.open(os.devnull, os.O_RDONLY)
    child_fds = [null_fd, out_write, err_write, child_read_fd, child_write_fd]
    flags = [FOPEN | FDEV, FOPEN | FPIPE, FOPEN | FPIPE, FOPEN | FPIPE, FOPEN | FPIPE]
    handles = [msvcrt.get_osfhandle(fd) for fd in child_fds]

    # lpReserved2 layout: int count; unsigned char flags[count];
    # HANDLE handles[count] — packed, no padding.
    handle_fmt = "Q" if ctypes.sizeof(ctypes.c_void_p) == 8 else "I"
    reserved2 = struct.pack(
        f"<i{len(handles)}B{len(handles)}{handle_fmt}", len(handles), *flags, *handles
    )
    reserved2_buf = ctypes.create_string_buffer(reserved2, len(reserved2))

    si = STARTUPINFOW()
    si.cb = ctypes.sizeof(STARTUPINFOW)
    si.dwFlags = STARTF_USESTDHANDLES
    si.hStdInput, si.hStdOutput, si.hStdError = handles[0], handles[1], handles[2]
    si.cbReserved2 = len(reserved2)
    si.lpReserved2 = ctypes.cast(reserved2_buf, ctypes.c_void_p)

    pi = PROCESS_INFORMATION()
    command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(args))
    env_block = "".join(
        f"{k}={v}\0" for k, v in sorted(env.items(), key=lambda kv: kv[0].upper())
    ) + "\0"
    env_buf = ctypes.create_unicode_buffer(env_block, len(env_block))

    try:
        with _SPAWN_LOCK:
            for h in handles:
                os.set_handle_inheritable(h, True)
            try:
                ok = kernel32.CreateProcessW(
                    None, command_line, None, None, True,
                    CREATE_UNICODE_ENVIRONMENT, ctypes.cast(env_buf, ctypes.c_void_p),
                    None, ctypes.byref(si), ctypes.byref(pi),
                )
                if not ok:
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                for h in handles:
                    os.set_handle_inheritable(h, False)
    except BaseException:
        os.close(out_read)
        os.close(err_read)
        raise
    finally:
        # The child has its own copies (or failed to start); ours must be
        # closed so EOF propagates when the browser exits. The CDP pipe
        # ends are closed by spawn_with_cdp_pipe.
        os.close(out_write)
        os.close(err_write)
        os.close(null_fd)

    kernel32.CloseHandle(pi.hThread)
    return _WindowsProcess(
        kernel32, pi.hProcess, pi.dwProcessId, args,
        os.fdopen(out_read, "rb"), os.fdopen(err_read, "rb"),
    )


class _WindowsProcess:
    """The subset of subprocess.Popen the driver relies on, over a raw process handle."""

    _WAIT_OBJECT_0 = 0x00000000
    _WAIT_TIMEOUT = 0x00000102
    _INFINITE = 0xFFFFFFFF

    def __init__(self, kernel32, handle, pid, args, stdout, stderr):
        import ctypes
        from ctypes import wintypes

        self._kernel32 = kernel32
        self._handle = handle
        self.pid = pid
        self.args = args
        self.stdout = stdout
        self.stderr = stderr
        self.returncode: Optional[int] = None

        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateProcess.restype = wintypes.BOOL

    def poll(self) -> Optional[int]:
        if self.returncode is None and self._handle:
            if self._kernel32.WaitForSingleObject(self._handle, 0) == self._WAIT_OBJECT_0:
                self._collect_exit_code()
        return self.returncode

    def wait(self, timeout: Optional[float] = None) -> int:
        if self.returncode is not None:
            return self.returncode
        ms = self._INFINITE if timeout is None else max(0, int(timeout * 1000))
        result = self._kernel32.WaitForSingleObject(self._handle, ms)
        if result == self._WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired(self.args, timeout)
        self._collect_exit_code()
        return self.returncode

    def terminate(self):
        if self.poll() is None:
            # Fails harmlessly (access denied) if it exited in between.
            self._kernel32.TerminateProcess(self._handle, 1)

    kill = terminate

    def _collect_exit_code(self):
        import ctypes
        from ctypes import wintypes

        code = wintypes.DWORD()
        if self._kernel32.GetExitCodeProcess(self._handle, ctypes.byref(code)):
            self.returncode = code.value
            self._kernel32.CloseHandle(self._handle)
            self._handle = None

    def __del__(self):
        handle = getattr(self, "_handle", None)
        if handle:
            try:
                self._kernel32.CloseHandle(handle)
            except Exception:
                pass
