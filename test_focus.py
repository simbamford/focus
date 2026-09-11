import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core import target_geometry, angle_delta, write_json, export_session, parse_distance
from focus_app import target_image, App


class MeasurementTests(unittest.TestCase):
    def test_distance_input(self):
        for value in ('infinity', ' INF ', 'Infinity', '∞'):
            self.assertEqual(parse_distance(value), 'infinity')
        self.assertEqual(parse_distance('60'), 60)
        for value in ('nan', '-inf', '0', '-20', ''):
            with self.assertRaises(ValueError):
                parse_distance(value)

    def test_diplopia_report_at_infinity(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder/'samples').mkdir()
            write_json(folder/'samples'/'a.json', dict(block_id='distant', eye='both',
                distance_cm='infinity', photo='photos/a.png', relative_yaw_deg=2,
                relative_pitch_deg=-15, sample_id='a', rating='diplopia', valid=True,
                letter_height_px=None))
            export_session(folder)
            report = (folder/'report.html').read_text(encoding='utf-8')
            self.assertIn('fill="#f4cf32"', report)
            self.assertIn('infinity (external target)', report)
            with (folder/'summary.csv').open(encoding='utf-8-sig', newline='') as f:
                self.assertEqual([r['count'] for r in csv.DictReader(f)], ['0', '0', '1'])

    def test_diplopia_single_eye_shortcut_rejected(self):
        app = App.__new__(App)
        for eye in ('left', 'right'):
            app.block = {'eye': eye}
            app.capture('diplopia')  # Must return before accessing camera/UI state.

    def test_ui_infinity_and_eye_switching(self):
        import tkinter as tk
        from argparse import Namespace
        with tempfile.TemporaryDirectory() as tmp, patch.object(App, 'initialise'):
            root = tk.Tk()
            app = App(root, Namespace(data=Path(tmp), models=Path('models'), camera=0))
            try:
                app.model = object()
                app.variables['distance_cm'].set('infinity')
                app.variables['ruler_mm'].set('')
                with patch('focus_app.messagebox.showerror') as error:
                    app.start_block()
                    error.assert_not_called()
                self.assertEqual(app.canvas.find_withtag('target'), ())
                self.assertIsNone(app.block['letter_height_px'])
                self.assertEqual(str(app.capture_buttons[3]['state']), 'disabled')
                app.centre = ('reference', [0, 0, 0])
                app.update_buttons()
                self.assertEqual(str(app.capture_buttons[3]['state']), 'normal')
                app.start_block()
                app.variables['eye'].set('left')
                app.variables['distance_cm'].set('200')
                app.variables['ruler_mm'].set('100')
                app.start_block()
                self.assertTrue(app.canvas.find_withtag('target'))
                app.centre = ('reference2', [0, 0, 0])
                app.update_buttons()
                self.assertEqual(str(app.capture_buttons[3]['state']), 'disabled')
                self.assertEqual(str(app.capture_buttons[1]['state']), 'normal')
                app.start_block()
                app.variables['distance_cm'].set('∞')
                app.start_block()
                self.assertEqual(app.canvas.find_withtag('target'), ())
            finally:
                app.close()

    def test_snellen_geometry(self):
        g = target_geometry(600, 20, 20, 4)
        self.assertAlmostEqual(g['letter_height_mm'], 8.72665, places=4)
        self.assertAlmostEqual(g['angular_height_arcmin'], 5)
        smaller = target_geometry(600, 30, 20, 4)
        larger = target_geometry(600, 20, 30, 4)
        self.assertLess(smaller['letter_height_mm'], g['letter_height_mm'])
        self.assertGreater(larger['letter_height_mm'], g['letter_height_mm'])
        self.assertAlmostEqual(target_geometry(300, 20, 20, 4)['letter_height_mm']*2, g['letter_height_mm'])

    def test_invalid_geometry(self):
        for bad in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                target_geometry(bad, 20, 20, 4)

    def test_wrapped_difference(self):
        self.assertEqual(angle_delta([179, 5, -179], [-179, 2, 179]), [-2, 3, 2])

    def test_fractional_target_does_not_stretch(self):
        image = target_image(10.1)
        self.assertEqual(image.size, (91, 11))
        # Fractional height leaves most of the final row white, rather than
        # stretching a black vertical stroke to eleven full pixels.
        self.assertGreater(image.getpixel((0, 10))[0], 150)

    def test_exports_preserve_invalid_and_escape_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder/'samples').mkdir()
            base = dict(block_id='test', eye='left', distance_cm=60, photo='photos/test.png',
                        relative_yaw_deg=2, relative_pitch_deg=-3)
            write_json(folder/'samples'/'a.json', dict(base, sample_id='a', rating='focused', valid=True))
            write_json(folder/'samples'/'b.json', dict(base, sample_id='b', rating='unfocused', valid=False, error='<bad>'))
            records = export_session(folder)
            self.assertEqual(len(records), 2)
            with (folder/'results.csv').open(encoding='utf-8-sig', newline='') as f:
                self.assertEqual(len(list(csv.DictReader(f))), 2)
            with (folder/'summary.csv').open(encoding='utf-8-sig', newline='') as f:
                summary = list(csv.DictReader(f))
            self.assertEqual([r['count'] for r in summary], ['1', '0'])
            report = (folder/'report.html').read_text()
            self.assertIn('&lt;bad&gt;', report)
            self.assertNotIn('<bad>', report)

    def test_capture_requires_centre_and_resists_double_trigger(self):
        app = App.__new__(App)
        app.busy = False
        app.block = {'block_id': 'test'}
        app.centre = None
        # Would fail on missing UI attributes if a worker were incorrectly launched.
        app.capture('focused')
        app.capture('unfocused')
        app.centre = ('centre', [0, 0, 0])
        app.capture('centre')
        app.busy = True
        app.capture('focused')


if __name__ == '__main__':
    unittest.main()
