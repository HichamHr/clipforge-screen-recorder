SCREEN RECORDER v2.5 — LIVE AREA + CONTROLS — WINDOWS 10 / 11

MAKE AN EXE FOR USERS WITHOUT PYTHON
Double-click Build EXE.bat on your Windows computer. When it finishes, share
dist\ScreenRecorder.exe. Only the build computer needs Python and internet.
See BUILD_EXE.txt for details.

GET STARTED (RUNNING THE PYTHON SOURCE)
1. Install 64-bit Python 3.10 or newer from https://www.python.org/downloads/windows/
   Keep Tcl/Tk and pip enabled. Select Add Python to PATH.
2. Extract this entire ZIP into a folder. Do not run inside the ZIP.
3. Double-click Start Recorder.bat. Setup downloads the recording/audio engines.
   You do not need to install FFmpeg, Stereo Mix, or a virtual audio cable.
   If replacing the earlier version, replace all included files; the launcher
   installs the new audio component even if an old .venv already exists.

LIVE CONTROLS (NEW IN v2.5)
- After selecting an area, its outline stays visible on your desktop.
- Teal means ready; amber means countdown/opening/saving; red means recording.
- The compact floating bar shows the timer, audio mode and REC / STOP.
- Drag the three-dot handle to move the floating bar.
- Open app brings the main window back without stopping the recording.
- Close follows the same save-and-exit behavior as the main window X.
- A large 3-2-1 countdown appears in the selected area before capture starts.
- Start from the MAIN APP, floating REC button, or Start capture on the area
  selection screen. All use the same recording settings and save workflow.
- You can still press Enter to confirm a selection without starting.
- The area is locked during capture; select a new area before the next recording.

The bar is placed outside your recording area wherever space permits. Boundary
strips are click-through on Windows, so they do not block the app underneath.
On supported Windows 10 (2004+) and Windows 11, the recorder requests capture
exclusion for its boundary, toolbar and main window. This is OS-dependent;
check a short recording on your PC. If exclusion is unavailable, keep the main
window and toolbar outside the frame or minimize the main window.

CHOOSE THE SCREEN AREA
- Portrait 9:16: vertical video, 1080 x 1920, 24 fps (for TikTok/Reels/Shorts).
- Landscape 16:9: horizontal video, 1920 x 1080, 24 fps.
- Free area: any rectangle; fits into a portrait or landscape 1080p canvas.
- Click Select area, then drag a rectangle over the PRIMARY monitor.
- In 9:16 or 16:9 mode, the rectangle keeps that exact ratio while you drag.
- Drag inside the existing rectangle to move it. Drag outside to draw again.
- Press Enter to confirm your selection; press Esc to cancel.
- Reset restores the largest centered rectangle of the chosen ratio.
- Changing the format resets the selected area.
- The app displays the source size/location and the final output resolution.

CHOOSE AUDIO
Computer sound: records what plays through your default Windows audio output,
including speakers or headphones. This captures sound from ALL apps using it.
Microphone: records your default Windows WASAPI input device.
Computer + microphone: records both, mixed into one stereo AAC track.
No audio: screen only.

Select the desired default playback and input devices in Windows Sound settings
BEFORE recording. Do not change devices or unplug headphones during capture.
The recorder uses the default input/output of the Windows WASAPI audio system.
If a microphone cannot open, allow microphone access for desktop apps under
Windows Settings > Privacy (or Privacy & security) > Microphone.
Some Bluetooth headsets change audio mode when the microphone is enabled.
Using a separate microphone can avoid that. Headphones help prevent speaker
sound from also being picked up by the microphone when recording both.

RECORD AND SAVE
1. Choose the format, selected area, audio mode and save folder.
2. Press Start recording. There is a 3-second countdown.
3. The app minimizes by default, then opens the capture devices.
4. Restore the app from the taskbar and press Stop & save.
5. Wait while the audio and video are combined into an MP4.
6. Press Open recordings folder to find the recording.

