"""Checks that do not access the screen or audio devices."""
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import screen_recorder as app


class ClipForgeTests(unittest.TestCase):
    def test_crop_coordinates_include_scrolled_viewport(self):
        editor = SimpleNamespace(preview_bounds=(10, 20, 200, 400),
                                 canvas=SimpleNamespace(canvasx=lambda x: x+80,
                                                        canvasy=lambda y: y+120))
        self.assertEqual(app.VideoLibrary.image_point(editor, 30, 40), (100, 140))
        self.assertEqual(app.VideoLibrary.image_point(editor, 1000, 1000), (200, 400))

    def test_snapshot_blocks_recording_until_capture_finishes(self):
        recorder = SimpleNamespace(state='idle', preview_busy=True)
        # No session or UI exists: start must return before touching either.
        app.Recorder.start(recorder)

    def test_settings_round_trip_and_invalid_json(self):
        with tempfile.TemporaryDirectory(dir='.') as directory:
            path = Path(directory) / 'preferences' / 'settings.json'
            with patch.object(app, 'settings_path', return_value=path):
                self.assertEqual(app.load_settings(), {})
                preferences = {'folder': 'My Videos', 'mouse': False, 'quality': 'High'}
                app.save_settings(preferences)
                self.assertEqual(app.load_settings(), preferences)
                self.assertFalse(path.with_suffix('.tmp').exists())
                path.write_text('{unfinished', encoding='utf-8')
                self.assertEqual(app.load_settings(), {})
                path.write_text('[]', encoding='utf-8')
                self.assertEqual(app.load_settings(), {})

    def test_cancel_export_removes_partial_output_and_keeps_source(self):
        with tempfile.TemporaryDirectory(dir='.') as directory:
            source = Path(directory) / 'original.mp4'
            source.write_bytes(b'original')
            started = threading.Event()
            process = Mock()
            process.returncode = None
            process.poll.side_effect = lambda: process.returncode
            process.kill.side_effect = lambda: setattr(process, 'returncode', -9)

            def launch(command, **kwargs):
                Path(command[-1]).write_bytes(b'partial export')
                started.set()
                return process

            editor = SimpleNamespace(
                pause_preview=Mock(), busy=False, duration=10,
                start_time=Mock(get=lambda: '0'), end_time=Mock(get=lambda: '10'),
                source=source, crop=None, exe='ffmpeg', win=None,
                export_cancel=threading.Event(), cancel_button=Mock(),
                status=Mock(), events=queue.Queue())
            with patch.object(app.filedialog, 'askdirectory', return_value=directory), \
                    patch.object(app.subprocess, 'Popen', side_effect=launch):
                app.VideoLibrary.export(editor, False)
                self.assertTrue(started.wait(5))
                app.VideoLibrary.cancel_export(editor)
                kind, _, message = editor.events.get(timeout=5)
            self.assertEqual(kind, 'export_error')
            self.assertIn('cancelled', message)
            self.assertEqual(set(Path(directory).glob('*.mp4')), {source})
            self.assertEqual(source.read_bytes(), b'original')
            process.kill.assert_called_once()


if __name__ == '__main__':
    unittest.main()
