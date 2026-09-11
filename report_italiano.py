r"""Generate index.html without changing the original report or measurements.

Usage: .venv\Scripts\python.exe report_italiano.py [session_folder]
"""
import argparse
from collections import defaultdict
import html
import json
import math
from pathlib import Path
from urllib.parse import quote

DEFAULT_SESSION = Path(r'C:\data\focus\20260911_115646_862c2a')
DISTANCES = ('infinity', 100.0, 60.0, 35.0)
EYES = ('left', 'both', 'right')
EYE_NAMES = {'left': 'Occhio sinistro', 'both': 'Entrambi gli occhi', 'right': 'Occhio destro'}
RATINGS = {'focused': ('A fuoco', '#147d64'), 'unfocused': ('Sfocato', '#cf443d'),
           'diplopia': ('Diplopia', '#f4cf32')}


def usable(row):
    return (row.get('valid') is True and not row.get('error')
            and row.get('rating') in RATINGS
            and all(isinstance(row.get(k), (int, float)) and math.isfinite(row[k])
                    for k in ('relative_yaw_deg', 'relative_pitch_deg')))


def select_blocks(folder):
    blocks = defaultdict(list)
    for source in sorted((folder / 'samples').glob('*.json')):
        row = json.loads(source.read_text(encoding='utf-8'))
        blocks[row['block_id']].append(row)
    selected = defaultdict(list)
    for rows in blocks.values():
        points = [row for row in rows if usable(row)]
        if len(points) < 2:
            continue
        distance, eye = points[0]['distance_cm'], points[0]['eye']
        if distance in DISTANCES and eye in EYES:
            selected[(distance, eye)].append(points)
    return selected


def graph(points, extent):
    # Same limits and geometry for every plot. Relative pitch is deliberately
    # positive DOWN, the vertical reflection of the original report.
    elements = ['<svg viewBox="0 0 400 350" role="img" aria-label="Angoli relativi della testa, asse verticale invertito">',
                '<rect x="48" y="25" width="304" height="264" fill="#f8fafc"/>']
    for tick in (-extent, -extent/2, 0, extent/2, extent):
        x, y = 200 + tick/extent*152, 157 + tick/extent*132
        color = '#8897a7' if tick == 0 else '#dee5eb'
        elements.append(f'<path d="M{x} 25V289 M48 {y}H352" stroke="{color}"/>')
        elements.append(f'<text x="{x}" y="308" text-anchor="middle">{tick:g}°</text>')
        elements.append(f'<text x="42" y="{y+4}" text-anchor="end">{tick:g}°</text>')
    for row in points:
        x = 200 + row['relative_yaw_deg']/extent*152
        y = 157 + row['relative_pitch_deg']/extent*132
        label, color = RATINGS[row['rating']]
        caption = html.escape(f"{label}; orizzontale {row['relative_yaw_deg']:+.2f}°; verticale {row['relative_pitch_deg']:+.2f}°")
        elements.append(f'<circle cx="{x:.3f}" cy="{y:.3f}" r="4.5" fill="{color}" stroke="#394553" stroke-width="0.5"><title>{caption}</title></circle>')
    elements.append('<text x="200" y="336" text-anchor="middle">Rotazione orizzontale relativa</text></svg>')
    return ''.join(elements)


def photo_table(points, folder):
    rows = []
    for row in points:
        # Only links to existing photos inside this session; no rejected frames.
        relative = Path(row.get('photo', ''))
        photo = (folder / relative).resolve()
        if not photo.is_relative_to(folder.resolve()) or not photo.is_file():
            continue
        url = quote(photo.relative_to(folder.resolve()).as_posix(), safe='/')
        label = RATINGS[row['rating']][0]
        rows.append(f'<tr><td>{label}</td><td>{row["relative_yaw_deg"]:+.2f}°</td><td>{row["relative_pitch_deg"]:+.2f}°</td><td><a href="{url}">Apri foto</a></td></tr>')
    return ('<details><summary>Valutazioni e fotografie</summary><table><thead><tr>'
            '<th>Valutazione</th><th>Orizz.</th><th>Vert.</th><th>Fotografia</th>'
            '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></details>')


