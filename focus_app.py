"""Local progressive-lens focus recorder. Run with .venv\\Scripts\\python focus_app.py."""
import argparse
import ctypes
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
import uuid

from core import target_geometry, angle_delta, write_json, export_session, parse_distance, distance_label

DEFAULT_MODELS = Path(r'C:\models\insightface\models\buffalo_l')
DEFAULT_DATA = Path(r'C:\data\focus')

# The bundled Python runtime needs Tcl's scripts alongside this environment.
# Standard Python installations already discover their own scripts.
local_tcl = Path(sys.prefix) / 'tcl'
if (local_tcl / 'tcl8.6' / 'init.tcl').is_file():
    os.environ.setdefault('TCL_LIBRARY', str(local_tcl / 'tcl8.6'))
    os.environ.setdefault('TK_LIBRARY', str(local_tcl / 'tk8.6'))


def utc():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


class PoseModel:
    def __init__(self, folder):
        # Load only the two explicitly local files: no identity embeddings or downloads.
        from insightface.model_zoo import get_model
        import numpy as np
        self.np = np
        for name in ('det_10g.onnx', '1k3d68.onnx'):
            if not (folder / name).is_file():
                raise FileNotFoundError(f'Missing local model: {folder / name}')
        self.detector = get_model(str(folder / 'det_10g.onnx'), providers=['CPUExecutionProvider'])
        self.landmark = get_model(str(folder / '1k3d68.onnx'), providers=['CPUExecutionProvider'])
        self.detector.prepare(ctx_id=-1, input_size=(640, 640), det_thresh=0.6)
        self.landmark.prepare(ctx_id=-1)

    def analyse(self, frame):
        from insightface.app.common import Face
        boxes, keypoints = self.detector.detect(frame, max_num=0)
        if len(boxes) != 1:
            raise ValueError(f'Expected one visible face; detected {len(boxes)}. Capture again.')
        face = Face(bbox=boxes[0, :4], det_score=boxes[0, 4], kps=None if keypoints is None else keypoints[0])
        self.landmark.get(frame, face)
        pose = self.np.asarray(face.pose, dtype=float)
        landmarks = self.np.asarray(face.landmark_3d_68, dtype=float)
        if pose.shape != (3,) or landmarks.shape != (68, 3) or not self.np.isfinite(pose).all() or not self.np.isfinite(landmarks).all():
            raise ValueError('Model returned invalid pose or landmarks.')
        x1, y1, x2, y2 = face.bbox
        h, w = frame.shape[:2]
        if min(x2-x1, y2-y1) < 80 or x1 < 1 or y1 < 1 or x2 >= w-1 or y2 >= h-1:
            raise ValueError('Face is too small or clipped. Adjust the camera and retry.')
        return dict(pose=pose.tolist(), landmarks=landmarks.tolist(), bbox=face.bbox.tolist(),
                    detection_score=float(face.det_score), face_width_px=float(x2-x1), face_height_px=float(y2-y1))


class Camera:
    def __init__(self, index):
        import cv2
        self.cv2 = cv2
        self.cap = cv2.VideoCapture(index, cv2.CAP_DSHOW if os.name == 'nt' else cv2.CAP_ANY)
        if not self.cap.isOpened() and os.name == 'nt':
            self.cap.release()
            self.cap = cv2.VideoCapture(index, cv2.CAP_MSMF)
        if not self.cap.isOpened():
            self.cap.release()
            raise RuntimeError(f'Cannot open camera {index}. Check Windows camera permissions and close other camera apps.')
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        self.condition = threading.Condition()
        self.latest = None
        self.stopped = False
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        try:
            while not self.stopped:
                ok, frame = self.cap.read()
                with self.condition:
                    if ok:
                        self.latest = (time.monotonic(), utc(), frame)
                    self.condition.notify_all()
                if not ok:
                    time.sleep(0.05)
        finally:
            self.cap.release()

    def snapshot(self, after):
        deadline = time.monotonic() + 3
        with self.condition:
            while not self.stopped and time.monotonic() < deadline:
                if self.latest is not None and self.latest[0] >= after:
                    stamp, date, frame = self.latest
                    if stamp - after > 0.5:
                        raise RuntimeError('Camera capture was delayed more than 500 ms. Please retry.')
                    return frame.copy(), date, (stamp-after)*1000
                self.condition.wait(0.05)
        raise RuntimeError('No fresh camera frame; check the camera connection.')

    def close(self):
        self.stopped = True
        with self.condition:
            self.condition.notify_all()