CLOSING THE APP
Click the title-bar X to close. If recording, the app stops and saves first,
then exits automatically without a saved-video popup. While idle or counting
down it closes immediately. Click X a second time while saving to choose
whether to exit immediately or keep waiting. Immediate exit can leave an
incomplete MP4; temporary recovery files are preserved.

The dimmed area-selection screen disappears before recording, but the thin
live outline and floating controls remain visible. Capture exclusion is
requested for these controls and the main app on supported Windows versions.
The selector covers the PRIMARY monitor only. Secondary monitor selection,
pause/resume, webcam and per-app audio filtering are not included.

QUALITY AND RECOVERY
The selected rectangle is scaled to the output dimensions without stretching.
Free-area mode can add black bars. A small source area is upscaled: selecting
1080 x 1920 output cannot recover detail missing from the source pixels.
24 fps output may repeat frames if the PC cannot capture/encode fast enough.
Audio is synchronized using screen timestamps and audio-device timestamps;
driver latency can still affect lip-sync. Test a short recording on your PC.
Protected content and some fullscreen games may appear black or remain silent.

Recording requires a local Windows desktop, not Colab or a web browser.
Keep sufficient disk space: temporary uncompressed audio is stored beside the
recording during capture (roughly 11 MB/minute for 48 kHz stereo per source,
more for multichannel devices), plus temporary and final compressed video.
Wait for saving to finish before shutting down the PC.
On errors, a diagnostic .log and a .recording_ recovery folder are retained
beside the output. Their paths are shown in the error dialog. Do not delete
these until you decide whether to recover the video.mkv or raw .pcm audio.
An audio buffer warning means you should check playback for gaps.

TECHNICAL NOTES
UI: Tkinter, built into the standard python.org Windows installer.
Dependencies: imageio-ffmpeg 0.6.0, PyAudioWPatch 0.2.12.9.
Video: FFmpeg gdigrab, H.264 CPU encoding, ultrafast preset, CRF 20, 24 fps.
Audio: WASAPI loopback and/or input capture; timestamped raw 16-bit PCM;
AAC stereo at 48 kHz / 192 kbps in the finished MP4.
Export measures the actual recorded video length first. Audio padding, input
reading and output duration are all finite; it does not rely on -shortest to
end an unlimited silent audio stream. Percentage progress is shown.
Video capture and export run on a background thread. Audio devices run in
a separate process, so blocked driver cleanup cannot hold the app in Saving.
Audio files are finalized before shutting down the audio driver. The app shows
Saving audio / Finishing screen recording / Combining video and audio.
Audio startup and saving have time limits; screen finalization is limited to
20 seconds and final MP4 export to 120 seconds. On timeout, recovery files stay
in the recordings folder and the app displays an error.

RECOVER A RECORDING THAT TIMED OUT DURING EXPORT
1. Dismiss the old error and close the old recorder before starting v2.5.
2. Keep the .recording_ folder named in the error. Do not delete its files.
3. Open v2.5 and click Recover recording.
4. Select that .recording_ folder INSIDE your recordings folder. It must
   contain video.mkv, plus .pcm audio and audio_ready.json for audio recovery.
5. Recovery measures the video length and exports a new Recovered_*.mp4 next
   to the recovery folder. All original recovery files remain untouched.
Choose any audio mode except No audio to include all available audio tracks
from the recovery folder. Choose No audio for video-only recovery.
Older recovery folders may lack audio sync metadata; their sound can have a
small startup offset. Very early versions without audio_ready.json support
video-only recovery. New recordings retain the sync metadata on failure.

IF AN EARLIER VERSION IS STILL STUCK
Close that old app using Windows Task Manager before launching this version.
Replace all package files and check that the new title bar says v2.5. Existing
.recording_ folders from earlier failed saves are left untouched.
Sources:
https://ffmpeg.org/ffmpeg-devices.html#gdigrab
https://github.com/s0d3s/PyAudioWPatch
https://pypi.org/project/PyAudioWPatch/