def generate(folder):
    folder = Path(folder).resolve()
    if not (folder / 'samples').is_dir():
        raise FileNotFoundError(f'Cartella delle acquisizioni non trovata: {folder / "samples"}')
    selected = select_blocks(folder)
    all_points = [p for groups in selected.values() for group in groups for p in group]
    extent = max(10, math.ceil(max((abs(p[k])*1.1 for p in all_points
                  for k in ('relative_yaw_deg', 'relative_pitch_deg')), default=0)/5)*5)
    sections = []
    for distance in DISTANCES:
        distance_name = 'Infinito' if distance == 'infinity' else f'{distance:g} cm'
        cards = []
        for eye in EYES:
            groups = selected.get((distance, eye), [])
            content = []
            for index, points in enumerate(groups, 1):
                # Keep repeated qualifying blocks separate because their centres differ.
                if len(groups) > 1:
                    content.append(f'<h4>Serie {index}</h4>')
                content.append(f'<p class="count">{len(points)} valutazioni</p>')
                content.append(graph(points, extent))
                content.append(photo_table(points, folder))
            if not content:
                content.append('<p>Nessuna serie con almeno due valutazioni utilizzabili.</p>')
            cards.append(f'<article><h3>{EYE_NAMES[eye]}</h3>{"".join(content)}</article>')
        sections.append(f'<section><h2>{distance_name}</h2><div class="graphs">{"".join(cards)}</div></section>')
    document = '''<!doctype html>
<html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Messa a fuoco e diplopia — confronto per distanza</title>
<style>
*{box-sizing:border-box}body{font:15px system-ui,sans-serif;color:#1b2937;background:#f1f4f7;margin:0;padding:28px}
main{max-width:1500px;margin:auto}h1{font-size:28px;margin-bottom:12px}p{line-height:1.55}header{max-width:1100px}
section{margin:30px 0}h2{font-size:23px;margin:0 0 14px}.graphs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}
article{background:white;border:1px solid #dbe2e9;border-radius:12px;padding:14px;min-width:0}h3{font-size:18px;text-align:center;margin:5px 0}
.count{text-align:center;color:#536374;margin:6px 0}svg{display:block;width:100%;height:auto}svg text{font:11px system-ui;fill:#445465}
.legend{display:flex;gap:22px;flex-wrap:wrap}.dot{display:inline-block;width:12px;height:12px;border:1px solid #536374;border-radius:50%;margin-right:7px}
summary{cursor:pointer;padding:10px 0}table{width:100%;border-collapse:collapse;font-size:12px}th,td{padding:7px 3px;border-bottom:1px solid #e5e9ee;text-align:left}a{color:#145ea5}
@media(max-width:800px){body{padding:12px}.graphs{min-width:840px;gap:10px}section{overflow-x:auto}}
@media print{body{padding:0;background:white;font-size:11px}section{break-inside:avoid;margin:18px 0}details{display:none}article{padding:7px}.graphs{gap:8px}}
</style></head><body><main><header><h1>Messa a fuoco e diplopia</h1>
<p>Confronto per distanza: occhio sinistro a sinistra, entrambi gli occhi al centro e occhio destro a destra.</p>
<p class="legend"><span><i class="dot" style="background:#147d64"></i>A fuoco</span><span><i class="dot" style="background:#cf443d"></i>Sfocato</span><span><i class="dot" style="background:#f4cf32"></i>Diplopia — visione inutilizzabile</span></p>
<p>I grafici sono ribaltati verticalmente rispetto al report originale per rappresentare la lettura soggettiva richiesta: i valori verticali positivi sono in basso. Lo zero corrisponde alla posizione dichiarata come centrale per ciascuna serie. Tutti i grafici usano la stessa scala; gli angoli sono stime della posizione della testa, non misure dello sguardo.</p>
<p>Sono incluse soltanto valutazioni con stima valida, appartenenti a serie con almeno due punti; le acquisizioni di centratura non contano come valutazioni. Le fotografie delle acquisizioni scartate sono escluse. Per infinito si osserva un bersaglio distante sopra la webcam, senza lettere sullo schermo.</p>
</header>'''
    output = folder / 'index.html'
    output.write_text(document + ''.join(sections) + '</main></body></html>', encoding='utf-8')
    return output, len(all_points), sum(len(groups) for groups in selected.values())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', nargs='?', type=Path, default=DEFAULT_SESSION)
    args = parser.parse_args()
    output, points, blocks = generate(args.session)
    print(f'Report salvato: {output}\n{blocks} serie, {points} valutazioni.')
