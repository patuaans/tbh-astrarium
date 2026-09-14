"""Opt-in, hot-attached Auto Stash controller; no game file modifications.

All game actions happen on its main thread in tbh_autostash.js. Off unloads
the agent. The game build must match exactly before any instrumentation.
"""
import ctypes
import json
import queue
import threading
import time
from ctypes import wintypes
from pathlib import Path

from . import probe
from .builds import SUPPORTED_SHA256, require_supported



def game_module_path(pid):
    snap = probe.kernel32.CreateToolhelp32Snapshot(probe.TH32CS_SNAPMODULE | probe.TH32CS_SNAPMODULE32, pid)
    if snap == probe.INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = probe.MODULEENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = probe.kernel32.Module32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szModule.lower() == 'gameassembly.dll':
                return Path(entry.szExePath)
            ok = probe.kernel32.Module32NextW(snap, ctypes.byref(entry))
    finally:
        probe.kernel32.CloseHandle(snap)
    raise RuntimeError('GameAssembly.dll is not loaded')


class AutoStashController:
    mutex_name = 'AutoStash'

    def _configure_agent(self, script):
        script.exports_sync.configure(self.eligible, not self._page_only, sorted(self.protected_ids))

    def _service_requests(self, script):
        """Allow specialized controllers to update a live agent."""
        while True:
            try:
                protected_ids = self._protection_requests.get_nowait()
            except queue.Empty:
                break
            script.exports_sync.setprotected(sorted(protected_ids))

    def __init__(self, agent_path, log_path, catalog):
        self.agent_path = Path(agent_path)
        self.log_path = Path(log_path)
        self.eligible = [int(key) for key, value in catalog.items() if value.get('type') in ('GEAR', 'MATERIAL')]
        self.events = queue.Queue()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None
        self._log_lock = threading.Lock()
        self._page_requests = queue.Queue()
        self._protection_requests = queue.Queue()
        self._page_only = False
        self.protected_ids = set()

    def set_protected_ids(self, item_ids):
        self.protected_ids = {int(value) for value in item_ids}
        if self.running:
            self._protection_requests.put(set(self.protected_ids))
            self._wake.set()

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return False
        self._stop.clear()
        self._wake.clear()
        self._thread = threading.Thread(target=self._run, name='TBH Auto Stash', daemon=True)
        self._thread.start()
        return True

    def open_page(self, page):
        """Select an owned stash page on the Unity main thread."""
        if not isinstance(page, int) or not 1 <= page <= 7:
            raise ValueError('Stash page must be between 1 and 7')
        self._page_requests.put(page)
        if self.running:
            self._wake.set()
            return True
        self._page_only = True
        started = self.start()
        self._wake.set()
        return started

    def stop(self):
        self._stop.set()
        self._wake.set()

    def join(self, timeout=10):
        if self._thread:
            self._thread.join(timeout)

    def drain(self):
        result = []
        while True:
            try:
                result.append(self.events.get_nowait())
            except queue.Empty:
                return result

    def _emit(self, event):
        event = {'time': time.time(), **event}
        self.events.put(event)
        # Logging is diagnostic only; a full or read-only disk must not affect
        # game actions or falsely turn an already confirmed move into failure.
        try:
            with self._log_lock:
                if self.log_path.exists() and self.log_path.stat().st_size > 2_000_000:
                    self.log_path.replace(self.log_path.with_suffix('.previous.jsonl'))
                with self.log_path.open('a', encoding='utf-8') as handle:
                    handle.write(json.dumps(event, ensure_ascii=False) + '\n')
        except OSError:
            pass

    def _run(self):
        session = script = mutex = None
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        try:
            self._emit({'event': 'starting'})
            import frida
            pid = probe.find_pid('TaskBarHero.exe')
            mutex = kernel.CreateMutexW(None, False, f'Local\\TBHStargaze.{self.mutex_name}.{pid}')
            error = ctypes.get_last_error()
            if not mutex:
                raise ctypes.WinError(error)
            if error == 183:
                raise RuntimeError('Auto Stash is already running in another viewer')
            require_supported(game_module_path(pid), 'auto-stash')
            if not self.eligible:
                raise RuntimeError('The item catalog is missing')
            if self._stop.is_set():
                return
            session = frida.attach(pid)
            def detached(reason, crash=None):
                if not self._stop.is_set():
                    self._emit({'event': 'paused', 'reason': f'Game connection ended: {reason}'})
                    self._stop.set()
            session.on('detached', detached)
            script = session.create_script(self.agent_path.read_text(encoding='utf-8'))
            def message(msg, data):
                event = msg.get('payload') if msg.get('type') == 'send' else {'event': 'paused', 'reason': msg.get('description', str(msg))}
                if isinstance(event, dict):
                    self._emit(event)
                    if event.get('event') == 'paused':
                        self._stop.set()
                    if event.get('event') == 'page_opened' and self._page_only:
                        self._stop.set()
            script.on('message', message)
            script.load()
            if self._stop.is_set():
                return
            self._configure_agent(script)
            start = time.monotonic()
            while not self._stop.is_set():
                self._wake.wait(1)
                self._wake.clear()
                if self._stop.is_set():
                    break
                self._service_requests(script)
                while True:
                    try:
                        page = self._page_requests.get_nowait()
                    except queue.Empty:
                        break
                    script.exports_sync.openpage(page - 1)
                state = script.exports_sync.heartbeat()
                if state['state'] == 'starting' and time.monotonic() - start > 15:
                    raise RuntimeError('Game is not updating yet; enable Auto Stash again after loading finishes')
                if self._page_only and time.monotonic() - start > 15:
                    raise RuntimeError('Game did not open the requested stash page')
                if state['state'] == 'full':
                    self._emit({'event': 'status', **state})
        except Exception as exc:
            self._emit({'event': 'paused', 'reason': str(exc)})
        finally:
            self._stop.set()
            if script:
                try:
                    script.exports_sync.stop()
                except Exception:
                    pass
                try:
                    script.unload()
                except Exception:
                    pass
            if session:
                try:
                    session.detach()
                except Exception:
                    pass
            if mutex:
                kernel.CloseHandle(mutex)
            self._page_only = False
            self._emit({'event': 'stopped'})
