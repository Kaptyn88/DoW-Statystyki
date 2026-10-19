"""Globalne skróty klawiszowe (działają, gdy gra ma fokus): RegisterHotKey w osobnym wątku z własną pętlą komunikatów.

Tk nie przekazuje komunikatów WM_HOTKEY, dlatego wątek odbiera je sam i wkłada nazwy akcji do kolejki, którą podgląd
opróżnia w swojej pętli co 0,1 s (poll()). Zarejestrowany klawisz jest zajęty w całym systemie – także w grze.
"""
import ctypes
import ctypes.wintypes as wt
import os
import queue
import threading

KEYS = [f'F{i}' for i in range(1, 13)]
VK = {f'F{i}': 0x6F + i for i in range(1, 13)}  # VK_F1 = 0x70
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012
MOD_NOREPEAT = 0x4000


class Hotkeys:
    def __init__(self):
        self.events = queue.Queue()
        self.failed = []          # klawisze, których nie udało się zarejestrować (zajęte przez inny program)
        self._thread = None
        self._tid = None

    def set(self, mapping):
        """mapping: akcja -> klawisz ('F1'..'F12'; inny/pusty = brak). Zastępuje poprzednie skróty."""
        self.stop()
        self.failed = []
        keys = {a: k for a, k in mapping.items() if k in VK}
        if os.name != 'nt' or not keys:
            return
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(keys, ready), daemon=True)
        self._thread.start()
        ready.wait(2)

    def _run(self, keys, ready):
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        self._tid = kernel32.GetCurrentThreadId()
        ids = {}
        for i, (action, key) in enumerate(keys.items(), 1):
            if user32.RegisterHotKey(None, i, MOD_NOREPEAT, VK[key]):
                ids[i] = action
            else:
                self.failed.append(key)
        ready.set()
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and msg.wParam in ids:
                self.events.put(ids[msg.wParam])
        for i in ids:
            user32.UnregisterHotKey(None, i)

    def stop(self):
        if self._thread and self._thread.is_alive() and self._tid:
            ctypes.windll.user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(2)
        self._thread = self._tid = None

    def poll(self):
        out = []
        while True:
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                return out