# Five-unit block glyphs give an explicitly controlled letter height and stroke width.
# This is a geometric target, not a validated clinical optotype chart.
GLYPHS = {'H': ['10001','10001','11111','10001','10001'],
          'E': ['11111','10000','11110','10000','11111'],
          'F': ['11111','10000','11110','10000','10000'],
          'T': ['11111','00100','00100','00100','00100']}
TARGET = 'H E F T H'


def target_image(height):
    from PIL import Image, ImageDraw
    scale = 8
    width = height * 9
    im = Image.new('RGB', (math.ceil(width)*scale, math.ceil(height)*scale), 'white')
    draw = ImageDraw.Draw(im)
    unit = height*scale/5
    for i, letter in enumerate(TARGET.split()):
        for y, row in enumerate(GLYPHS[letter]):
            for x, cell in enumerate(row):
                if cell == '1':
                    left = (i*10+x)*unit
                    draw.rectangle((round(left), round(y*unit), round(left+unit)-1, round((y+1)*unit)-1), fill='black')
    return im.resize((math.ceil(width), math.ceil(height)), Image.Resampling.LANCZOS)


class App:
    def __init__(self, root, args):
        self.root, self.args = root, args
        self.camera = self.model = self.session = self.block = self.centre = None
        self.busy = False
        self.events = queue.Queue()
        self.closed = False
        root.title('Focus — progressive lens observations')
        root.attributes('-fullscreen', True)
        root.configure(bg='white')
        root.bind('<Escape>', lambda e: self.close())
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.screen = (root.winfo_screenwidth(), root.winfo_screenheight())
        self.canvas = tk.Canvas(root, height=130, bg='white', highlightthickness=0)
        self.canvas.pack(fill='x')
        self.canvas.create_text(self.screen[0]/2, 38, text='H E F T H', font=('Arial', 18), tags='target')
        body = ttk.Frame(root, padding=24)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='Focus recorder', font=('Segoe UI', 22, 'bold')).pack(anchor='w')
        ttk.Label(body, text='Look at the letters, or above the webcam for infinity. Use C, F, U; D = double vision (both eyes).').pack(anchor='w', pady=8)
        self.form = ttk.Frame(body)
        self.form.pack(anchor='w', pady=8)
        self.variables = {}
        self.inputs = []
        settings = [('eye', 'Eye(s) being tested', 'both'), ('distance_cm', 'Distance (cm or infinity)', '60'),
                    ('numerator', 'Snellen numerator (default 20/20)', '20'), ('denominator', 'Snellen denominator (default 20/20)', '20'),
                    ('ruler_mm', 'Measured length of the 400-pixel line (mm)', ''),
                    ('notes', 'Glasses / lighting / notes', '')]
        config = args.data / 'calibration.json'
        saved = {}
        if config.exists():
            try:
                saved = json.loads(config.read_text())
            except (ValueError, OSError):
                pass
        for row, (key, label, default) in enumerate(settings):
            ttk.Label(self.form, text=label).grid(row=row, column=0, sticky='w', padx=(0, 16), pady=5)
            value = saved.get('ruler_mm', '') if key == 'ruler_mm' and saved.get('screen_px') == list(self.screen) else default
            var = tk.StringVar(value=value)
            self.variables[key] = var
            widget = ttk.Combobox(self.form, textvariable=var, values=['left', 'right', 'both'], state='readonly', width=36) if key == 'eye' else ttk.Entry(self.form, textvariable=var, width=40)
            widget.grid(row=row, column=1, sticky='w')
            self.inputs.append(widget)
        ruler = tk.Canvas(body, width=440, height=45, bg='white', highlightthickness=0)
        ruler.pack(anchor='w')
        ruler.create_line(20, 20, 420, 20, width=1)
        for x in (20, 420):
            ruler.create_line(x, 10, x, 30)
        ttk.Label(body, text='Measure between the two end ticks with a physical ruler. Recheck after display/scaling changes.').pack(anchor='w')
        self.start = ttk.Button(body, text='Start new eye / distance block', command=self.start_block)
        self.start.pack(anchor='w', pady=12)
        buttons = ttk.Frame(body)
        buttons.pack(anchor='w', pady=8)
        self.capture_buttons = []
        for label, rating, key in [('Centred  [C]', 'centre', 'c'), ('Focused  [F]', 'focused', 'f'), ('Unfocused  [U]', 'unfocused', 'u'), ('Double vision  [D]', 'diplopia', 'd')]:
            b = ttk.Button(buttons, text=label, command=lambda r=rating: self.capture(r), state='disabled')
            b.pack(side='left', padx=(0, 16), ipady=12, ipadx=18)
            self.capture_buttons.append(b)
            root.bind(key, lambda e, r=rating: self.key_capture(r))
            root.bind(key.upper(), lambda e, r=rating: self.key_capture(r))
        self.status = tk.StringVar(value='Loading the local models and camera…')
        ttk.Label(body, textvariable=self.status, wraplength=max(600, self.screen[0]-80), font=('Segoe UI', 12)).pack(anchor='w', pady=12)
        self.details = tk.StringVar(value='')
        ttk.Label(body, textvariable=self.details, wraplength=max(600, self.screen[0]-80)).pack(anchor='w')
        footer = ttk.Frame(body)
        footer.pack(side='bottom', anchor='w', pady=12)
        ttk.Button(footer, text='Open results report', command=self.open_report).pack(side='left', padx=(0, 15))
        ttk.Button(footer, text='Finish / exit', command=self.close).pack(side='left')
        self.start.configure(state='disabled')
        threading.Thread(target=self.initialise, daemon=True).start()
        root.after(50, self.poll)

    def initialise(self):
        try:
            model = PoseModel(self.args.models)
            camera = Camera(self.args.camera)
            if self.closed:
                camera.close()
                return
            self.events.put(('ready', (model, camera)))
        except Exception as exc:
            self.events.put(('error', str(exc)))

    def poll(self):
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == 'ready':
                    self.model, self.camera = payload
                    self.start.configure(state='normal')
                    self.status.set('Ready. Measure the ruler line, enter the viewing distance, then start a block.')
                elif event == 'error':
                    self.status.set(f'Error: {payload}')
                    self.busy = False
                    self.update_buttons()
                elif event == 'saved':
                    record, pose, report_error = payload
                    self.busy = False
                    if record['valid'] and record['rating'] == 'centre':
                        self.centre = (record['sample_id'], pose)
                    if record['valid']:
                        target = 'your distant target above the webcam' if record['distance_cm'] == 'infinity' else 'the letters'
                        keys = 'F, U or D' if record['eye'] == 'both' else 'F or U'
                        self.status.set(f"Saved {record['rating']}: yaw {record['relative_yaw_deg']:+.1f}°, pitch {record['relative_pitch_deg']:+.1f}°. Look at {target}; press {keys}.")
                    else:
                        self.status.set(f"Capture saved but rejected: {record['error']} Please retry.")
                    if report_error:
                        self.status.set(self.status.get() + f' Table/report export failed: {report_error}. Close the CSV in Excel and use Open results report to rebuild.')
                    self.update_buttons()
        except queue.Empty:
            pass
        if not self.closed:
            self.root.after(50, self.poll)

    def update_buttons(self):
        for i, button in enumerate(self.capture_buttons):
            allowed = self.block is not None and not self.busy and ((i == 0 and self.centre is None) or (i > 0 and self.centre is not None))
            if i == 3:
                allowed = allowed and self.block['eye'] == 'both'
            button.configure(state='normal' if allowed else 'disabled')
        if self.model is not None:
            self.start.configure(state='disabled' if self.busy else 'normal')

    def start_block(self):
        if self.block is not None:
            self.block = self.centre = None
            for widget in self.inputs:
                widget.configure(state='readonly' if isinstance(widget, ttk.Combobox) else 'normal')
            self.start.configure(text='Start new eye / distance block')
            self.status.set('Choose the next eye / distance, then start a block and declare centre again.')
            self.update_buttons()
            return
        try:
            config = {k: v.get() for k, v in self.variables.items()}
            config['distance_cm'] = parse_distance(config['distance_cm'])
            infinity = config['distance_cm'] == 'infinity'
            for k in ('numerator', 'denominator', 'ruler_mm'):
                if infinity:
                    config[k] = None
                    continue
                config[k] = float(config[k])
                if not math.isfinite(config[k]) or config[k] <= 0:
                    raise ValueError('Enter positive finite numbers in all measurement fields.')
            if config['eye'] not in ('left', 'right', 'both'):
                raise ValueError('Choose left, right or both.')
            config['pixels_per_mm'] = None if infinity else 400/config['ruler_mm']
            config.update(dict(angular_height_arcmin=None, letter_height_mm=None, letter_height_px=None) if infinity else target_geometry(config['distance_cm'], config['numerator'], config['denominator'], config['pixels_per_mm']))
            if not infinity and config['letter_height_px'] < 5:
                raise ValueError(f"Target is only {config['letter_height_px']:.2f} pixels high: insufficient for five strokes. Increase viewing distance or use a larger Snellen denominator.")
            if not infinity and (config['letter_height_px'] > 85 or config['letter_height_px']*9 > self.screen[0]-40):
                raise ValueError('Target does not fit the fixed target area. Adjust distance or acuity ratio.')
            self.args.data.mkdir(parents=True, exist_ok=True)
            if not infinity:
                write_json(self.args.data / 'calibration.json', dict(ruler_mm=config['ruler_mm'], screen_px=self.screen))
            if self.session is None:
                self.session = self.args.data / (datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6])
                (self.session / 'photos').mkdir(parents=True)
                (self.session / 'samples').mkdir()
                write_json(self.session / 'session.json', dict(created_utc=utc(), screen_px=self.screen,
                    models=str(self.args.models), camera_index=self.args.camera, screen_target=TARGET, target_source='See each block: screen or external distant target',
                    pose_method='InsightFace 68-point 3D landmark affine pose; pitch,yaw,roll',
                    camera_timing='First received frame after trigger; timestamp is software receipt, not exposure time.',
                    image_mirrored=False, acuity_note='Five-unit geometric letters, not a validated acuity test.'))
            config.update(block_id=uuid.uuid4().hex[:10], target=None if infinity else TARGET, screen_px=self.screen,
                          target_center_px=None if infinity else [self.screen[0]/2, 55], created_utc=utc(),
                          raster_canvas_height_px=None if infinity else math.ceil(config['letter_height_px']))
            write_json(self.session / f"block_{config['block_id']}.json", config)
            self.block = config
            self.centre = None
            self.canvas.delete('target')
            self.target_photo = None
            if not infinity:
                from PIL import ImageTk
                self.target_photo = ImageTk.PhotoImage(target_image(config['letter_height_px']))
                self.canvas.create_image(self.screen[0]/2, 55, image=self.target_photo, tags='target')
            for widget in self.inputs:
                widget.configure(state='disabled')
            self.start.configure(text='End block / change eye or distance')
            self.root.focus_set()
            target_instruction = 'Look at a distant object just above the webcam.' if infinity else 'Look at the letters.'
            self.status.set(target_instruction + ' When it feels straight ahead, press C to record centre. For one eye, cover the other without pressing on the glasses or hiding the face.')
            sizing = 'External target; no screen letters or acuity sizing. ' if infinity else f"{config['numerator']:g}/{config['denominator']:g} | letter height {config['letter_height_mm']:.3f} mm / {config['letter_height_px']:.2f} pixels. " + ('Low pixel resolution: letter strokes are under 2 pixels. ' if config['letter_height_px'] < 10 else '')
            self.details.set(f"{config['eye']} | {distance_label(config['distance_cm'])} | " + sizing + f'Results: {self.session}')
            self.update_buttons()
        except Exception as exc:
            messagebox.showerror('Cannot start block', str(exc))

    def key_capture(self, rating):
        if isinstance(self.root.focus_get(), (ttk.Entry, ttk.Combobox)):
            return
        self.capture(rating)

    def capture(self, rating):
        if rating == 'diplopia' and (self.block is None or self.block['eye'] != 'both'):
            return
        if self.busy or self.block is None or (rating == 'centre' and self.centre is not None) or (rating != 'centre' and self.centre is None):
            return
        trigger = time.monotonic()
        date = utc()
        self.busy = True
        self.update_buttons()
        self.status.set('Capturing and estimating head pose…')
        threading.Thread(target=self.process, args=(rating, trigger, date, dict(self.block), self.centre), daemon=True).start()

    def process(self, rating, trigger, date, config, centre):
        try:
            frame, frame_date, delay = self.camera.snapshot(trigger)
            sample_id = datetime.now().strftime('%H%M%S_%f') + '_' + uuid.uuid4().hex[:6]
            photo = f'photos/{sample_id}.png'
            if not self.camera.cv2.imwrite(str(self.session / photo), frame):
                raise OSError('Could not save the captured photo.')
            record = dict(config, sample_id=sample_id, rating=rating, trigger_utc=date, frame_utc=frame_date,
                          frame_delay_ms=round(delay, 3), photo=photo, landmarks_file=f'samples/{sample_id}.json',
                          valid=False, error='', centre_id=centre[0] if centre else '',
                          frame_size_px=[int(frame.shape[1]), int(frame.shape[0])])
            pose = None
            try:
                result = self.model.analyse(frame)
                pose = result.pop('pose')
                record.update(result)
                delta = angle_delta(pose, centre[1]) if centre else [0., 0., 0.]
                for axis, absolute, relative in zip(('pitch', 'yaw', 'roll'), pose, delta):
                    record[f'{axis}_deg'] = absolute
                    record[f'relative_{axis}_deg'] = relative
                record['valid'] = True
                if rating == 'centre':
                    record['centre_id'] = sample_id
            except Exception as exc:
                record['error'] = str(exc)
            write_json(self.session / 'samples' / f'{sample_id}.json', record)
            report_error = ''
            try:
                export_session(self.session)
            except Exception as exc:
                report_error = str(exc)
            self.events.put(('saved', (record, pose, report_error)))
        except Exception as exc:
            self.events.put(('error', str(exc)))

    def open_report(self):
        if self.busy:
            return
        if self.session is None:
            messagebox.showinfo('Results', 'No captures yet.')
            return
        try:
            export_session(self.session)
            import webbrowser
            webbrowser.open((self.session / 'report.html').as_uri())
        except Exception as exc:
            messagebox.showerror('Report', str(exc))

    def close(self):
        if self.busy:
            self.status.set('Wait for the current capture to finish, then exit.')
            return
        self.closed = True
        if self.camera:
            self.camera.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', type=Path, default=DEFAULT_MODELS)
    parser.add_argument('--data', type=Path, default=DEFAULT_DATA)
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--check-model', action='store_true', help='Load local models, then exit without opening camera')
    parser.add_argument('--export', type=Path, help='Rebuild CSV and HTML for an existing session')
    args = parser.parse_args()
    if args.export:
        print(f'Exported {len(export_session(args.export))} records.')
        return
    if args.check_model:
        PoseModel(args.models)
        print('Local detection and 68-point pose models loaded successfully.')
        return
    if os.name == 'nt':
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
    root = tk.Tk()
    App(root, args)
    root.mainloop()


if __name__ == '__main__':
    main()
