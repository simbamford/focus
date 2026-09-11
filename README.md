# Focus recorder

A Python/Tkinter app for documenting where progressive lenses feel sharp, using local webcam head-pose estimates. All processing is local. The app loads only `det_10g.onnx` and `1k3d68.onnx` from `C:\models\insightface\models\buffalo_l`; it does not compute identity embeddings.

## Start

Double-click `C:\repos\personal\focus\run.cmd`, or run:

```powershell
cd C:\repos\personal\focus
.\.venv\Scripts\python.exe focus_app.py
```

The dedicated environment is installed. To recreate it with Python 3.12+ (including Tk):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Use `--camera 1` to select another camera, `--models PATH` to change the model folder, or `--data PATH` for another recording folder. `--check-model` verifies the models without opening the camera. CPU inference is the default.

## Record

**Double vision:** In both-eyes mode, after declaring centre, press **D** or **Double vision** when the view is doubled and unusable regardless of focus. This is a third, independent rating (`diplopia`), plotted in **yellow** and summarised separately from focused/unfocused. The button and shortcut are disabled for left-eye and right-eye blocks.

**Infinity:** Enter `infinity`, `inf`, or `∞` in the distance field. Look at an external distant object just above the laptop webcam. The target letters disappear when you start the block; centre and rating capture work as usual. Screen calibration and Snellen sizing are not needed for this mode. Saved distance is the text `infinity`, and inapplicable letter-size/acuity fields are blank in CSV and null in JSON. Existing finite-distance recordings remain compatible.

1. Keep the laptop stationary, with the webcam above the middle of the screen. The app fills the primary display and places the fixed letters near its top centre. Use the display associated with that webcam, and keep display scaling unchanged during the session.
2. Measure the on-screen line between its end ticks using a physical ruler. Enter that length in millimetres. This calibrates the app's actual drawing pixels and accounts for screen size and Windows scaling. Recheck even when a previous calibration is prefilled.
3. Enter the eye-to-screen distance in centimetres, eye(s), the desired Snellen ratio, and useful notes such as glasses and lighting. The distance is your physical measurement; the camera does not measure it. Maintain it while recording.
4. Select **Start new eye / distance block**. The letters are sized once and remain fixed for the entire block.
5. For a single eye, cover the other eye without pressing on the glasses or obscuring much of the face. Look at the letters with your head in the position where they feel straight ahead. Press **C** or **Centred** to take the reference photo. A successful centre is required before ratings.
6. Move your head while continuing to look at the letters. Press **F** for focused or **U** for unfocused. Keyboard shortcuts avoid shifting your attention to a button. Wait for the saved status between captures. Explore around the boundary and repeat positions to assess consistency.
7. Select **End block / change eye or distance**, change the fields, and start again. Every block gets its own centre reference, including repeated blocks at the same distance. To replace a mistaken centre, start a new block.
8. **Open results report** opens the local HTML scatter plots and links to the tables/photos. **Finish / exit** or Escape closes the camera. Each capture is saved immediately; there is no final save step.

## Letter sizing and its limits

The default is **20/20**. The Snellen convention uses test distance divided by reference distance. A 20/20 letter is five arcminutes high. The ratio is editable if you want to compare larger or smaller targets in separate blocks.

Formula: `height_mm = 2 × distance_mm × tan(radians((5 × denominator / numerator) / 60) / 2)`.

The target is a fixed `H E F T H` line drawn on five-unit grids. Letter height and nominal stroke width are controlled; these are **geometric letters, not validated clinical optotypes**. Being able to read them does not establish a measured Snellen acuity. Rasterisation, contrast, memorisation, illumination and subjective judgement affect the task. The aim is consistent comparison across head positions.

At 60 cm, a 20/20 letter is about **0.873 mm** high. Many laptop displays cannot draw its strokes adequately. The app rejects targets below five pixels high and warns below ten pixels. It never silently enlarges the target. Increase distance, use a display with greater pixel density, or explicitly choose larger letters; that changes the test condition and is recorded. Ruler accuracy and entered distance limit sizing accuracy.

## Saved files

Each session creates a unique directory under `C:\data\focus` containing:

- `photos/*.png`: unmirrored original frames, including frames whose pose analysis failed.
- `samples/*.json`: one record per saved frame, with rating, timing, settings, face bounding box, detection score, 68 three-dimensional landmarks and angles when valid.
- `results.csv`: one row per capture, including rejected captures and centre references.
- `summary.csv`: counts and mean relative angles, separately for focused/unfocused within each block.
- `report.html`: per-block yaw/pitch scatter plots with links to original photos.
- `session.json` and `block_*.json`: method, display, target and block metadata.

You can give the optician the whole session folder. Keep its structure intact so report links work. To regenerate tables/report after closing an open CSV in Excel:

```powershell
.\.venv\Scripts\python.exe focus_app.py --export 'C:\data\focus\YOUR_SESSION_FOLDER'
```

Raw per-capture JSON files are authoritative. They are saved using an atomic rename before regenerating exports, so an Excel file lock does not lose a completed capture. Do not manually edit them while recording. Camera failures before a frame is available cannot produce a photo and are reported in the UI.

## Interpreting angles

InsightFace estimates pitch, yaw and roll from its 68-point 3D face landmarks. Each rating includes raw angles and wrapped differences from that block's declared centre. These are differences in Euler components, not a composed relative rotation. Zero means your declared straight-ahead reference. The app preserves the model's signs on unmirrored images; anatomical left/right and up/down signs are not independently validated. Use the original photos to interpret direction.

These are approximate **head angles**, not eye-gaze angles or the exact ray through a progressive lens. Head translation, glasses slipping, eye movements, occlusion, reflections and model error can affect interpretation. No face or multiple faces causes rejection; clipped/small faces and nonfinite estimates also cause rejection. A high detection score is not a pose-accuracy guarantee. Far-away faces may be too small for reliable inference. The reported distance is entered, not inferred. Sampling means are descriptive; they do not estimate a lens optical centre or prescribe a correction.

The camera is read continuously to reduce buffering. A trigger uses the first frame received afterward, stores software trigger/receipt timestamps and delay, and rejects delays over 500 ms. Receipt time is not the sensor exposure timestamp; a driver may still buffer frames. Hold the pose briefly as you press a key.

## Checks and references

Run ` .\.venv\Scripts\python.exe -m unittest -v test_focus.py` for geometry, persistence and capture-state checks. `--check-model` exercises the installed models.

- Visual-acuity conventions: https://eyewiki.aao.org/Visual_Acuity_Testing_in_Adults
- InsightFace landmark/pose implementation: https://github.com/deepinsight/insightface/blob/master/python-package/insightface/model_zoo/landmark.py
- Model package and licensing: https://github.com/deepinsight/insightface/tree/master/python-package

Use these observations as supporting information for the optician, not as a clinical visual-acuity test or a replacement for checking lens fitting and prescription.
