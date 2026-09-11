"""Pure measurement and persistence helpers; no camera or GUI required."""
import csv
import html
import json
import math
from pathlib import Path


def parse_distance(value):
    if str(value).strip().lower() in ('infinity', 'inf', '∞'):
        return 'infinity'
    distance = float(value)
    if not math.isfinite(distance) or distance <= 0:
        raise ValueError('Enter a positive distance in cm, or infinity.')
    return distance


def distance_label(value):
    return 'infinity (external target)' if value == 'infinity' else f'{value:g} cm'


def target_geometry(distance_cm, numerator, denominator, pixels_per_mm):
    values = [distance_cm, numerator, denominator, pixels_per_mm]
    if any(not math.isfinite(float(v)) or float(v) <= 0 for v in values):
        raise ValueError('Distance, acuity values and calibration must be positive finite numbers.')
    arcmin = 5 * denominator / numerator
    height_mm = 2 * distance_cm * 10 * math.tan(math.radians(arcmin / 60) / 2)
    return dict(angular_height_arcmin=arcmin, letter_height_mm=height_mm,
                letter_height_px=height_mm * pixels_per_mm)


def angle_delta(pose, centre):
    return [((float(a) - float(b) + 180) % 360) - 180 for a, b in zip(pose, centre)]


FIELDS = ['sample_id', 'block_id', 'rating', 'valid', 'error', 'eye', 'distance_cm',
          'trigger_utc', 'frame_utc', 'frame_delay_ms', 'centre_id',
          'pitch_deg', 'yaw_deg', 'roll_deg', 'relative_pitch_deg',
          'relative_yaw_deg', 'relative_roll_deg', 'detection_score',
          'face_width_px', 'face_height_px', 'numerator', 'denominator',
          'pixels_per_mm', 'letter_height_mm', 'letter_height_px',
          'angular_height_arcmin', 'photo', 'landmarks_file', 'notes']


def write_json(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def export_session(folder):
    """Rebuild tables/report from durable per-capture JSON records."""
    folder = Path(folder)
    records = [json.loads(p.read_text(encoding='utf-8')) for p in sorted((folder / 'samples').glob('*.json'))]
    temp = folder / 'results.csv.tmp'
    with temp.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(records)
    temp.replace(folder / 'results.csv')
    sections = []
    summaries = []
    for block in dict.fromkeys(r['block_id'] for r in records):
        rows = [r for r in records if r['block_id'] == block]
        first = rows[0]
        valid = [r for r in rows if r['valid'] and r['rating'] != 'centre']
        points = []
        extent = max([10] + [abs(r[k]) * 1.15 for r in valid for k in ('relative_yaw_deg', 'relative_pitch_deg')])
        for r in valid:
            x = 300 + r['relative_yaw_deg'] / extent * 240
            y = 220 - r['relative_pitch_deg'] / extent * 170
            color = {'focused': '#147d64', 'unfocused': '#cf443d', 'diplopia': '#f4cf32'}.get(r['rating'], '#808080')
            label = html.escape(f"{r['sample_id']}: {r['rating']}, yaw {r['relative_yaw_deg']:.2f}, pitch {r['relative_pitch_deg']:.2f}")
            points.append(f'<circle cx="{x}" cy="{y}" r="6" fill="{color}"><title>{label}</title></circle>')
        title = html.escape(f"{first['eye']} eye(s), {distance_label(first['distance_cm'])} — block {block}")
        for rating in (('focused', 'unfocused', 'diplopia') if first['eye'] == 'both' else ('focused', 'unfocused')):
            group = [r for r in valid if r['rating'] == rating]
            summaries.append(dict(block_id=block, eye=first['eye'], distance_cm=first['distance_cm'],
                                  rating=rating, count=len(group),
                                  mean_relative_yaw_deg=sum(r['relative_yaw_deg'] for r in group)/len(group) if group else '',
                                  mean_relative_pitch_deg=sum(r['relative_pitch_deg'] for r in group)/len(group) if group else ''))
        links = ''.join(f'<tr><td>{html.escape(r["sample_id"])}</td><td>{html.escape(r["rating"])}</td><td>{r["valid"]}</td><td>{html.escape(r.get("error", ""))}</td><td><a href="{html.escape(r["photo"], quote=True)}">Photo</a></td></tr>' for r in rows)
        sections.append(f'''<section><h2>{title}</h2><p>Green: focused; red: unfocused; yellow: diplopia (double vision, unusable regardless of focus). {len(valid)} valid ratings; {sum(not r['valid'] for r in rows)} rejected captures.</p>
        <svg viewBox="0 0 600 450" width="600" role="img" aria-label="Relative head yaw and pitch scatter plot">
        <rect width="600" height="450" fill="#f5f7fa"/><path d="M60 220H540 M300 50V390" stroke="#929aa6"/>
        <text x="300" y="430" text-anchor="middle">Relative yaw (degrees), ±{extent:.1f}</text>
        <text x="10" y="24">Relative pitch (degrees), ±{extent:.1f}; positive upward on plot</text>
        <text x="305" y="237">0 (declared centre)</text>{''.join(points)}</svg>
        <details><summary>Captures and original photos</summary><table><tr><th>ID</th><th>Rating</th><th>Valid</th><th>Error</th><th>Image</th></tr>{links}</table></details></section>''')
    if summaries:
        with (folder / 'summary.csv').open('w', newline='', encoding='utf-8-sig') as f:
            w = csv.DictWriter(f, fieldnames=list(summaries[0]))
            w.writeheader()
            w.writerows(summaries)
    report = '''<!doctype html><meta charset="utf-8"><title>Focus measurements</title>
    <style>body{font:16px system-ui;max-width:960px;margin:40px auto;color:#182330}section{border-top:1px solid #ddd;padding:20px 0}svg{max-width:100%;height:auto}td,th{padding:8px;text-align:left}table{border-collapse:collapse}p{line-height:1.5}</style>
    <h1>Progressive lens focus observations</h1>
    <p>Diplopia is a separate self-reported category, excluded from focused/unfocused averages. Infinity means viewing an external distant target above the webcam, with no on-screen letters or acuity sizing.</p>
    <p>Self-reported sharpness versus estimated head pose. These measurements do not establish visual acuity, gaze direction, lens power, or a prescription. Distances are entered by the observer, not measured by the camera. Head translation and eye rotation also affect which part of the lens is used.</p>
    <p>Angles follow InsightFace's pitch/yaw/roll convention on unmirrored camera images; relative values are wrapped Euler-angle differences from the centre capture for that block, not a full 3D relative rotation. Positive signs are model coordinates, not verified anatomical left/right. Photos permit interpretation. Averages describe sampled points and are not an estimated optical centre.</p>
    <p><a href="results.csv">All results CSV</a> · <a href="summary.csv">Summary CSV</a> · <a href="session.json">Session metadata</a></p>'''
    (folder / 'report.html').write_text(report + ''.join(sections), encoding='utf-8')
    return records
