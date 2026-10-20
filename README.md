# Screen Recorder

A local Windows desktop screen recorder built with Python and Tkinter. Record a selected screen area with computer sound, microphone audio, or both, then trim, crop, or split videos in the built-in editor.

## Features

- Portrait (9:16), landscape (16:9), and free-area capture on the primary monitor.
- Output resolutions from 720p to 4K, with 24, 30, or 60 fps and three quality levels.
- Computer audio, microphone, mixed audio, or silent recording through Windows WASAPI.
- Three-second countdown, recording timer, live area outline, and draggable floating controls.
- Optional mouse pointer capture and automatic minimization.
- MP4 output with H.264 video and AAC audio when enabled.
- Video library with import, seeking, silent playback preview, trimming, cropping, and splitting.
- Diagnostic logs and recovery export for interrupted or failed saves.
- Standalone Windows EXE packaging with PyInstaller.

## Run from source

Requires Windows 10/11 and 64-bit Python 3.10 or newer with pip and Tcl/Tk installed. Initial dependency setup requires internet access.

1. Download or clone this project into a writable folder. Extract it first if downloaded as a ZIP.
2. Double-click **Start Recorder.bat**.
3. The launcher creates `.venv`, installs the pinned recording dependencies, and opens the app.

Alternatively, run these commands in PowerShell from the project folder:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements.txt
.\.venv\Scripts\python.exe screen_recorder.py
```

FFmpeg is provided by `imageio-ffmpeg`; a separate FFmpeg installation is not required. After setup, recording works locally without an internet connection.

## Record a video

1. Choose the format, capture area, resolution, frame rate, and quality.
2. Choose an audio mode. Set your default Windows playback and microphone devices before recording.
3. Choose a save folder. The default is `Videos\Screen Recordings` under your user folder.
4. Click **Start recording**, or use the floating recording controls.
5. Click **Stop & save**, then wait for export to finish.
6. Open the recordings folder or **Videos • Crop • Split** to view and edit files.

In the area selector, drag to select an area, drag inside the selection to move it, press Enter to confirm, or Esc to cancel. Closing the app during recording requests a stop and save before exiting.

## Build a portable EXE

On a Windows computer with 64-bit Python installed, double-click **Build EXE.bat**. It creates `.build-venv`, installs build dependencies, and packages the app.

The result is:

```text
dist/ScreenRecorder.exe
```

Recipients can run that file without installing Python or FFmpeg. This is a portable app, not an installer. The one-file executable extracts bundled components into a temporary directory on startup, which can add startup time.

Test the built EXE on Windows, including screen capture, both audio sources, editing, and saving before sharing. Rebuild after changing the source. See [BUILD_EXE.txt](BUILD_EXE.txt) for additional packaging details.

## Editing and recovery

The editor imports MP4, MKV, MOV, AVI, and WebM files. Set start/end times to trim, drag on the preview to crop, or position the slider to split into two videos. Exports preserve the original files. Preview playback is silent; exported audio is retained when available.

If recording or saving fails, the app retains a `.recording_` folder and diagnostic log beside the output. Use **Recover recording…** and select the folder containing `video.mkv`. Audio recovery also needs the PCM files and `audio_ready.json`; choose **No audio** for video-only recovery. Keep recovery files until you have checked the recovered output.

## Current limitations

- Windows desktop only; capture selection is limited to the primary monitor.
- No recording pause/resume, global recording shortcuts, webcam overlay, or per-app audio filtering.
- Audio uses default Windows devices; device selection and volume mixing controls are not provided in the app.
- Free-area capture fits a portrait or landscape output canvas and may add black bars. Small capture areas can be upscaled.
- Capture uses CPU H.264 encoding. High resolutions and frame rates may exceed the computer's recording capacity.
- Preview playback is limited to 12 fps and has no audio.
- Capture exclusion for floating controls depends on Windows support. Check a short recording before a longer session.
- Protected content and some fullscreen games may not capture correctly.
- Temporary uncompressed audio and video require additional disk space during recording and export.

For microphone access errors, allow desktop apps in Windows microphone privacy settings. Avoid changing or unplugging audio devices during capture. See [READ_ME.txt](READ_ME.txt) for more troubleshooting and recovery instructions.

## Project files

| File | Purpose |
| --- | --- |
| `screen_recorder.py` | Desktop UI, capture, audio worker, editor, and recovery |
| `Start Recorder.bat` | Source setup and launch |
| `requirements.txt` | Pinned runtime dependencies |
| `Build EXE.bat` | Standalone Windows EXE build |
| `build-requirements.txt` | Runtime dependencies plus PyInstaller |
| `ScreenRecorder.spec` | PyInstaller specification; the build launcher regenerates it |
| `BUILD_EXE.txt` | Detailed build instructions |
| `READ_ME.txt` | Additional usage and troubleshooting notes |

Developed by [hichamhr.com](https://hichamhr.com/).
