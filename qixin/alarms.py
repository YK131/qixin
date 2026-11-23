"""Calendar alarm audio and locally managed MP3 imports."""
from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
import tkinter as tk
from ctypes import create_unicode_buffer
import uuid
from pathlib import Path


def import_sound(source: Path, data_dir: Path) -> Path:
    if source.suffix.lower() != ".mp3":
        raise ValueError("请选择 MP3 文件")
    directory = data_dir / "ringtones"
    directory.mkdir(exist_ok=True)
    if source.parent.resolve() == directory.resolve() and source.is_file():
        return source
    digest = hashlib.sha256()
    with tempfile.NamedTemporaryFile(dir=directory, delete=False) as output:
        temporary = Path(output.name)
    try:
        with source.open("rb") as incoming, temporary.open("wb") as outgoing:
            while chunk := incoming.read(65536):
                digest.update(chunk)
                outgoing.write(chunk)
        if not temporary.stat().st_size:
            raise ValueError("文件为空")
        destination = directory / (digest.hexdigest()[:12] + "-" + source.name[:100] + ("" if len(source.name)<=100 else ".mp3"))
        temporary.replace(destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def play_alarm(custom: str):
    fallback = Path(__file__).parent / "assets" / "canon.wav"
    path = Path(custom) if custom and Path(custom).is_file() else fallback
    if os.name == "nt":
        from ctypes import windll
        alias = "qixin" + uuid.uuid4().hex
        send = windll.winmm.mciSendStringW
        kind = "mpegvideo" if path.suffix.lower() == ".mp3" else "waveaudio"
        if send(f'open "{path}" type {kind} alias {alias}', None, 0, None):
            if path != fallback:
                return play_alarm("")
            raise OSError("无法打开铃声")
        def stop():
            send("close " + alias, None, 0, None)
        if send("play " + alias, None, 0, None):
            stop()
            raise OSError("无法播放铃声")
        def playing():
            status = create_unicode_buffer(32)
            error = send("status " + alias + " mode", status, len(status), None)
            return not error and status.value == "playing"
        return stop, playing
    process = subprocess.Popen(["ffplay", "-loglevel", "quiet", "-nodisp", "-autoexit", str(path)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return (lambda: process.terminate() if process.poll() is None else None), (lambda: process.poll() is None)


class AlarmQueue:
    def __init__(self, root):
        self.root = root
        self.window = None
        self.pending = []
        self.active = None
        self.playback = None
        self.job = None

    def add(self, rows):
        if self.window is None:
            self.window = tk.Toplevel(self.root)
            self.window.title("日程闹铃")
            self.window.attributes("-topmost", True)
            from tkinter.scrolledtext import ScrolledText
            self.listing = ScrolledText(self.window, width=36, height=8, wrap="char")
            self.listing.pack(fill="both", expand=True, padx=12, pady=10)
            tk.Button(self.window, text="全部关闭", command=self.window.destroy).pack(pady=8)
            self.window.bind("<Destroy>", self._destroyed)
        self.listing.configure(state="normal")
        for row in rows:
            self.listing.insert("end", f"{row['due']}  {row['title']}\n")
            group = (row["due"], row["alarm_sound"])
            if group != self.active and group not in self.pending:
                self.pending.append(group)
        self.listing.configure(state="disabled")
        if self.job is None:
            self.job = self.window.after_idle(self._advance)

    def _advance(self):
        self.job = None
        if self.playback:
            stop, playing = self.playback
            if playing():
                self.job = self.window.after(250, self._advance)
                return
            stop()
            self.playback = None
        self.active = None
        if self.pending:
            self.active = self.pending.pop(0)
            try:
                self.playback = play_alarm(self.active[1])
            except (OSError, RuntimeError):
                self.window.bell()
            self.job = self.window.after(250, self._advance)

    def _destroyed(self, event):
        if event.widget is self.window:
            if self.job is not None:
                self.window.after_cancel(self.job)
            if self.playback:
                self.playback[0]()
            self.pending.clear()
            self.job = self.active = self.playback = self.window = None
