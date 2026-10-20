"""ClipForge desktop recorder. Launch with Start Recorder.bat.

UI: Tkinter. Video: FFmpeg gdigrab. Audio: WASAPI via PyAudioWPatch.
Dependencies are imported only when needed so geometry/encoding can be tested
without Windows hardware. Audio and screen access need local Windows 10/11.
"""
import ctypes
from ctypes import wintypes
import datetime as dt
import os
import json
import math
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import webbrowser

FPS = 24
FRAME_RATES = ('24', '30', '60')
RESOLUTIONS = ('720p', '1080p', '1440p', '2160p (4K)')
QUALITY_LEVELS = {'Standard': 26, 'High': 20, 'Maximum': 16}
FORMATS = ('Portrait 9:16', 'Landscape 16:9', 'Free area')
AUDIO_MODES = ('Computer sound', 'Microphone', 'Computer + microphone', 'No audio')
APP_NAME = 'ClipForge'
APP_VERSION = '1.1'
MIN_FREE_BYTES = 512 * 1024 * 1024


def settings_path():
    return Path(os.environ.get('APPDATA', str(Path.home()))) / APP_NAME / 'settings.json'


def load_settings():
    try:
        data = json.loads(settings_path().read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(data):
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temporary.replace(path)


class RecordingHotkeys:
    """Own thread messages so Tk cannot consume global hotkey notifications."""
    def __init__(self, events):
        self.events = events
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        if sys.platform != 'win32':
            return
        user32 = ctypes.windll.user32
        registered = []
        try:
            for identifier, key in [(0x4341, 0x78), (0x4342, 0x79)]:
                if user32.RegisterHotKey(None, identifier, 0x4006, key):
                    registered.append(identifier)
            if len(registered) != 2:
                self.events.put(('shortcut_warning', None))
            message = wintypes.MSG()
            while not self.closed.wait(.05):
                while user32.PeekMessageW(ctypes.byref(message), None, 0x0312, 0x0312, 1):
                    if message.wParam in registered:
                        self.events.put(('shortcut', 'start' if message.wParam == 0x4341 else 'stop'))
        finally:
            for identifier in registered:
                user32.UnregisterHotKey(None, identifier)

    def close(self):
        self.closed.set()
        self.thread.join(timeout=1)

# UI theme and credit link (display only).
THEME = {
    'bg': '#0a0f1c', 'card': '#111a2e', 'field': '#18233d', 'field_hover': '#22315a',
    'line': '#243251', 'text': '#eef3ff', 'muted': '#8d9bb9',
    'accent': '#25cdbb', 'accent_hover': '#43e0cf', 'accent_press': '#1ba899',
    'accent_dim': '#0f2f35', 'on_accent': '#04211d',
    'danger': '#f04452', 'danger_hover': '#ff5a67', 'danger_press': '#c92c3b',
    'warn': '#ffc262', 'disabled_bg': '#0f1729', 'disabled_fg': '#5a6785',
}
DEVELOPER_NAME = 'hichamhr.com'
DEVELOPER_URL = 'https://hichamhr.com/'


def rounded_polygon(canvas, x1, y1, x2, y2, radius, **options):
    """Rounded rectangle for canvas drawings."""
    points = [x1+radius, y1, x2-radius, y1, x2, y1, x2, y1+radius,
              x2, y2-radius, x2, y2, x2-radius, y2, x1+radius, y2,
              x1, y2, x1, y2-radius, x1, y1+radius, x1, y1]
    return canvas.create_polygon(points, smooth=True, **options)


def audio_worker_command(work):
    # A packaged executable already contains this script. Passing __file__ to it
    # would open another UI instead of entering audio-worker mode.
    prefix = [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, str(Path(__file__).resolve())]
    return prefix + ['--audio-worker', str(work)]


def screen_size():
    return (ctypes.windll.user32.GetSystemMetrics(0),
            ctypes.windll.user32.GetSystemMetrics(1))


def aspect_units(mode):
    return (9, 16) if mode == FORMATS[0] else (16, 9) if mode == FORMATS[1] else None


def dragged_region(anchor, point, bounds, units=None):
    """Keep selection inside primary screen; locked ratios use exact integer units."""
    sw, sh = bounds
    ax, ay = min(max(int(anchor[0]), 0), sw), min(max(int(anchor[1]), 0), sh)
    px, py = min(max(int(point[0]), 0), sw), min(max(int(point[1]), 0), sh)
    sx, sy = (1 if px >= ax else -1), (1 if py >= ay else -1)
    w, h = abs(px - ax), abs(py - ay)
    if units:
        u, v = units
        available_w = sw - ax if sx > 0 else ax
        available_h = sh - ay if sy > 0 else ay
        k = int(min(max(w / u, h / v), available_w // u, available_h // v))
        w, h = u * k, v * k
    return min(ax, ax + sx*w), min(ay, ay + sy*h), w, h


def centered_region(bounds, mode):
    sw, sh = bounds
    units = aspect_units(mode)
    if not units:
        return 0, 0, sw, sh
    u, v = units
    k = min(sw // u, sh // v)
    return (sw-u*k)//2, (sh-v*k)//2, u*k, v*k


def output_size(mode, region, resolution='1080p'):
    short = {'720p': 720, '1080p': 1080, '1440p': 1440, '2160p (4K)': 2160}[resolution]
    long = short*16//9
    portrait = mode == FORMATS[0] or (mode == FORMATS[2] and region[2] < region[3])
    return (short, long) if portrait else (long, short)


def toolbar_position(region, bounds, size=(112, 264), gap=12):
    """Prefer a control bar outside the capture area; keep it on the screen."""
    x, y, w, h = region
    sw, sh = bounds
    tw, th = size
    candidates = [(x+w+gap, y+(h-th)//2), (x-tw-gap, y+(h-th)//2),
                  (x+(w-tw)//2, y+h+gap), (x+(w-tw)//2, y-th-gap)]
    def clamp(point):
        return max(0, min(sw-tw, point[0])), max(0, min(sh-th, point[1]))
    def overlap(point):
        px, py = point
        return max(0, min(x+w, px+tw)-max(x, px))*max(0, min(y+h, py+th)-max(y, py))
    return min(map(clamp, candidates), key=overlap)


def border_rectangles(region, bounds, thickness=3):
    x, y, w, h = region
    sw, sh = bounds
    t = thickness
    raw = [(x-t, max(0, y-t), w+2*t, t),
           (x-t, min(sh-t, y+h), w+2*t, t),
           (max(0, x-t), y, t, h), (min(sw-t, x+w), y, t, h)]
    result = []
    for bx, by, bw, bh in raw:
        x1, y1 = max(0, bx), max(0, by)
        x2, y2 = min(sw, bx+bw), min(sh, by+bh)
        if x2 > x1 and y2 > y1:
            result.append((x1, y1, x2-x1, y2-y1))
    return result


def configure_overlay_window(window, click_through=False, tool_window=True):
    """Exclude our own controls from Windows capture; border strips pass clicks."""
    if sys.platform != 'win32':
        return False
    try:
        window.update_idletasks()
        user32 = ctypes.windll.user32
        user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user32.GetAncestor.restype = ctypes.c_void_p
        hwnd = user32.GetAncestor(window.winfo_id(), 2)
        getter = getattr(user32, 'GetWindowLongPtrW', user32.GetWindowLongW)
        setter = getattr(user32, 'SetWindowLongPtrW', user32.SetWindowLongW)
        getter.argtypes = [ctypes.c_void_p, ctypes.c_int]
        getter.restype = ctypes.c_ssize_t
        setter.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        setter.restype = ctypes.c_ssize_t
        style = getter(hwnd, -20)
        if tool_window:
            style |= 0x80  # WS_EX_TOOLWINDOW
        if click_through:
            style |= 0x20 | 0x80000 | 0x8000000  # transparent, layered, no-activate
        setter(hwnd, -20, style)
        if sys.getwindowsversion().build < 19041:
            return False
        user32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        user32.SetWindowDisplayAffinity.restype = ctypes.c_int
        return bool(user32.SetWindowDisplayAffinity(hwnd, 0x11))
    except (AttributeError, OSError, ctypes.ArgumentError, tk.TclError):
        return False


class RecordingOverlay:
    """Live click-through area boundary, compact controls and countdown."""
    def __init__(self, root, region, start, stop, show_app, close):
        self.root, self.region = root, region
        self.start, self.stop = start, stop
        self.bounds = screen_size()
        self.windows = []
        self.countdown = None
        self.drag_anchor = None
        self.excluded = True
        self.state = None
        for x, y, w, h in border_rectangles(region, self.bounds):
            win = tk.Toplevel(root)
            win.overrideredirect(True)
            win.geometry(f'{w}x{h}+{x}+{y}')
            win.configure(bg='#25cdbb')
            win.attributes('-topmost', True)
            win.attributes('-alpha', .99)
            self.excluded = configure_overlay_window(win, True) and self.excluded
            self.windows.append(win)
        self.toolbar = tk.Toplevel(root)
        self.toolbar.overrideredirect(True)
        self.toolbar.attributes('-topmost', True)
        self.toolbar.configure(bg='#0d1422', highlightthickness=1, highlightbackground='#526076')
        x, y = toolbar_position(region, self.bounds)
        self.toolbar.geometry(f'112x264+{x}+{y}')
        self.handle = tk.Label(self.toolbar, text='•••', bg='#0d1422', fg='#94a3b8', cursor='fleur', font=('Segoe UI', 11))
        self.handle.pack(fill='x')
        self.handle.bind('<ButtonPress-1>', self.begin_drag)
        self.handle.bind('<B1-Motion>', self.drag)
        self.pill = tk.Label(self.toolbar, text='READY', bg='#0d1422', fg='#25cdbb', font=('Segoe UI', 9, 'bold'))
        self.pill.pack(pady=(0, 3))
        self.timer = tk.Label(self.toolbar, text='00:00:00', bg='#0d1422', fg='white', font=('Consolas', 12, 'bold'))
        self.timer.pack(pady=(0, 10))
        self.record = tk.Button(self.toolbar, text='● REC', command=start, bg='#f04452', fg='white', activebackground='#dd3344', activeforeground='white', relief='flat', bd=0, font=('Segoe UI', 12, 'bold'), cursor='hand2')
        self.record.pack(fill='x', padx=10, ipady=8)
        self.audio_label = tk.Label(self.toolbar, text='Audio: PC', bg='#0d1422', fg='#bac7d8', font=('Segoe UI', 9), wraplength=98)
        self.audio_label.pack(pady=10)
        self.app_button = tk.Button(self.toolbar, text='Open app', command=show_app, bg='#263246', fg='white', relief='flat', bd=0, font=('Segoe UI', 9), cursor='hand2')
        self.app_button.pack(fill='x', padx=10, ipady=5)
        self.exit_button = tk.Button(self.toolbar, text='×  Close', command=close, bg='#0d1422', fg='#94a3b8', relief='flat', bd=0, font=('Segoe UI', 9), cursor='hand2')
        self.exit_button.pack(fill='x', pady=6)
        self.excluded = configure_overlay_window(self.toolbar) and self.excluded
        self.set_state('idle', '00:00:00', AUDIO_MODES[0])

    def begin_drag(self, event):
        self.drag_anchor = (event.x_root, event.y_root, self.toolbar.winfo_x(), self.toolbar.winfo_y())

    def drag(self, event):
        if not self.drag_anchor:
            return
        ax, ay, px, py = self.drag_anchor
        x = max(0, min(self.bounds[0]-112, px+event.x_root-ax))
        y = max(0, min(self.bounds[1]-264, py+event.y_root-ay))
        self.toolbar.geometry(f'+{x}+{y}')

    def set_state(self, state, clock, audio):
        self.timer.configure(text=clock)
        summary = dict(zip(AUDIO_MODES, ('PC sound', 'Mic', 'PC + Mic', 'Off')))[audio]
        self.audio_label.configure(text='Audio: '+summary)
        if state == self.state:
            return
        self.state = state
        color = '#25cdbb' if state == 'idle' else '#f04452' if state == 'recording' else '#ffc262'
        for win in self.windows:
            win.configure(bg=color)
        pill = {'idle': 'READY', 'countdown': 'GET READY', 'starting': 'OPENING', 'recording': '● LIVE', 'saving': 'SAVING'}
        self.pill.configure(text=pill.get(state, state.upper()), fg=color)
        text = '● REC' if state == 'idle' else 'Saving…' if state == 'saving' else 'Cancel' if state == 'countdown' else '■ STOP'
        self.record.configure(text=text, command=self.start if state == 'idle' else self.stop,
            state='disabled' if state == 'saving' else 'normal')

    def show_countdown(self, value):
        if self.countdown is None:
            self.countdown = tk.Toplevel(self.root)
            self.countdown.overrideredirect(True)
            self.countdown.configure(bg='#0d1422')
            self.countdown.attributes('-topmost', True)
            x, y, w, h = self.region
            cx = max(0, min(self.bounds[0]-120, x+(w-120)//2))
            cy = max(0, min(self.bounds[1]-120, y+(h-120)//2))
            self.countdown.geometry(f'120x120+{cx}+{cy}')
            self.countdown_label = tk.Label(self.countdown, text='', bg='#0d1422', fg='white', font=('Segoe UI', 48, 'bold'))
            self.countdown_label.pack(expand=True)
            configure_overlay_window(self.countdown)
        self.countdown_label.configure(text=str(value))

    def hide_countdown(self):
        if self.countdown is not None:
            self.countdown.destroy()
            self.countdown = None

    def destroy(self):
        self.hide_countdown()
        for win in self.windows+[self.toolbar]:
            try:
                win.destroy()
            except tk.TclError:
                pass


def recording_command(exe, region, size, mouse, target, fps=FPS, crf=20):
    if fps not in (24, 30, 60) or crf not in QUALITY_LEVELS.values():
        raise ValueError("Choose a supported frame rate and quality.")
    x, y, w, h = region
    ow, oh = size
    return [exe, '-hide_banner', '-loglevel', 'info', '-nostats', '-n',
            '-f', 'gdigrab', '-framerate', str(fps), '-draw_mouse', str(int(mouse)),
            '-offset_x', str(x), '-offset_y', str(y), '-video_size', f'{w}x{h}',
            '-i', 'desktop', '-an', '-vf',
            f'scale={ow}:{oh}:force_original_aspect_ratio=decrease:force_divisible_by=2,'
            f'pad={ow}:{oh}:(ow-iw)/2:(oh-ih)/2,setsar=1',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', str(crf),
            '-pix_fmt', 'yuv420p', '-r', str(fps), str(target)]


def duration_from_text(text):
    match = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', text)
    if not match:
        raise RuntimeError('Could not read the recorded video duration. Recovery files have been kept.')
    duration = int(match[1])*3600+int(match[2])*60+float(match[3])
    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError('The video contains no complete frames. Try a recording of at least one second.')
    return duration


def mux_command(exe, video, tracks, target, offset=0.0, *, duration):
    """Tracks are (raw PCM path, sample rate, channels), with a shared zero."""
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('Export requires a positive, finite video duration.')
    if not math.isfinite(offset):
        raise ValueError('Audio offset must be finite.')
    length = f'{duration:.6f}'
    args = [exe, '-hide_banner', '-loglevel', 'warning', '-nostdin', '-n',
            '-nostats', '-stats_period', '0.25', '-progress', 'pipe:1', '-i', str(video)]
    for path, rate, channels in tracks:
        args += ['-f', 's16le', '-ar', str(rate), '-ac', str(channels),
                 '-t', f'{duration+max(0,offset)+.25:.6f}', '-i', str(path)]
    if tracks:
        filters = []
        for i in range(len(tracks)):
            sync = f'atrim=start={offset:.6f},asetpts=PTS-STARTPTS' if offset >= 0 else f'adelay={int(-offset*1000)}:all=1'
            filters.append(f'[{i+1}:a]{sync},aformat=sample_rates=48000:channel_layouts=stereo[a{i}]')
        joined = ''.join(f'[a{i}]' for i in range(len(tracks)))
        if len(tracks) > 1:
            filters.append(f'{joined}amix=inputs={len(tracks)}:duration=longest:normalize=1,apad=whole_dur={length},atrim=duration={length}[aout]')
        else:
            filters.append(f'[a0]apad=whole_dur={length},atrim=duration={length}[aout]')
        args += ['-filter_complex', ';'.join(filters), '-map', '0:v:0', '-map', '[aout]',
                 '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k']
    else:
        args += ['-map', '0:v:0', '-c:v', 'copy', '-an']
    return args + ['-t', length, '-movflags', '+faststart', str(target)]


class TimelineWriter:
    """Raw PCM timeline: fill silence gaps and trim overlapping/early samples."""
    def __init__(self, file, rate, channels):
        self.file, self.rate, self.frame_bytes = file, rate, channels*2
        self.frames = 0

    def silence_to(self, frame):
        remaining = max(0, frame-self.frames)
        while remaining:
            n = min(remaining, self.rate)
            self.file.write(b'\0' * (n*self.frame_bytes))
            self.frames += n
            remaining -= n

    def write(self, seconds, data):
        frame = round(seconds*self.rate)
        # Small timestamp jitter should not continually insert/drop samples.
        if abs(frame-self.frames) <= self.rate*.02 and frame >= 0:
            frame = self.frames
        self.silence_to(max(0, frame))
        skip = max(0, self.frames-frame)*self.frame_bytes
        data = data[skip:]
        usable = len(data)//self.frame_bytes*self.frame_bytes
        self.file.write(data[:usable])
        self.frames += usable//self.frame_bytes


class AudioTrack:
    def __init__(self, manager, pa, kind, path):
        self.path = path
        self.error = None
        self.status_flags = 0
        self.queue = queue.Queue(maxsize=512)
        self.finished = threading.Event()
        self.callback_lock = threading.Lock()
        self.accepting = False
        self.stream = None
        self.writer_thread = None
        self.t0 = 0
        self.end = 0
        if kind == 'computer':
            device = manager.get_default_wasapi_loopback()
        else:
            api = manager.get_host_api_info_by_type(pa.paWASAPI)
            index = int(api['defaultInputDevice'])
            if index < 0:
                raise RuntimeError('No default microphone. Choose one in Windows Sound settings.')
            device = manager.get_device_info_by_index(index)
        self.name = device['name']
        self.rate = int(device['defaultSampleRate'])
        self.channels = int(device['maxInputChannels'])
        if self.channels < 1:
            raise RuntimeError(f'Audio device has no input channels: {self.name}')
        self.pa = pa
        self.stream = manager.open(format=pa.paInt16, channels=self.channels,
            rate=self.rate, input=True, input_device_index=int(device['index']),
            frames_per_buffer=1024, stream_callback=self.callback, start=False)

    def callback(self, data, frame_count, timing, status):
        try:
            with self.callback_lock:
                if not self.accepting:
                    return None, self.pa.paComplete
                return self.capture_callback(data, frame_count, timing, status)
        except Exception as exc:
            self.error = str(exc)
            return None, self.pa.paAbort

    def capture_callback(self, data, frame_count, timing, status):
        try:
            now = time.monotonic()
            adc, current = timing.get('input_buffer_adc_time', 0), timing.get('current_time', 0)
            delta = adc-current
            # PortAudio host times share a clock; map them onto monotonic time.
            timestamp = now+delta if adc > 0 and current > 0 and abs(delta) < 5 else now-frame_count/self.rate
            self.status_flags |= status
            self.queue.put_nowait((timestamp, data or b''))
            return None, self.pa.paContinue
        except queue.Full:
            self.error = 'Audio buffer filled up. Try a shorter recording or a faster disk.'
            return None, self.pa.paAbort
        except Exception as exc:
            self.error = str(exc)
            return None, self.pa.paAbort

    def start(self, t0):
        self.t0 = t0
        self.accepting = True
        self.writer_thread = threading.Thread(target=self.write_audio, daemon=True)
        self.writer_thread.start()
        self.stream.start_stream()

    def write_audio(self):
        try:
            with self.path.open('wb') as f:
                writer = TimelineWriter(f, self.rate, self.channels)
                while not self.finished.is_set() or not self.queue.empty():
                    try:
                        timestamp, data = self.queue.get(timeout=.1)
                    except queue.Empty:
                        continue
                    writer.write(timestamp-self.t0, data)
                    f.flush()
                # Some WASAPI devices send no callbacks while the computer is silent.
                writer.silence_to(max(1, round((self.end-self.t0)*self.rate)))
        except Exception as exc:
            self.error = f'Cannot write audio: {exc}'

    def finish_file(self, end):
        # Finish PCM BEFORE touching a driver that may block in stop_stream.
        with self.callback_lock:
            self.accepting = False
            self.end = end
            self.finished.set()
        if self.writer_thread:
            self.writer_thread.join()

    def close(self, end):
        self.finish_file(end)
        if self.stream:
            try:
                if self.stream.is_active():
                    self.stream.stop_stream()
            finally:
                self.stream.close()
                self.stream = None


def write_signal(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data), encoding='utf-8')
    os.replace(temporary, path)


def audio_worker(work):
    """Hardware lives in a child process; a stuck driver cannot block the UI."""
    manager, tracks = None, []
    try:
        import pyaudiowpatch as pa
        config = json.loads((work/'audio_config.json').read_text(encoding='utf-8'))
        manager = pa.PyAudio()
        for kind in config['kinds']:
            tracks.append(AudioTrack(manager, pa, kind, work/f'{kind}.pcm'))
        write_signal(work/'audio_ready.json', [
            {'path': str(t.path), 'rate': t.rate, 'channels': t.channels, 'name': t.name}
            for t in tracks])
        while not (work/'audio_start.json').exists():
            time.sleep(.05)
        t0 = json.loads((work/'audio_start.json').read_text(encoding='utf-8'))['t0']
        for track in tracks:
            track.start(t0)
        write_signal(work/'audio_started.json', {})
        while not (work/'audio_stop.json').exists():
            for track in tracks:
                if track.error:
                    raise RuntimeError(track.error)
            time.sleep(.05)
        end = json.loads((work/'audio_stop.json').read_text(encoding='utf-8'))['end']
        for track in tracks:
            track.finish_file(end)
            if track.error:
                raise RuntimeError(track.error)
        # Parent can export as soon as files are closed, regardless of driver cleanup.
        write_signal(work/'audio_stopped.json', {'warnings': [t.name for t in tracks if t.status_flags]})
    except Exception as exc:
        write_signal(work/'audio_error.json', {'error': str(exc)})
    finally:
        for track in tracks:
            try:
                track.close(time.monotonic())
            except Exception:
                pass
        if manager:
            manager.terminate()


class AudioProcess:
    def __init__(self, work, mode, abort_event, process_lock=None):
        self.work, self.mode, self.abort_event = work, mode, abort_event
        self.process_lock = process_lock or threading.Lock()
        self.proc = None
        self.descriptors = []

    def check(self):
        error_file = self.work/'audio_error.json'
        if error_file.exists():
            raise RuntimeError(json.loads(error_file.read_text(encoding='utf-8'))['error'])
        if self.abort_event.is_set():
            raise RuntimeError('Recording interrupted. Recovery files have been kept.')
        if self.proc and self.proc.poll() is not None and not (self.work/'audio_stopped.json').exists():
            raise RuntimeError('The audio capture process stopped unexpectedly. See audio_driver.log in the recovery folder.')

    def wait_signal(self, name, timeout):
        deadline = time.monotonic()+timeout
        path = self.work/name
        while not path.exists():
            self.check()
            if time.monotonic() >= deadline:
                raise RuntimeError(f'Audio driver timed out at {name}. Recovery files have been kept.')
            time.sleep(.05)
        self.check()
        return json.loads(path.read_text(encoding='utf-8'))

    def prepare(self):
        kinds = ['computer', 'microphone'] if self.mode == AUDIO_MODES[2] else ['computer' if self.mode == AUDIO_MODES[0] else 'microphone']
        write_signal(self.work/'audio_config.json', {'kinds': kinds})
        with (self.work/'audio_driver.log').open('wb') as log:
            with self.process_lock:
                if self.abort_event.is_set():
                    raise RuntimeError('Recording interrupted.')
                self.proc = subprocess.Popen(audio_worker_command(self.work),
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        devices = self.wait_signal('audio_ready.json', 12)
        self.descriptors = [(Path(d['path']), d['rate'], d['channels']) for d in devices]

    def start(self, t0):
        write_signal(self.work/'audio_start.json', {'t0': t0})
        self.wait_signal('audio_started.json', 8)

    def stop(self, end):
        write_signal(self.work/'audio_stop.json', {'end': end})
        result = self.wait_signal('audio_stopped.json', 8)
        self.shutdown()
        return result['warnings']

    def shutdown(self):
        if self.proc:
            try:
                self.proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=3)


class RecordingSession:
    """Owns hardware and subprocesses on one background thread, never Tk widgets."""
    def __init__(self, exe, region, size, mouse, audio, target, events, fps=FPS, crf=20):
        self.fps, self.crf = fps, crf
        self.exe, self.region, self.size, self.mouse = exe, region, size, mouse
        self.audio, self.target, self.events = audio, target, events
        self.stop_event = threading.Event()
        self.abort_event = threading.Event()
        self.process_lock = threading.Lock()
        self.proc = None
        self.work = None
        self.audio_process = None
        self.log = target.with_suffix('.log')

    def launch(self, cmd, **kwargs):
        # Closing must not race with opening a new capture/export process.
        with self.process_lock:
            if self.abort_event.is_set():
                raise RuntimeError('Recording interrupted. Recovery files have been kept.')
            self.proc = subprocess.Popen(cmd, **kwargs)
            return self.proc

    def abort(self):
        with self.process_lock:
            self.abort_event.set()
            self.stop_event.set()
            if self.proc and self.proc.poll() is None:
                try:
                    self.proc.kill()
                except OSError:
                    pass
            if self.audio_process and self.audio_process.proc and self.audio_process.proc.poll() is None:
                try:
                    self.audio_process.proc.kill()
                except OSError:
                    pass

    def export(self, video, descriptors, offset, log):
        self.events.put(('phase', 'Reading recorded video length…'))
        probe = self.launch([self.exe, '-hide_banner', '-nostdin', '-i', str(video)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            _, metadata = probe.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            probe.kill()
            probe.communicate()
            raise RuntimeError('Reading video length timed out. Recovery files have been kept.')
        duration = duration_from_text(metadata)
        self.events.put(('phase', 'Combining video and audio… 0%'))
        cmd = mux_command(self.exe, video, descriptors, self.target, offset, duration=duration)
        log.write(('\nEXPORT DURATION: '+str(duration)+' seconds\n'+json.dumps(cmd)+'\n').encode())
        log.flush()
        result = self.launch(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=log, text=True, encoding='utf-8', errors='replace',
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

        def progress():
            try:
                last = -1
                for line in result.stdout:
                    if line.startswith('out_time_us='):
                        try:
                            percent = min(99, max(0, int(int(line.strip().split('=', 1)[1])/(duration*10000))))
                        except ValueError:
                            continue
                        if percent != last:
                            self.events.put(('phase', f'Combining video and audio… {percent}%'))
                            last = percent
            finally:
                result.stdout.close()

        reader = threading.Thread(target=progress, daemon=True)
        reader.start()
        try:
            code = result.wait(timeout=120)
        except subprocess.TimeoutExpired:
            result.kill()
            result.wait()
            raise RuntimeError('Video export timed out. Recovery files have been kept.')
        finally:
            reader.join(timeout=3)
        if code:
            raise RuntimeError('Could not combine video and audio. Recovery files have been kept.')
        self.events.put(('phase', 'Export complete • 100%'))

    def run(self):
        warnings = []
        error = None
        try:
            self.work = Path(tempfile.mkdtemp(prefix='.recording_', dir=self.target.parent))
            if self.audio != AUDIO_MODES[3]:
                self.events.put(('phase', 'Opening audio devices…'))
                self.audio_process = AudioProcess(self.work, self.audio, self.abort_event, self.process_lock)
                self.audio_process.prepare()
            if self.stop_event.is_set():
                raise RuntimeError('Recording cancelled before capture started.')
            video = self.work / 'video.mkv'
            with self.log.open('wb') as log:
                t0, wall0 = time.monotonic(), time.time()
                write_signal(self.work/'session.json', {'wall0': wall0})
                if self.audio_process:
                    self.audio_process.start(t0)
                self.launch(recording_command(self.exe, self.region, self.size, self.mouse, video, self.fps, self.crf),
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=log,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                self.events.put(('started', t0))
                while self.proc.poll() is None and not self.stop_event.wait(.1):
                    if self.audio_process:
                        self.audio_process.check()
                    if shutil.disk_usage(self.target.parent).free < 128 * 1024 * 1024:
                        self.events.put(('phase', 'Low disk space • stopping to save recording'))
                        self.stop_event.set()
                requested_stop = self.stop_event.is_set()
                end = time.monotonic()
                if self.proc.poll() is None:
                    try:
                        self.proc.stdin.write(b'q\n')
                        self.proc.stdin.flush()
                    except OSError:
                        pass
                self.events.put(('saving', None))
                if self.audio_process:
                    self.events.put(('phase', 'Saving audio…'))
                    warnings = self.audio_process.stop(end)
                self.events.put(('phase', 'Finishing screen recording…'))
                try:
                    code = self.proc.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait()
                    raise RuntimeError('Video encoder did not finish. Recovery files have been kept.')
                if code != 0 or not requested_stop:
                    raise RuntimeError('Screen capture ended unexpectedly. Check the diagnostic log.')
                if self.proc.stdin:
                    try:
                        self.proc.stdin.close()
                    except OSError:
                        pass
                # gdigrab timestamps are wall-clock seconds. Align the audio timeline
                # to the first captured video packet, excluding encoder startup delay.
                text = self.log.read_text(errors='replace')
                match = re.search(r'Duration: N/A, start: ([0-9]+\.[0-9]+)', text)
                offset = float(match.group(1))-wall0 if match else 0.0
                if abs(offset) > 30:
                    offset = 0.0
                descriptors = self.audio_process.descriptors if self.audio_process else []
                shutil.copyfile(self.log, self.work/'capture.log')
                self.export(video, descriptors, offset, log)
            if not self.target.exists() or not self.target.stat().st_size:
                raise RuntimeError('No video was saved.')
        except Exception as exc:
            error = exc
        finally:
            if self.proc:
                if self.proc.poll() is None:
                    self.proc.kill()
                    self.proc.wait()
                if self.proc.stdin:
                    try:
                        self.proc.stdin.close()
                    except OSError:
                        pass
            if self.audio_process:
                try:
                    self.audio_process.shutdown()
                except Exception:
                    pass
            if error or self.abort_event.is_set():
                try:
                    details = self.log.read_text(errors='replace')[-2600:] if self.log.exists() else ''
                except OSError:
                    details = ''
                self.events.put(('error', f'{error}\n\n{details}\n\nRecovery folder: {self.work}\nLog: {self.log}'))
            elif self.work:
                shutil.rmtree(self.work, ignore_errors=True)
                try:
                    self.log.unlink(missing_ok=True)
                except OSError:
                    pass
                self.events.put(('success', (self.target, warnings)))


class RecoverySession(RecordingSession):
    """Retry export while retaining all original recovery files."""
    def run(self):
        error = None
        try:
            descriptors = []
            ready = self.work/'audio_ready.json'
            if self.audio != AUDIO_MODES[3]:
                if not ready.exists() and list(self.work.glob('*.pcm')):
                    raise RuntimeError('Audio settings are missing from this recovery folder. Choose No audio to recover the video alone.')
                if ready.exists():
                    for item in json.loads(ready.read_text(encoding='utf-8')):
                        pcm = self.work/Path(item['path']).name
                        if not pcm.is_file():
                            raise RuntimeError(f'Missing audio file: {pcm.name}. Choose No audio for video-only recovery.')
                        rate, channels = int(item['rate']), int(item['channels'])
                        if not 1 <= rate <= 384000 or not 1 <= channels <= 64:
                            raise RuntimeError('Invalid audio settings in recovery folder.')
                        descriptors.append((pcm, rate, channels))
            offset = 0.0
            if (self.work/'session.json').exists() and (self.work/'capture.log').exists():
                wall0 = json.loads((self.work/'session.json').read_text(encoding='utf-8'))['wall0']
                text = (self.work/'capture.log').read_text(errors='replace')
                match = re.search(r'Duration: N/A, start: ([0-9]+\.[0-9]+)', text)
                if match and abs(float(match[1])-wall0) <= 30:
                    offset = float(match[1])-wall0
            with self.log.open('wb') as log:
                self.export(self.work/'video.mkv', descriptors, offset, log)
            if not self.target.exists() or not self.target.stat().st_size:
                raise RuntimeError('The recovered video was not saved.')
        except Exception as exc:
            error = exc
        finally:
            if self.proc and self.proc.poll() is None:
                self.proc.kill()
                self.proc.wait()
            if error:
                try:
                    details = self.log.read_text(errors='replace')[-2600:] if self.log.exists() else ''
                except OSError:
                    details = ''
                self.events.put(('error', f'{error}\n\n{details}\n\nOriginal files kept: {self.work}\nLog: {self.log}'))
            else:
                self.events.put(('success', (self.target, [])))


class AreaSelector:
    def __init__(self, root, mode, done):
        self.done, self.mode = done, mode
        self.bounds = screen_size()
        self.region = None
        self.anchor = None
        self.move_origin = None
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.geometry(f'{self.bounds[0]}x{self.bounds[1]}+0+0')
        self.win.attributes('-topmost', True)
        self.win.attributes('-alpha', .55)
        self.canvas = tk.Canvas(self.win, bg='#101827', highlightthickness=0, cursor='crosshair')
        self.canvas.pack(fill='both', expand=True)
        self.canvas.create_text(self.bounds[0]//2, 35, text=f'{mode} • Drag to select • Drag inside to move • Enter to confirm • Esc to cancel', fill='white', font=('Segoe UI', 15, 'bold'), tags='help')
        self.canvas.bind('<ButtonPress-1>', self.press)
        self.canvas.bind('<B1-Motion>', self.drag)
        footer = tk.Frame(self.win, bg='#0d1422', padx=10, pady=8)
        self.use_button = tk.Button(footer, text='Use area', command=self.confirm, state='disabled', relief='flat', padx=14, pady=8,
            bg=THEME['field'], fg=THEME['text'], activebackground=THEME['field_hover'],
            activeforeground=THEME['text'], disabledforeground=THEME['disabled_fg'], bd=0, highlightthickness=0, cursor='hand2', font=('Segoe UI', 10, 'bold'))
        self.use_button.pack(side='left', padx=4)
        self.start_button = tk.Button(footer, text='● Start capture', command=lambda: self.confirm(start_now=True), state='disabled', bg='#f04452', fg='white', activebackground='#dd3344', relief='flat', padx=14, pady=8,
            activeforeground='white', disabledforeground='#ffd0d4', bd=0, highlightthickness=0, cursor='hand2', font=('Segoe UI', 10, 'bold'))
        self.start_button.pack(side='left', padx=4)
        tk.Button(footer, text='Cancel', command=lambda: self.finish(None), relief='flat', padx=14, pady=8,
            bg=THEME['field'], fg=THEME['text'], activebackground=THEME['field_hover'],
            activeforeground=THEME['text'], bd=0, highlightthickness=0, cursor='hand2', font=('Segoe UI', 10, 'bold')).pack(side='left', padx=4)
        self.canvas.create_window(self.bounds[0]//2, self.bounds[1]-50, window=footer, tags='actions')
        self.win.bind('<Return>', self.confirm)
        self.win.bind('<Escape>', lambda e: self.finish(None))
        self.win.protocol('WM_DELETE_WINDOW', lambda: self.finish(None))
        self.win.grab_set()
        self.win.focus_force()

    def press(self, e):
        self.anchor = (e.x, e.y)
        self.move_origin = None
        if self.region:
            x, y, w, h = self.region
            if x < e.x < x+w and y < e.y < y+h:
                self.move_origin = self.region
                return
        self.region = None
        self.canvas.delete('selection')
        self.use_button.configure(state='disabled')
        self.start_button.configure(state='disabled')

    def drag(self, e):
        if self.anchor is None:
            return
        if self.move_origin:
            x, y, w, h = self.move_origin
            x = max(0, min(self.bounds[0]-w, x+e.x-self.anchor[0]))
            y = max(0, min(self.bounds[1]-h, y+e.y-self.anchor[1]))
            self.region = (x, y, w, h)
        else:
            self.region = dragged_region(self.anchor, (e.x, e.y), self.bounds, aspect_units(self.mode))
        self.canvas.delete('selection')
        x, y, w, h = self.region
        valid = 'normal' if min(w, h) >= 32 else 'disabled'
        self.use_button.configure(state=valid)
        self.start_button.configure(state=valid)
        self.canvas.create_rectangle(x, y, x+w, y+h, outline='#62ffe2', width=4, tags='selection')
        self.canvas.create_text(x+w/2, min(self.bounds[1]-20, y+h+20), text=f'{w} × {h} selected • Enter to use', fill='#62ffe2', font=('Segoe UI', 13, 'bold'), tags='selection')

    def confirm(self, e=None, start_now=False):
        if self.region and min(self.region[2:]) >= 32:
            self.finish(self.region, start_now)

    def finish(self, region, start_now=False):
        self.win.grab_release()
        self.win.destroy()
        self.done(region, start_now)


def theme_titlebar(window):
    """Draw a consistent caption; retain the native HWND, taskbar and resize frame."""
    if sys.platform != 'win32' or getattr(window, '_caption_ready', False):
        return
    window._caption_ready = True
    window.update_idletasks()
    user32 = ctypes.windll.user32
    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.GetAncestor.restype = ctypes.c_void_p
    hwnd = user32.GetAncestor(window.winfo_id(), 2)
    getter = getattr(user32, 'GetWindowLongPtrW', user32.GetWindowLongW)
    setter = getattr(user32, 'SetWindowLongPtrW', user32.SetWindowLongW)
    getter.argtypes = [ctypes.c_void_p, ctypes.c_int]
    getter.restype = ctypes.c_ssize_t
    setter.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
    setter.restype = ctypes.c_ssize_t
    bar = tk.Frame(window, bg=THEME['card'], height=36)
    children = [child for child in window.winfo_children() if child is not bar]
    if children:
        bar.pack(side='top', fill='x', before=children[0])
    else:
        bar.pack(side='top', fill='x')
    label = tk.Label(bar, text=window.title(), bg=THEME['card'], fg=THEME['text'],
                     font=('Segoe UI', 10), padx=12, anchor='w')
    label.pack(side='left', fill='x', expand=True)
    def minimize():
        user32.ShowWindow(ctypes.c_void_p(hwnd), 6)
    def maximize(event=None):
        zoomed = user32.IsZoomed(ctypes.c_void_p(hwnd))
        user32.ShowWindow(ctypes.c_void_p(hwnd), 9 if zoomed else 3)
        maximum.configure(text='□' if zoomed else '❐')
    def close():
        # Dispatch through Tk's registered close handler, including safe saving.
        command = window.protocol('WM_DELETE_WINDOW')
        if command:
            window.tk.call(command)
        else:
            window.destroy()
    def button(text, action, hover):
        widget = tk.Button(bar, text=text, command=action, bg=THEME['card'],
            fg=THEME['text'], activebackground=hover, activeforeground='white',
            relief='flat', bd=0, width=5, pady=6, font=('Segoe UI', 11), takefocus=True)
        widget.pack(side='right')
        widget.bind('<Enter>', lambda e: widget.configure(bg=hover))
        widget.bind('<Leave>', lambda e: widget.configure(bg=THEME['card']))
        return widget
    button('×', close, THEME['danger'])
    maximum = button('□', maximize, THEME['field_hover'])
    button('—', minimize, THEME['field_hover'])
    drag_origin = None
    def begin_drag(event):
        nonlocal drag_origin
        if user32.IsZoomed(ctypes.c_void_p(hwnd)):
            user32.ShowWindow(ctypes.c_void_p(hwnd), 9)
            maximum.configure(text='□')
            window.update_idletasks()
            # Restore under the pointer before beginning the move.
            user32.SetWindowPos(ctypes.c_void_p(hwnd), None,
                event.x_root-window.winfo_width()//2, event.y_root-18,
                0, 0, 0x0001 | 0x0004 | 0x0010)
        rect = (ctypes.c_long * 4)()
        user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rect))
        drag_origin = (event.x_root, event.y_root, rect[0], rect[1])
        return 'break'
    def move_drag(event):
        if drag_origin is not None:
            ax, ay, wx, wy = drag_origin
            # Move directly: do not synthesize non-client caption/system-menu clicks.
            user32.SetWindowPos(ctypes.c_void_p(hwnd), None,
                wx+event.x_root-ax, wy+event.y_root-ay, 0, 0,
                0x0001 | 0x0004 | 0x0010)
        return 'break'
    def end_drag(event):
        nonlocal drag_origin
        drag_origin = None
        return 'break'
    def double_click(event):
        end_drag(event)
        maximize()
        return 'break'
    for widget in (bar, label):
        widget.bind('<ButtonPress-1>', begin_drag)
        widget.bind('<B1-Motion>', move_drag)
        widget.bind('<ButtonRelease-1>', end_drag)
        widget.bind('<Double-Button-1>', double_click)
    def apply(event=None):
        if event is not None and event.widget is not window:
            return
        # Remove WS_CAPTION, retain WS_THICKFRAME, WS_SYSMENU and min/max styles.
        style = getter(ctypes.c_void_p(hwnd), -16)
        setter(ctypes.c_void_p(hwnd), -16, (style & ~0x00C00000) | 0x00040000 | 0x00080000 | 0x00030000)
        user32.SetWindowPos(ctypes.c_void_p(hwnd), None, 0, 0, 0, 0,
                            0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020)
    window.bind('<Map>', apply, add='+')
    window.after_idle(apply)


def clip_command(exe, source, target, start, end, crop=None):
    if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end):
        raise ValueError('Choose a valid start and end time.')
    args = [exe, '-hide_banner', '-loglevel', 'error', '-nostdin', '-n',
            '-ss', str(start), '-i', str(source), '-t', str(end-start),
            '-map', '0:v:0', '-map', '0:a:0?']
    if crop:
        x, y, w, h = crop
        if min(w, h) < 2 or min(x, y) < 0:
            raise ValueError('Draw a larger crop rectangle.')
        args += ['-vf', f'crop={w}:{h}:{x}:{y},setsar=1']
    return args + ['-c:v', 'libx264', '-preset', 'fast', '-crf', '20',
                   '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-movflags', '+faststart', str(target)]


class VideoLibrary:
    """Local file browser, frame scrubber and non-destructive FFmpeg exports."""
    def __init__(self, app):
        self.app = app
        self.win = tk.Toplevel(app.root)
        self.win.title('ClipForge • Videos & editor')
        self.win.geometry('1100x740')
        self.win.minsize(850, 650)
        self.win.configure(bg=THEME['bg'])
        self.events = queue.Queue()
        self.source = None
        self.duration = 0
        self.crop = None
        self.busy = False
        self.process = None
        self.export_cancel = threading.Event()
        self.closed = False
        self.token = 0
        self.photo = None
        self.playing = False
        self.play_stop = threading.Event()
        self.play_process = None
        self.seek_job = None
        self.paths = []
        self.exe = __import__('imageio_ffmpeg').get_ffmpeg_exe()
        outer = ttk.Frame(self.win, padding=18)
        outer.pack(fill='both', expand=True)
        sidebar = ttk.Frame(outer, width=230)
        sidebar.pack(side='left', fill='y', padx=(0, 18))
        ttk.Label(sidebar, text='Your videos', style='Title.TLabel').pack(anchor='w', pady=(0, 12))
        self.list = tk.Listbox(sidebar, bg=THEME['field'], fg=THEME['text'],
            selectbackground=THEME['accent_dim'], selectforeground=THEME['accent'],
            highlightthickness=0, relief='flat', width=28, exportselection=False)
        self.list.pack(fill='both', expand=True)
        self.list.bind('<<ListboxSelect>>', self.select)
        for label, callback in [('Import video…', self.import_video), ('Refresh folder', self.refresh),
                                 ('Open selected video', self.open_video)]:
            ttk.Button(sidebar, text=label, command=callback, style='Ghost.TButton').pack(fill='x', pady=(8, 0))
        main = ttk.Frame(outer)
        main.pack(side='left', fill='both', expand=True)
        self.info = tk.StringVar(value='Choose or import a video')
        ttk.Label(main, textvariable=self.info, wraplength=650).pack(fill='x', pady=(0, 10))
        self.canvas = tk.Canvas(main, bg='#050810', highlightthickness=1, highlightbackground=THEME['line'])
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<ButtonPress-1>', self.crop_start)
        self.canvas.bind('<B1-Motion>', self.crop_drag)
        self.canvas.bind('<ButtonRelease-1>', self.crop_end)
        self.canvas.bind('<Configure>', lambda e: self.request_frame())
        self.position = tk.DoubleVar(value=0)
        self.slider = ttk.Scale(main, from_=0, to=1, variable=self.position, command=lambda v: self.request_frame())
        self.slider.pack(fill='x', pady=10)
        transport = ttk.Frame(main)
        transport.pack(fill='x', pady=(0, 8))
        self.play_button = ttk.Button(transport, text='▶ Play', command=self.toggle_play,
                                      style='Accent.TButton')
        self.play_button.pack(side='left')
        ttk.Label(transport, text='Silent preview • audio is kept in exports').pack(side='left', padx=12)

        self.clock = tk.StringVar(value='00:00.00 / 00:00.00')
        ttk.Label(main, textvariable=self.clock).pack(anchor='w')
        row = ttk.Frame(main)
        row.pack(fill='x', pady=10)
        self.start_time = tk.StringVar(value='0')
        self.end_time = tk.StringVar(value='0')
        for label, var in [('Start (seconds)', self.start_time), ('End (seconds)', self.end_time)]:
            ttk.Label(row, text=label).pack(side='left', padx=(0, 6))
            ttk.Entry(row, textvariable=var, width=9).pack(side='left', padx=(0, 12))
        ttk.Button(row, text='Set start here', command=lambda: self.start_time.set(f'{self.position.get():.3f}')).pack(side='left')
        ttk.Button(row, text='Set end here', command=lambda: self.end_time.set(f'{self.position.get():.3f}')).pack(side='left', padx=6)
        ttk.Label(main, text='Drag on the preview to crop. Split uses the current slider position.').pack(anchor='w')
        row = ttk.Frame(main)
        row.pack(fill='x', pady=12)
        for label, cb in [('Reset crop', self.reset_crop), ('Export trim / crop', lambda: self.export(False)),
                          ('Split into 2 videos', lambda: self.export(True))]:
            ttk.Button(row, text=label, command=cb, style='Ghost.TButton').pack(side='left', padx=(0, 8))
        self.status = tk.StringVar(value='Original files are preserved. Preview updates when you seek.')
        self.cancel_button = ttk.Button(main, text='Cancel export', command=self.cancel_export,
                                        state='disabled', style='Ghost.TButton')
        self.cancel_button.pack(anchor='w', pady=(0, 6))
        ttk.Label(main, textvariable=self.status, wraplength=650).pack(fill='x')
        self.win.protocol('WM_DELETE_WINDOW', self.close)
        theme_titlebar(self.win)
        self.refresh()
        self.win.after(100, self.poll)

    def refresh(self):
        folder = Path(self.app.folder.get()).expanduser()
        files = sorted((p for p in folder.glob('*') if p.suffix.lower() in ('.mp4', '.mkv', '.mov', '.avi', '.webm')), key=lambda p: p.stat().st_mtime, reverse=True)
        self.paths = list(dict.fromkeys(files + self.paths))
        self.list.delete(0, 'end')
        for p in self.paths:
            self.list.insert('end', p.name)

    def import_video(self):
        path = filedialog.askopenfilename(parent=self.win, filetypes=[('Videos', '*.mp4 *.mkv *.mov *.avi *.webm')])
        if path:
            p = Path(path)
            if p not in self.paths:
                self.paths.insert(0, p)
            self.refresh()
            index = self.paths.index(p)
            self.list.selection_clear(0, 'end')
            self.list.selection_set(index)
            self.select()

    def open_video(self):
        if self.source:
            os.startfile(str(self.source))

    def select(self, event=None):
        if self.busy or not self.list.curselection():
            return
        self.pause_preview()
        self.source = self.paths[self.list.curselection()[0]]
        self.photo = None
        self.anchor = None
        self.canvas.delete('all')
        self.duration = 0
        self.token += 1
        token, source = self.token, self.source
        self.status.set('Reading video…')
        def worker():
            try:
                result = subprocess.run([self.exe, '-hide_banner', '-i', str(source)], capture_output=True,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=30)
                data = result.stderr.decode(errors='replace')
                duration = duration_from_text(data)
                size = re.search(r'Video:.*?\b(\d{2,6})x(\d{2,6})\b', data)
                if not size:
                    raise ValueError('Cannot read video dimensions.')
                self.events.put(('loaded', token, (duration, int(size[1]), int(size[2]))))
            except Exception as exc:
                self.events.put(('error', token, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def request_frame(self):
        self.pause_preview()
        if self.closed or not self.duration:
            return
        if self.seek_job:
            self.win.after_cancel(self.seek_job)
        self.seek_job = self.win.after(180, self.frame)

    def pause_preview(self):
        if not self.playing:
            return
        self.playing = False
        self.play_stop.set()
        self.token += 1  # Ignore queued frames from the previous playback.
        process = self.play_process
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
        self.play_process = None
        self.play_button.configure(text='▶ Play')

    def toggle_play(self):
        if self.playing:
            self.pause_preview()
            return
        if not self.duration or self.busy:
            return
        if self.seek_job:
            self.win.after_cancel(self.seek_job)
            self.seek_job = None
        at = self.position.get()
        if at >= self.duration-.1:
            at = 0
            self.position.set(0)
        self.playing = True
        self.play_button.configure(text='Ⅱ Pause')
        self.token += 1
        token = self.token
        stop = self.play_stop = threading.Event()
        source = self.source
        scale = min(max(2, self.canvas.winfo_width())/self.width,
                    max(2, self.canvas.winfo_height())/self.height)
        w, h = max(2, int(self.width*scale)), max(2, int(self.height*scale))
        command = [self.exe, '-v', 'error', '-nostdin', '-ss', str(at), '-i', str(source),
                   '-an', '-vf', f'fps=12,scale={w}:{h}', '-f', 'rawvideo',
                   '-pix_fmt', 'rgb24', 'pipe:1']
        # A single decoder per playback; no new FFmpeg process per frame.
        def worker():
            process = None
            try:
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if stop.is_set():
                    return
                self.play_process = process
                index, origin = 0, None
                size = w*h*3
                header = f'P6\n{w} {h}\n255\n'.encode('ascii')
                while not stop.is_set():
                    data = bytearray()
                    while len(data) < size and not stop.is_set():
                        chunk = process.stdout.read(size-len(data))
                        if not chunk:
                            break
                        data.extend(chunk)
                    if len(data) != size or stop.is_set():
                        break
                    if origin is None:
                        origin = time.monotonic()
                    if stop.wait(max(0, origin+index/12-time.monotonic())):
                        break
                    # Bound the event backlog if the UI is busy.
                    if self.events.qsize() < 3:
                        self.events.put(('play_frame', token,
                            (header+bytes(data), w, h, min(self.duration, at+index/12))))
                    index += 1
                if not stop.is_set():
                    if process.wait(timeout=5) != 0:
                        raise RuntimeError('Preview decoder failed. Try another video.')
                    self.events.put(('play_done', token, None))
            except Exception as exc:
                if not stop.is_set():
                    self.events.put(('play_error', token, str(exc)))
            finally:
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    process.wait()
                    process.stdout.close()
        threading.Thread(target=worker, daemon=True).start()

    def frame(self):
        self.seek_job = None
        self.token += 1
        token, source = self.token, self.source
        at = min(self.position.get(), max(0, self.duration-.05))
        self.clock.set(f'{at:.2f}s / {self.duration:.2f}s')
        cw, ch = max(2, self.canvas.winfo_width()), max(2, self.canvas.winfo_height())
        scale = min(cw/self.width, ch/self.height)
        w, h = max(2, int(self.width*scale)), max(2, int(self.height*scale))
        def worker():
            try:
                result = subprocess.run([self.exe, '-v', 'error', '-ss', str(at), '-i', str(source),
                    '-frames:v', '1', '-vf', f'scale={w}:{h}', '-f', 'image2pipe', '-vcodec', 'ppm', 'pipe:1'],
                    capture_output=True, timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                if result.returncode or not result.stdout:
                    raise RuntimeError('Unable to decode this frame.')
                self.events.put(('frame', token, (result.stdout, w, h)))
            except Exception as exc:
                self.events.put(('error', token, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def crop_start(self, e):
        self.pause_preview()
        if not self.photo or self.busy:
            return
        self.anchor = self.image_point(e.x, e.y)
        self.crop = None

    def image_point(self, x, y):
        ox, oy, w, h = self.preview_bounds
        return max(0, min(w, x-ox)), max(0, min(h, y-oy))

    def crop_drag(self, e):
        if not getattr(self, 'anchor', None):
            return
        a, b = self.anchor, self.image_point(e.x, e.y)
        ox, oy, w, h = self.preview_bounds
        self.canvas.delete('crop')
        self.canvas.create_rectangle(ox+a[0], oy+a[1], ox+b[0], oy+b[1], outline=THEME['accent'], width=2, tags='crop')

    def crop_end(self, e):
        if not getattr(self, 'anchor', None):
            return
        a, b = self.anchor, self.image_point(e.x, e.y)
        _, _, w, h = self.preview_bounds
        x = int(min(a[0], b[0])*self.width/w)//2*2
        y = int(min(a[1], b[1])*self.height/h)//2*2
        width = min(self.width-x, int(abs(a[0]-b[0])*self.width/w))//2*2
        height = min(self.height-y, int(abs(a[1]-b[1])*self.height/h))//2*2
        self.anchor = None
        self.crop = (x, y, width, height) if min(width, height) >= 2 else None
        self.status.set(f'Crop: {self.crop}' if self.crop else 'Crop cleared: selection too small.')

    def reset_crop(self):
        self.crop = None
        self.canvas.delete('crop')
        self.status.set('Full frame selected.')

    def export(self, split):
        self.pause_preview()
        if self.busy or not self.duration:
            return
        try:
            start, end = float(self.start_time.get()), float(self.end_time.get())
            if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= self.duration+.001):
                raise ValueError('Times must satisfy 0 ≤ start < end ≤ video duration.')
            if split:
                at = self.position.get()
                if not start+.05 < at < end-.05:
                    raise ValueError('Move the slider between the start and end times to split.')
                ranges = [(start, at), (at, end)]
            else:
                ranges = [(start, end)]
            directory = filedialog.askdirectory(parent=self.win, title='Export videos to', initialdir=str(self.source.parent))
            if not directory:
                return
            stamp = dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            jobs = [(Path(directory)/f'{self.source.stem}_edit_{stamp}_{i+1}.mp4', a, b) for i, (a, b) in enumerate(ranges)]
            commands = [(p, clip_command(self.exe, self.source, p, a, b, self.crop)) for p, a, b in jobs]
        except Exception as exc:
            messagebox.showerror('Check edit settings', str(exc), parent=self.win)
            return
        self.busy = True
        self.export_cancel.clear()
        self.cancel_button.configure(state='normal')
        self.status.set('Exporting… You can keep using the recorder.')
        def worker():
            created = []
            try:
                for path, command in commands:
                    if self.export_cancel.is_set():
                        raise RuntimeError('Export cancelled. Completed files are preserved.')
                    with tempfile.TemporaryFile() as errors:
                        result = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=errors,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                        self.process = result
                        while result.poll() is None:
                            if self.export_cancel.wait(.1):
                                result.kill()
                                result.wait()
                                break
                        errors.seek(0)
                        details = errors.read()[-1800:].decode(errors='replace')
                    if self.export_cancel.is_set() or result.returncode:
                        # Only our newly generated, incomplete export is removed.
                        path.unlink(missing_ok=True)
                        raise RuntimeError('Export cancelled. Completed files are preserved.' if self.export_cancel.is_set() else details)
                    created.append(path)
                self.events.put(('exported', None, created))
            except Exception as exc:
                self.events.put(('export_error', None, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def cancel_export(self):
        if self.busy:
            self.export_cancel.set()
            self.cancel_button.configure(state='disabled')
            self.status.set('Cancelling export…')

    def poll(self):
        if self.closed:
            return
        while not self.events.empty():
            kind, token, payload = self.events.get_nowait()
            if token is not None and token != self.token:
                continue
            if kind == 'loaded':
                self.duration, self.width, self.height = payload
                self.reset_crop()
                self.start_time.set('0')
                self.end_time.set(str(self.duration))
                self.info.set(f'{self.source.name}  •  {self.width} × {self.height}  •  {self.duration:.2f}s')
                self.slider.configure(to=self.duration)
                self.position.set(0)
                self.request_frame()
            elif kind in ('play_done', 'play_error'):
                self.pause_preview()
                if kind == 'play_done':
                    self.position.set(self.duration)
                    self.clock.set(f'{self.duration:.2f}s / {self.duration:.2f}s')
                else:
                    self.status.set(payload)
            elif kind in ('frame', 'play_frame'):
                if kind == 'play_frame':
                    data, w, h, at = payload
                    self.position.set(at)
                    self.clock.set(f'{at:.2f}s / {self.duration:.2f}s')
                else:
                    data, w, h = payload
                self.photo = tk.PhotoImage(data=data, format='PPM')
                ox, oy = (self.canvas.winfo_width()-w)//2, (self.canvas.winfo_height()-h)//2
                self.preview_bounds = ox, oy, w, h
                self.canvas.delete('all')
                self.canvas.create_image(ox, oy, image=self.photo, anchor='nw')
                if self.crop:
                    x, y, cw, ch = self.crop
                    self.canvas.create_rectangle(ox+x*w/self.width, oy+y*h/self.height,
                        ox+(x+cw)*w/self.width, oy+(y+ch)*h/self.height,
                        outline=THEME['accent'], width=2, tags='crop')
            elif kind == 'exported':
                self.busy = False
                self.cancel_button.configure(state='disabled')
                self.paths = list(dict.fromkeys(payload+self.paths))
                self.refresh()
                self.status.set('Saved: '+', '.join(p.name for p in payload))
            elif kind in ('error', 'export_error'):
                if kind == 'export_error':
                    self.busy = False
                    self.cancel_button.configure(state='disabled')
                self.status.set(payload)
        self.win.after(30, self.poll)

    def close(self):
        if self.busy:
            messagebox.showinfo('Export in progress', 'Wait for the export to finish before closing this editor.', parent=self.win)
            return
        self.pause_preview()
        if self.seek_job:
            self.win.after_cancel(self.seek_job)
        self.closed = True
        self.win.destroy()


class Recorder:
    def __init__(self, root):
        self.root, self.state = root, 'idle'
        self.events = queue.Queue()
        self.session = None
        self.generation = 0
        self.region = None
        self.started = 0
        self.close_after_save = False
        self.overlay = None
        self.folder = tk.StringVar(value=str(Path.home()/'Videos'/'Screen Recordings'))
        self.mode = tk.StringVar(value=FORMATS[0])
        self.frame_rate = tk.StringVar(value='24')
        self.resolution = tk.StringVar(value='1080p')
        self.quality = tk.StringVar(value='High')
        self.audio = tk.StringVar(value=AUDIO_MODES[0])
        self.mouse, self.minimize = tk.BooleanVar(value=True), tk.BooleanVar(value=True)
        preferences = load_settings()
        for key, variable, choices in [
                ('mode', self.mode, FORMATS), ('frame_rate', self.frame_rate, FRAME_RATES),
                ('resolution', self.resolution, RESOLUTIONS), ('quality', self.quality, QUALITY_LEVELS),
                ('audio', self.audio, AUDIO_MODES)]:
            if isinstance(preferences.get(key), str) and preferences[key] in choices:
                variable.set(preferences[key])
        if isinstance(preferences.get('folder'), str) and preferences['folder'].strip():
            self.folder.set(preferences['folder'])
        for key, variable in [('mouse', self.mouse), ('minimize', self.minimize)]:
            if isinstance(preferences.get(key), bool):
                variable.set(preferences[key])
        self.status = tk.StringVar(value='Choose your area, then press Start')
        self.clock = tk.StringVar(value='00:00:00')
        self.area_text = tk.StringVar()
        root.title(f'{APP_NAME} {APP_VERSION} • Record & edit')
        self.ui_scale = max(1.0, root.winfo_fpixels('1i') / 96.0)
        root.configure(bg=THEME['bg'])
        self.build_styles()
        self.build_layout()
        root.update_idletasks()
        screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
        width = min(max(self.px(940), root.winfo_reqwidth()), screen_w - self.px(40))
        height = min(max(self.px(660), root.winfo_reqheight()), screen_h - self.px(90))
        root.geometry(f'{width}x{height}+{max(0, (screen_w-width)//2)}+{max(0, (screen_h-height)//3)}')
        root.minsize(min(max(self.px(880), root.winfo_reqwidth()), width),
                     min(max(self.px(640), root.winfo_reqheight()), height))
        root.protocol('WM_DELETE_WINDOW', self.close)
        theme_titlebar(root)
        self.reset_area()
        self.main_excluded = configure_overlay_window(root, tool_window=False)
        self.hotkeys = RecordingHotkeys(self.events)
        root.after(100, self.poll)

    def remember_settings(self):
        try:
            save_settings({key: getattr(self, key).get() for key in
                           ('folder', 'mode', 'frame_rate', 'resolution', 'quality',
                            'audio', 'mouse', 'minimize')})
        except OSError:
            pass

    def px(self, value):
        """Scale a design pixel to the Windows display scaling of this screen."""
        return int(round(value * self.ui_scale))

    def build_styles(self):
        t, ui = THEME, 'Segoe UI'
        # Dark drop-down lists for the comboboxes.
        for option, value in (('background', t['field']), ('foreground', t['text']),
                              ('selectBackground', t['accent']), ('selectForeground', t['on_accent']),
                              ('font', '{Segoe UI} 10'), ('borderWidth', 0), ('relief', 'flat')):
            self.root.option_add(f'*TCombobox*Listbox.{option}', value)
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', background=t['bg'], foreground=t['text'], font=(ui, 10),
                        bordercolor=t['line'], lightcolor=t['line'], darkcolor=t['line'],
                        focuscolor=t['bg'], troughcolor=t['field'])
        style.configure('TFrame', background=t['bg'])
        style.configure('Card.TFrame', background=t['card'])
        style.configure('TLabel', background=t['bg'], foreground=t['text'])
        style.configure('Title.TLabel', font=(ui, 22, 'bold'))
        style.configure('Subtitle.TLabel', foreground=t['muted'])
        style.configure('Heading.TLabel', background=t['card'], font=(ui, 11, 'bold'))
        style.configure('Hint.TLabel', background=t['card'], foreground=t['muted'], font=(ui, 9))
        style.configure('Badge.TLabel', background=t['accent_dim'], foreground=t['accent'],
                        font=(ui, 9, 'bold'), anchor='center', padding=(4, 3))
        style.configure('Time.TLabel', background=t['card'], font=('Consolas', 40, 'bold'))
        style.configure('State.TLabel', background=t['card'], foreground=t['accent'], font=(ui, 9, 'bold'))
        style.configure('Status.TLabel', background=t['card'], foreground=t['muted'])
        style.configure('Footer.TLabel', foreground=t['muted'], font=(ui, 9))
        style.configure('Link.TLabel', foreground=t['accent'], font=(ui, 9, 'bold'))

        def button(name, bg, fg, hover, press, border, border_hover, font, padding):
            off = t['disabled_bg']
            style.configure(name, background=bg, foreground=fg, bordercolor=border, lightcolor=bg,
                            darkcolor=bg, focuscolor=bg, focusthickness=0, borderwidth=1,
                            relief='flat', font=font, padding=padding, anchor='center')
            style.map(name,
                      background=[('disabled', off), ('pressed', press), ('active', hover)],
                      foreground=[('disabled', t['disabled_fg'])],
                      bordercolor=[('disabled', off), ('pressed', press), ('active', border_hover)],
                      lightcolor=[('disabled', off), ('pressed', press), ('active', hover)],
                      darkcolor=[('disabled', off), ('pressed', press), ('active', hover)])

        button('Record.TButton', t['danger'], '#ffffff', t['danger_hover'], t['danger_press'],
               t['danger'], t['danger_hover'], (ui, 12, 'bold'), (18, 12))
        button('Stop.TButton', t['field'], t['text'], t['field_hover'], t['card'],
               t['line'], t['muted'], (ui, 12, 'bold'), (18, 12))
        button('Accent.TButton', t['accent'], t['on_accent'], t['accent_hover'], t['accent_press'],
               t['accent'], t['accent_hover'], (ui, 10, 'bold'), (16, 8))
        button('Ghost.TButton', t['field'], t['text'], t['field_hover'], t['card'],
               t['line'], t['muted'], (ui, 10), (14, 8))

        style.configure('TEntry', fieldbackground=t['field'], foreground=t['text'],
                        insertcolor=t['text'], bordercolor=t['line'], lightcolor=t['line'],
                        darkcolor=t['line'], padding=(10, 8),
                        selectbackground=t['accent'], selectforeground=t['on_accent'])
        style.map('TEntry',
                  fieldbackground=[('disabled', t['disabled_bg'])],
                  foreground=[('disabled', t['disabled_fg'])],
                  bordercolor=[('focus', t['accent'])],
                  lightcolor=[('focus', t['accent'])], darkcolor=[('focus', t['accent'])])
        style.configure('TCombobox', fieldbackground=t['field'], background=t['field'],
                        foreground=t['text'], arrowcolor=t['muted'], bordercolor=t['line'],
                        lightcolor=t['line'], darkcolor=t['line'], padding=(10, 8), arrowsize=16,
                        selectbackground=t['field'], selectforeground=t['text'])
        style.map('TCombobox',
                  fieldbackground=[('disabled', t['disabled_bg']), ('readonly', t['field'])],
                  background=[('disabled', t['disabled_bg']), ('active', t['field_hover']),
                              ('pressed', t['field_hover'])],
                  foreground=[('disabled', t['disabled_fg'])],
                  selectbackground=[('readonly', t['field'])],
                  selectforeground=[('readonly', t['text'])],
                  arrowcolor=[('disabled', t['disabled_fg']), ('active', t['text'])],
                  bordercolor=[('focus', t['accent'])],
                  lightcolor=[('focus', t['accent'])], darkcolor=[('focus', t['accent'])])
        style.configure('Card.TCheckbutton', background=t['card'], foreground=t['text'],
                        font=(ui, 10), indicatorbackground=t['field'],
                        indicatorforeground=t['on_accent'], upperbordercolor=t['line'],
                        lowerbordercolor=t['line'], indicatormargin=(0, 0, 8, 0),
                        focuscolor=t['card'], padding=(0, 4))
        style.map('Card.TCheckbutton',
                  background=[('active', t['card'])],
                  foreground=[('disabled', t['disabled_fg'])],
                  indicatorbackground=[('disabled', t['disabled_bg']), ('selected', t['accent']),
                                       ('!selected', t['field'])],
                  upperbordercolor=[('selected', t['accent'])],
                  lowerbordercolor=[('selected', t['accent'])])

    def make_card(self, parent, number, title):
        t, px = THEME, self.px
        card = tk.Frame(parent, bg=t['card'], highlightthickness=1,
                        highlightbackground=t['line'], highlightcolor=t['line'])
        head = ttk.Frame(card, style='Card.TFrame')
        head.pack(fill='x', padx=px(18), pady=(px(16), px(10)))
        ttk.Label(head, text=str(number), style='Badge.TLabel', width=2, anchor='center').pack(side='left')
        ttk.Label(head, text=title, style='Heading.TLabel').pack(side='left', padx=(px(10), 0))
        content = ttk.Frame(card, style='Card.TFrame')
        content.pack(fill='x', padx=px(18), pady=(0, px(18)))
        return card, content

    def fit_text(self, container, label, margin=0):
        """Keep a wrapping label as wide as the space it sits in."""
        container.bind('<Configure>', lambda e: label.configure(
            wraplength=max(self.px(120), e.width - margin)), add='+')

    def build_layout(self):
        t, px, ui = THEME, self.px, 'Segoe UI'
        outer = ttk.Frame(self.root, padding=(px(28), px(24), px(28), px(14)))
        outer.pack(fill='both', expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        # Header: logo mark, title and tagline.
        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky='ew')
        logo = tk.Canvas(header, width=px(46), height=px(46), bg=t['bg'], highlightthickness=0)
        logo.grid(row=0, column=0, rowspan=2, padx=(0, px(14)))
        rounded_polygon(logo, 1, 1, px(45), px(45), px(13), fill=t['accent_dim'], outline=t['accent'])
        logo.create_oval(px(12), px(12), px(34), px(34), outline=t['text'], width=2)
        logo.create_oval(px(18), px(18), px(28), px(28), fill=t['danger'], outline='')
        ttk.Label(header, text=APP_NAME, style='Title.TLabel').grid(row=0, column=1, sticky='sw')
        ttk.Label(header, text='Your area. Your audio.  •  Custom quality  •  MP4',
                  style='Subtitle.TLabel').grid(row=1, column=1, sticky='nw')

        body = ttk.Frame(outer)
        body.grid(row=1, column=0, sticky='nsew', pady=(px(20), px(12)))
        body.columnconfigure(0, weight=11, uniform='main')
        body.columnconfigure(1, weight=8, uniform='main')
        body.rowconfigure(0, weight=1)

        # Left column: the three setup steps.
        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, px(16)))
        left.columnconfigure(0, weight=1)
        for i in range(3):
            left.rowconfigure(i, weight=1)

        card, content = self.make_card(left, 1, 'Choose a format and recording area')
        card.grid(row=0, column=0, sticky='nsew')
        row = ttk.Frame(content, style='Card.TFrame')
        row.pack(fill='x')
        self.format_box = ttk.Combobox(row, textvariable=self.mode, values=FORMATS, state='readonly', width=21)
        self.format_box.pack(side='left', fill='x', expand=True)
        self.format_box.bind('<<ComboboxSelected>>', self.format_changed)
        self.area_btn = ttk.Button(row, text='Select area…', command=self.select_area, style='Accent.TButton')
        self.area_btn.pack(side='left', padx=(px(8), px(6)))
        self.reset_btn = ttk.Button(row, text='Reset', command=self.reset_area, style='Ghost.TButton')
        self.reset_btn.pack(side='left')
        hint = ttk.Label(content, textvariable=self.area_text, style='Hint.TLabel', justify='left')
        hint.pack(anchor='w', pady=(px(10), 0))
        self.fit_text(content, hint)

        quality_row = ttk.Frame(content, style='Card.TFrame')
        quality_row.pack(fill='x', pady=(px(10), 0))
        self.quality_boxes = []
        for column, (label, variable, values) in enumerate([
                ('Resolution', self.resolution, RESOLUTIONS),
                ('Frame rate (fps)', self.frame_rate, FRAME_RATES),
                ('Quality', self.quality, tuple(QUALITY_LEVELS))]):
            quality_row.columnconfigure(column, weight=1, uniform='quality')
            ttk.Label(quality_row, text=label, style='Hint.TLabel').grid(
                row=0, column=column, sticky='w', padx=(0, px(8)))
            box = ttk.Combobox(quality_row, textvariable=variable, values=values,
                               state='readonly', width=12)
            box.grid(row=1, column=column, sticky='ew', padx=(0, px(8)))
            box.bind('<<ComboboxSelected>>', lambda e: self.update_area())
            self.quality_boxes.append(box)

        card, content = self.make_card(left, 2, 'Choose audio')
        card.grid(row=1, column=0, sticky='nsew', pady=(px(12), 0))
        self.audio_box = ttk.Combobox(content, textvariable=self.audio, values=AUDIO_MODES, state='readonly')
        self.audio_box.pack(fill='x')
        hint = ttk.Label(content, text='Uses your default Windows speakers/headphones and microphone.',
                         style='Hint.TLabel', justify='left')
        hint.pack(anchor='w', pady=(px(10), 0))
        self.fit_text(content, hint)

        card, content = self.make_card(left, 3, 'Save recordings to')
        card.grid(row=2, column=0, sticky='nsew', pady=(px(12), 0))
        row = ttk.Frame(content, style='Card.TFrame')
        row.pack(fill='x')
        self.entry = ttk.Entry(row, textvariable=self.folder)
        self.entry.pack(side='left', fill='x', expand=True)
        self.browse = ttk.Button(row, text='Browse…', command=self.choose, style='Ghost.TButton')
        self.browse.pack(side='right', padx=(px(8), 0))
        toggles = ttk.Frame(content, style='Card.TFrame')
        toggles.pack(fill='x', pady=(px(12), 0))
        self.options = []
        for text, var in [('Show mouse pointer', self.mouse), ('Minimize when recording begins', self.minimize)]:
            c = ttk.Checkbutton(toggles, text=text, variable=var, style='Card.TCheckbutton')
            c.pack(side='left', padx=(0, px(22)))
            self.options.append(c)

        # Right column: live state, timer and the record controls.
        panel = tk.Frame(body, bg=t['card'], highlightthickness=1,
                         highlightbackground=t['line'], highlightcolor=t['line'])
        panel.grid(row=0, column=1, sticky='nsew')
        inner = ttk.Frame(panel, style='Card.TFrame', padding=(px(22), px(20)))
        inner.pack(fill='both', expand=True)
        top = ttk.Frame(inner, style='Card.TFrame')
        top.pack(fill='x')
        ttk.Label(top, text='4', style='Badge.TLabel', width=2, anchor='center').pack(side='left')
        ttk.Label(top, text='Record', style='Heading.TLabel').pack(side='left', padx=(px(10), 0))
        live = ttk.Frame(top, style='Card.TFrame')
        live.pack(side='right')
        self.state_dot = tk.Canvas(live, width=px(12), height=px(12), bg=t['card'], highlightthickness=0)
        self.state_dot.pack(side='left')
        self.state_dot_item = self.state_dot.create_oval(1, 1, px(11), px(11), fill=t['accent'], outline='')
        self.state_text = ttk.Label(live, text='READY', style='State.TLabel')
        self.state_text.pack(side='left', padx=(px(6), 0))

        bottom = ttk.Frame(inner, style='Card.TFrame')
        bottom.pack(side='bottom', fill='x')
        tk.Frame(bottom, height=1, bg=t['line']).pack(fill='x', pady=(0, px(14)))
        ttk.Button(bottom, text='Show floating controls', command=self.restore_floating_bar,
                   style='Ghost.TButton').pack(fill='x', pady=(0, px(8)))
        ttk.Button(bottom, text='Videos • Crop • Split', command=self.open_editor,
                   style='Accent.TButton').pack(fill='x', pady=(0, px(8)))
        ttk.Button(bottom, text='Open recordings folder', command=self.open_folder,
                   style='Ghost.TButton').pack(fill='x')
        self.recovery_btn = ttk.Button(bottom, text='Recover recording…', command=self.recover,
                                       style='Ghost.TButton')
        self.recovery_btn.pack(fill='x', pady=(px(8), 0))

        ttk.Label(inner, textvariable=self.clock, style='Time.TLabel', anchor='center').pack(
            fill='x', pady=(px(22), px(4)))
        status_box = ttk.Frame(inner, style='Card.TFrame', height=px(66))
        status_box.pack(fill='x')
        status_box.pack_propagate(False)
        status = ttk.Label(status_box, textvariable=self.status, style='Status.TLabel',
                           justify='center', anchor='center')
        status.pack(fill='both', expand=True)
        self.fit_text(status_box, status)
        self.start_btn = ttk.Button(inner, text='●  Start recording', command=self.start, style='Record.TButton')
        self.start_btn.pack(fill='x', pady=(px(14), px(8)))
        self.stop_btn = ttk.Button(inner, text='■  Stop & save', command=self.stop, state='disabled',
                                   style='Stop.TButton')
        self.stop_btn.pack(fill='x')

        # Footer: developer credit.
        footer = ttk.Frame(outer)
        footer.grid(row=2, column=0, sticky='ew')
        tk.Frame(footer, height=1, bg=t['line']).pack(fill='x', pady=(0, px(10)))
        credit = ttk.Frame(footer)
        credit.pack(fill='x')
        ttk.Label(credit, text='Developed by', style='Footer.TLabel').pack(side='left')
        link = ttk.Label(credit, text=DEVELOPER_NAME, style='Link.TLabel', cursor='hand2')
        link.pack(side='left', padx=(px(5), 0))
        link.bind('<Button-1>', self.open_developer_site)
        link.bind('<Enter>', lambda e: link.configure(font=(ui, 9, 'bold underline')))
        link.bind('<Leave>', lambda e: link.configure(font=(ui, 9, 'bold')))
        ttk.Label(credit, text=f'Ctrl+Alt+F9: Start • Ctrl+Alt+F10: Stop   |   v{APP_VERSION}', style='Footer.TLabel').pack(side='right')

        self.status.trace_add('write', self.refresh_indicator)
        self.refresh_indicator()

    def refresh_indicator(self, *_):
        """Mirror the recorder state in the panel badge (display only)."""
        t = THEME
        text, color = {
            'idle': ('READY', t['accent']), 'countdown': ('GET READY', t['warn']),
            'starting': ('OPENING', t['warn']), 'recording': ('RECORDING', t['danger']),
            'saving': ('SAVING', t['warn']),
        }.get(self.state, ('READY', t['accent']))
        try:
            self.state_dot.itemconfigure(self.state_dot_item, fill=color)
            self.state_text.configure(text=text, foreground=color)
        except tk.TclError:
            pass

    def open_developer_site(self, event=None):
        try:
            webbrowser.open(DEVELOPER_URL)
        except Exception as exc:
            messagebox.showerror('Cannot open link', str(exc), parent=self.root)

    def open_editor(self):
        try:
            if getattr(self, 'editor', None) and not self.editor.closed:
                self.editor.win.lift()
                self.editor.refresh()
            else:
                self.editor = VideoLibrary(self)
        except Exception as exc:
            messagebox.showerror('Cannot open editor', str(exc), parent=self.root)

    def format_changed(self, e=None):
        self.reset_area()

    def reset_area(self):
        self.region = centered_region(screen_size(), self.mode.get())
        self.update_area()
        if self.overlay:
            self.show_overlay()

    def update_area(self):
        x, y, w, h = self.region
        ow, oh = output_size(self.mode.get(), self.region, self.resolution.get())
        self.area_text.set(f'Area: {w} × {h} at ({x}, {y})  →  Output: {ow} × {oh} • {self.frame_rate.get()} fps • {self.quality.get()}')

    def select_area(self):
        if self.state != 'idle':
            return
        self.hide_overlay()
        self.root.withdraw()
        self.root.after(150, lambda: AreaSelector(self.root, self.mode.get(), self.area_done))

    def area_done(self, region, start_now=False):
        if region:
            self.region = region
            self.update_area()
            self.show_overlay()
        self.root.deiconify()
        if start_now and region:
            self.start()

    def show_overlay(self):
        self.hide_overlay()
        self.overlay = RecordingOverlay(self.root, self.region, self.start, self.stop, self.show_app, self.close_floating_bar)
        self.overlay.set_state(self.state, self.clock.get(), self.audio.get())

    def close_floating_bar(self):
        """Stop/cancel capture, dismiss all overlay windows, keep the app open."""
        if self.state == 'closed':
            return
        if self.state in ('countdown', 'starting', 'recording'):
            self.stop()
        self.hide_overlay()
        self.show_app()

    def restore_floating_bar(self):
        if self.overlay:
            self.overlay.toolbar.deiconify()
            self.overlay.toolbar.lift()
        else:
            self.show_overlay()

    def hide_overlay(self):
        if self.overlay:
            self.overlay.destroy()
            self.overlay = None

    def show_app(self):
        self.root.deiconify()
        self.root.lift()

    def choose(self):
        folder = filedialog.askdirectory(title='Choose where to save recordings')
        if folder:
            self.folder.set(folder)

    def open_folder(self):
        try:
            p = Path(self.folder.get()).expanduser()
            p.mkdir(parents=True, exist_ok=True)
            os.startfile(str(p))
        except Exception as exc:
            messagebox.showerror('Cannot open folder', str(exc))

    def controls(self, busy):
        for w in [self.start_btn, self.browse, self.entry, self.area_btn, self.reset_btn, self.recovery_btn, *self.options]:
            w.configure(state='disabled' if busy else 'normal')
        for w in [self.format_box, self.audio_box, *self.quality_boxes]:
            w.configure(state='disabled' if busy else 'readonly')
        self.stop_btn.configure(state='normal' if busy else 'disabled')

    def recover(self):
        if self.state != 'idle':
            return
        directory = filedialog.askdirectory(title='Choose the .recording_ recovery folder containing video.mkv', initialdir=self.folder.get())
        if not directory:
            return
        try:
            work = Path(directory).resolve()
            if not (work/'video.mkv').is_file():
                raise ValueError('Select a .recording_ folder that contains video.mkv.')
            import imageio_ffmpeg
            target = work.parent/(dt.datetime.now().strftime('Recovered_%Y-%m-%d_%H-%M-%S_%f')+'.mp4')
            self.session = RecoverySession(imageio_ffmpeg.get_ffmpeg_exe(), None, None, False,
                self.audio.get(), target, self.events)
            self.session.work = work
            self.folder.set(str(work.parent))
            self.state = 'saving'
            self.controls(True)
            self.stop_btn.configure(state='disabled')
            self.status.set('Recovering recording… Original files will be kept.')
            threading.Thread(target=self.session.run, daemon=True).start()
        except Exception as exc:
            self.state = 'idle'
            self.controls(False)
            messagebox.showerror('Cannot recover recording', str(exc), parent=self.root)

    def start(self):
        if self.state != 'idle':
            return
        try:
            if not self.folder.get().strip():
                raise ValueError('Please choose a save folder.')
            x, y, w, h = self.region
            sw, sh = screen_size()
            if min(w, h) < 32 or x < 0 or y < 0 or x+w > sw or y+h > sh:
                raise ValueError('The screen layout changed or the area is too small. Select your area again.')
            folder = Path(self.folder.get()).expanduser().resolve()
            folder.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(folder).free < MIN_FREE_BYTES:
                raise ValueError('Less than 512 MB is available. Choose a folder with more free space.')
            self.folder.set(str(folder))
            target = folder/(dt.datetime.now().strftime('Recording_%Y-%m-%d_%H-%M-%S_%f')+'.mp4')
            with target.with_suffix('.check').open('x'):
                pass
            target.with_suffix('.check').unlink()
            import imageio_ffmpeg
            exe = imageio_ffmpeg.get_ffmpeg_exe()
            if self.audio.get() != AUDIO_MODES[3]:
                import pyaudiowpatch  # noqa: F401
            self.session = RecordingSession(exe, self.region, output_size(self.mode.get(), self.region, self.resolution.get()),
                self.mouse.get(), self.audio.get(), target, self.events,
                fps=int(self.frame_rate.get()), crf=QUALITY_LEVELS[self.quality.get()])
        except Exception as exc:
            messagebox.showerror('Cannot start', f'{exc}\n\nRun Start Recorder.bat to set up the required components.')
            return
        self.generation += 1
        self.remember_settings()
        self.state = 'countdown'
        self.controls(True)
        self.clock.set('00:00:00')
        self.show_overlay()
        self.countdown(3, self.generation)

    def countdown(self, remaining, token):
        if self.state != 'countdown' or token != self.generation:
            return
        if remaining:
            self.status.set(f'Recording starts in {remaining}…')
            if self.overlay:
                self.overlay.show_countdown(remaining)
            self.root.after(1000, lambda: self.countdown(remaining-1, token))
            return
        self.state = 'starting'
        if self.overlay:
            self.overlay.hide_countdown()
        self.status.set('Opening screen and audio…')
        if self.minimize.get():
            self.root.iconify()
        # Give the window a moment to disappear before the first captured frame.
        self.root.after(200, lambda: threading.Thread(target=self.session.run, daemon=True).start())

    def stop(self):
        if self.state == 'countdown':
            self.generation += 1
            self.state = 'idle'
            self.controls(False)
            self.status.set('Cancelled • Ready when you are')
            if self.overlay:
                self.overlay.hide_countdown()
        elif self.state in ('recording', 'starting'):
            self.session.stop_event.set()
            self.state = 'saving'
            self.status.set('Saving video and audio… Please wait.')
            self.stop_btn.configure(state='disabled')

    def poll(self):
        if self.state == 'closed':
            return
        if self.state == 'recording':
            seconds = int(time.monotonic()-self.started)
            self.clock.set(f'{seconds//3600:02}:{seconds//60%60:02}:{seconds%60:02}')
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'shortcut':
                self.start() if payload == 'start' else self.stop()
            elif kind == 'shortcut_warning':
                self.status.set('Some global shortcuts are unavailable or already in use')
            elif kind == 'started':
                self.started = payload
                if self.state != 'saving':
                    self.state = 'recording'
                    self.status.set('Recording • Use the floating STOP button or Stop & save here')
            elif kind == 'phase':
                suffix = ' Closing when finished; click × again for exit options.' if self.close_after_save else ''
                self.status.set(payload+suffix)
            elif kind == 'saving':
                self.state = 'saving'
                self.stop_btn.configure(state='disabled')
                self.status.set('Saving before closing… Click × again for exit options.' if self.close_after_save else 'Saving video and audio… Please wait.')
            elif kind in ('success', 'error'):
                self.state = 'idle'
                self.controls(False)
                self.root.deiconify()
                if kind == 'success':
                    target, warnings = payload
                    self.status.set(f'Saved • {target.name}')
                    if self.close_after_save:
                        self.destroy()
                        return
                    note = '\n\nAudio device reported a buffer warning. Check playback for gaps.' if warnings else ''
                    messagebox.showinfo('Video saved', f'Your recording is ready:\n\n{target}{note}', parent=self.root)
                else:
                    self.status.set('Recording failed • See details')
                    messagebox.showerror('Recording could not finish', payload+'\n\nFor microphone issues, allow desktop apps in Windows microphone privacy settings. For computer audio, select your playback device in Windows Sound settings before recording.', parent=self.root)
                    if self.close_after_save:
                        self.destroy()
                        return
        if self.overlay:
            self.overlay.set_state(self.state, self.clock.get(), self.audio.get())
        self.root.after(100, self.poll)

    def close(self):
        if getattr(self, 'editor', None) and not self.editor.closed and self.editor.busy:
            messagebox.showinfo('Export in progress', 'Wait for the video export to finish before closing.', parent=self.root)
            return
        if self.state == 'closed':
            return
        if self.close_after_save:
            if messagebox.askyesno('Exit before saving finishes?',
                    'Saving has not finished yet. Exit now?\n\n'
                    'The final MP4 may be incomplete. Temporary recovery files '
                    'will stay in your recordings folder.\n\n'
                    'Choose No to keep saving.', parent=self.root):
                self.session.abort()
                self.destroy()
        elif self.state in ('recording', 'starting', 'saving'):
            self.close_after_save = True
            self.stop()
            self.status.set('Saving before closing… Click × again for exit options.')
        else:
            self.destroy()

    def destroy(self):
        self.remember_settings()
        self.hotkeys.close()
        if getattr(self, 'editor', None) and not self.editor.closed:
            self.editor.pause_preview()
            self.editor.closed = True
        self.generation += 1
        self.state = 'closed'
        self.hide_overlay()
        self.root.quit()
        self.root.destroy()


def main():
    if sys.platform != 'win32':
        raise SystemExit('This recorder requires a local Windows 10/11 desktop, not Google Colab.')
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()
    root = tk.Tk()
    Recorder(root)
    root.mainloop()


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--audio-worker':
        audio_worker(Path(sys.argv[2]))
    else:
        main()
