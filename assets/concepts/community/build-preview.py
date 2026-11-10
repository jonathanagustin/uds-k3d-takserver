#!/usr/bin/env python3
# Copyright 2026 uds-takserver authors; SPDX-License-Identifier: GPL-3.0-only
"""Build review variants from original, hand-authored SVG geometry."""
from pathlib import Path
from html import escape

ROOT = Path(__file__).resolve().parent
COPYRIGHT = '<!-- Copyright 2026 uds-takserver authors; SPDX-License-Identifier: GPL-3.0-only -->\n'
# All coordinates are authored on a 64-unit grid. No traced artwork or fonts.
ART = {
    'stack-relay': '''  <g fill="{ink}">
    <rect x="6" y="13" width="31" height="10" rx="3"/>
    <rect x="6" y="29" width="31" height="10" rx="3"/>
    <rect x="6" y="45" width="31" height="10" rx="3"/>
  </g>
  <path d="M34 18H46V50H34M34 34H46" fill="none" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>
  <path fill="{accent}" d="m61 4-7 25-9-9-10-7Z"/>''',
    'trail-relay': '''  <path d="M14 16V40Q14 51 25 51H33Q44 51 44 40V24" fill="none" stroke="{ink}" stroke-width="10" stroke-linecap="round"/>
  <circle cx="14" cy="15" r="8" fill="{ink}"/>
  <path fill="{accent}" d="m59 5-8 28-8-10-10-8Z"/>'''
}
LABELS = {'stack-relay': 'Relay stack', 'trail-relay': 'Unified route'}
THEMES = {
    'light': ('#0F172A','#22D3EE'),
    'dark': ('#F8FAFC','#22D3EE'),
    'mono': ('currentColor','currentColor'),
    'indigo': ('#0F172A','#4F46E5'),
}
for name, art in ART.items():
    for theme,(ink,accent) in THEMES.items():
        svg = COPYRIGHT + f'''<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64" role="img" aria-labelledby="title desc">
  <title id="title">TAK on UDS — {LABELS[name]}</title>
  <desc id="desc">{'Three platform layers share a connected relay that ends in a navigation heading.' if name == 'stack-relay' else 'A teammate node connects through a U-shaped route to a forward navigation arrow.'}</desc>
{art.format(ink=ink,accent=accent)}
</svg>
'''
        (ROOT / f'{name}-{theme}.svg').write_text(svg)

cards = []
for i,(name,label) in enumerate(LABELS.items(),1):
    note = 'Three platform layers connect to one navigation heading: the Unified Defense Stack delivering shared situational awareness to field teams.' if name == 'stack-relay' else 'A teammate, a route, a heading. One continuous U connects a field position to the shared platform.'
    sizes = ''.join(f'<div><img src="{name}-light.svg" width="{s}" height="{s}"><span>{s}px</span></div>' for s in (16,24,32,48))
    dark_sizes = ''.join(f'<div><img src="{name}-dark.svg" width="{s}" height="{s}"><span>{s}px</span></div>' for s in (16,24,32,48))
    indigo_sizes = ''.join(f'<div><img src="{name}-indigo.svg" width="{s}" height="{s}"><span>{s}px</span></div>' for s in (16,24,32))
    cards.append(f'''<article><div class="meta"><span>0{i} / CONCEPT</span><span>64 UNIT MASTER</span></div><div class="hero"><img src="{name}-light.svg" width="176" height="176"><div><h2>{label}</h2><p>{note}</p></div></div><div class="pair"><section><h3>DAYLIGHT</h3><div class="sizes">{sizes}</div></section><section class="night"><h3>LOW LIGHT</h3><div class="sizes">{dark_sizes}</div></section></div><div class="mono"><span>ONE INK</span><svg viewBox="0 0 64 64" width="48" height="48">{ART[name].format(ink='currentColor',accent='currentColor')}</svg><div class="reverse"><svg viewBox="0 0 64 64" width="48" height="48">{ART[name].format(ink='currentColor',accent='currentColor')}</svg></div><span class="mono-note">No border · no gradients · no type dependency</span></div><section><h3>INDIGO ON WHITE / HIGHER ACCENT CONTRAST</h3><div class="sizes">{indigo_sizes}</div></section></article>''')
html = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TAK on UDS — community logo concepts</title><style>
*{box-sizing:border-box}body{margin:0;background:#F1F5F9;color:#0F172A;font-family:Arial,Helvetica,sans-serif}main{max-width:1400px;padding:42px 48px 28px;margin:auto}.eyebrow{font-size:11px;letter-spacing:2px;font-weight:700}header{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:30px}h1{font-size:43px;letter-spacing:-1.7px;line-height:1.05;margin:12px 0}header p{font-size:14px;line-height:1.5;margin:0;max-width:330px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:24px}article{background:#FFFFFF;border:1px solid #CBD5E1;border-radius:20px;overflow:hidden}.meta{padding:20px 24px;display:flex;justify-content:space-between;font-size:10px;font-weight:bold;letter-spacing:1.4px;border-bottom:1px solid #E2E8F0;color:#64748B}.hero{min-height:273px;padding:34px 30px;display:flex;gap:26px;align-items:center}.hero>img{flex:none}h2{font-size:29px;letter-spacing:-.8px;margin:0 0 12px}p{font-size:14px;line-height:1.6;margin:0}.pair{display:grid;grid-template-columns:1fr 1fr}section{padding:22px 24px;background:#F8FAFC}h3{font-size:10px;letter-spacing:1.5px;margin:0 0 25px;color:#64748B}.night{background:#0B1220;color:#F8FAFC}.night h3{color:#CBD5E1}.sizes{height:80px;display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.sizes>div{height:80px;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:12px}.sizes span{font-size:10px}.mono{padding:18px 24px;display:flex;align-items:center;gap:14px;font-size:10px;letter-spacing:1.3px}.reverse{background:#0F172A;color:#fff;border-radius:8px;padding:5px;height:58px}.mono-note{margin-left:auto;max-width:165px;line-height:1.6;letter-spacing:0;color:#64748B}.recommend{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-top:24px}.recommend>div{padding:0 24px}.recommend strong{display:block;font-size:13px;margin-bottom:7px}.recommend p{font-size:12px;color:#475569;line-height:1.6}footer{margin-top:28px;padding-top:18px;border-top:1px solid #CBD5E1;display:flex;justify-content:space-between;font-size:10px;letter-spacing:.5px;color:#64748B}.current{display:flex;align-items:center;gap:8px}@media(max-width:950px){main{padding:24px}.grid,.recommend{grid-template-columns:1fr}.hero{justify-content:center}header{display:block}header p{max-width:none}}@media(max-width:500px){.hero{padding:24px 18px;gap:16px}.hero>img{width:108px;height:108px}h2{font-size:24px}.pair{grid-template-columns:1fr}footer{gap:16px}.mono-note{display:none}}
</style><main><header><div><div class="eyebrow">TAK ON UDS / COMMUNITY MARK EXPLORATION</div><h1>Built for people in the field.</h1></div><p>Search & rescue. Civilian response. Connected field teams. Open platform builders.</p></header><div class="grid">'''+''.join(cards)+'''</div><div class="recommend"><div><strong>01 / Stronger platform meaning</strong><p>Recommended for the integrated platform identity. Three substantial layers connect to a navigation heading. At 16px each layer remains 2.5px thick, separated by 1.5px gaps.</p></div><div><strong>02 / Simpler field shorthand</strong><p>The simpler favicon alternative. A teammate node links through a U-shaped route to a heading. It emphasizes shared field awareness; the accompanying wordmark supplies the platform context.</p></div></div><footer><span>REVIEW CONCEPTS · ORIGINAL SVG GEOMETRY · NO DEPLOYED BRANDING CHANGES</span><div class="current"><img src="../../tak-mark.svg" width="24" height="24"><span>Current beacon for comparison</span></div></footer></main></html>'''
(ROOT / 'index.html').write_text(html)

# Standalone proof sheet: all marks remain vector paths, even at favicon size.
def text(x,y,content,size=14,color='#0F172A',weight=400):
    return f'<text x="{x}" y="{y}" fill="{color}" font-family="DejaVu Sans,sans-serif" font-size="{size}" font-weight="{weight}">{escape(content)}</text>'
def icon(name,x,y,size,theme='light'):
    ink,accent = THEMES[theme] if theme != 'mono' else ('#0F172A','#0F172A')
    return f'<g transform="translate({x} {y}) scale({size/64})">{ART[name].format(ink=ink,accent=accent)}</g>'
parts = ['<rect width="1440" height="996" fill="#F1F5F9"/>',text(48,55,'TAK ON UDS / COMMUNITY MARK EXPLORATION',12,weight=700),text(48,109,'Built for people in the field.',42,weight=700),text(1040,72,'Search & rescue. Civilian response.',14),text(1040,96,'Field teams. Open platform builders.',14)]
for i,(name,label) in enumerate(LABELS.items()):
    x = 48 + i*684
    parts += [f'<rect x="{x}" y="150" width="660" height="664" rx="20" fill="#FFFFFF" stroke="#CBD5E1"/>',text(x+24,184,f'0{i+1} / CONCEPT',11,weight=700),text(x+480,184,'64 UNIT MASTER',11,weight=700),icon(name,x+36,231,200),text(x+270,288,label,30,weight=700)]
    lines = ['A platform connected to the field.', 'Three layers share one relay.', 'The heading brings TAK into', 'the Unified Defense Stack.'] if i == 0 else ['A teammate, a route, a heading.', 'One continuous U-shaped link', 'connects shared awareness', 'to the platform beneath it.']
    parts += [text(x+270,326+j*25,s,15) for j,s in enumerate(lines)]
    for j,theme in enumerate(('light','dark')):
        sx=x+330*j
        bg='#F8FAFC' if j==0 else '#0B1220'; fg='#64748B' if j==0 else '#CBD5E1'
        parts += [f'<rect x="{sx}" y="479" width="330" height="160" fill="{bg}"/>',text(sx+24,510,'DAYLIGHT' if j==0 else 'LOW LIGHT',11,fg,700)]
        for k,size in enumerate((16,24,32,48)):
            cx=sx+40+k*77
            parts += [icon(name,cx-size/2,593-size,size,theme),text(cx-12,616,f'{size}px',10,fg)]
    parts += [text(x+24,692,'ONE INK',11,weight=700),icon(name,x+112,661,48,'mono'),f'<rect x="{x+180}" y="656" width="58" height="58" rx="8" fill="#0F172A"/>',f'<g transform="translate({x+185} 661) scale(.75)">{ART[name].format(ink="#FFFFFF",accent="#FFFFFF")}</g>',text(x+269,683,'Flat color. No frame. No type dependency.',12,'#64748B'),text(x+269,706,'Original geometry; no embedded raster artwork.',12,'#64748B')]
    parts += [text(x+24,768,'INDIGO ON WHITE',11,weight=700)]
    for k,size in enumerate((16,24,32)):
        parts += [icon(name,x+194+k*62,775-size,size,'indigo'),text(x+194+k*62,796,f'{size}px',10,'#64748B')]
    parts += [text(x+406,762,'Higher accent contrast',12,'#64748B'),text(x+406,784,'for light favicon surfaces.',12,'#64748B')]
    desc=['01 / INTEGRATED PLATFORM IDENTITY','Three layers, one relay, one field heading.', 'At 16px: 2.5px layers with 1.5px gaps keep the stack distinct.'] if i==0 else ['02 / SIMPLER FAVICON ALTERNATIVE','A shared route connects a teammate to a heading.', 'Its open U shape and two endpoints stay clear at 16px.']
    parts += [text(x+24,855,desc[0],12,weight=700),text(x+24,881,desc[1],13,'#475569'),text(x+24,904,desc[2],13,'#475569')]
parts += ['<path d="M48 934H1392" stroke="#CBD5E1"/>',text(48,965,'REVIEW CONCEPTS · ORIGINAL SVG GEOMETRY · NO DEPLOYED BRANDING CHANGES',11,'#64748B')]
(ROOT/'review-sheet.svg').write_text(COPYRIGHT+'<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="996" viewBox="0 0 1440 996" role="img"><title>TAK on UDS community logo concepts, with actual favicon sizes</title>'+''.join(parts)+'</svg>\n')

# Preserve the project's existing outlined typography while comparing new marks.
import xml.etree.ElementTree as ET
ET.register_namespace('', 'http://www.w3.org/2000/svg')
original = ET.parse(ROOT.parents[1] / 'tak-on-uds-dark.svg').getroot()
lettering = list(original)[3:]
# The old document has title, desc, mark group, then the outlined wordmark.
lettering_xml = ''.join(ET.tostring(e,encoding='unicode') for e in lettering)
lockup_parts = ['<rect width="1440" height="640" fill="#F1F5F9"/>',text(48,54,'TAK ON UDS / EXISTING TYPE + NEW COMMUNITY MARKS',13,weight=700)]
for i,name in enumerate(LABELS):
    for j,theme in enumerate(('light','dark')):
        ink,accent = THEMES[theme]
        label_color = '#0F172A' if theme=='light' else '#F8FAFC'
        outlines = lettering_xml.replace('#f9fafb',label_color)
        content = f'<g transform="translate(0 8) scale(2.75)">{ART[name].format(ink=ink,accent=accent)}</g>'+outlines
        (ROOT/f'{name}-wordmark-{theme}.svg').write_text(COPYRIGHT+f'<svg xmlns="http://www.w3.org/2000/svg" width="770" height="192" viewBox="0 0 770 192" role="img"><title>TAK on UDS — {LABELS[name]} concept</title>{content}</svg>\n')
        x=48+j*684;y=88+i*264
        lockup_parts += [f'<rect x="{x}" y="{y}" width="660" height="236" rx="18" fill="{"#FFFFFF" if theme=="light" else "#0B1220"}"/>',text(x+24,y+32,LABELS[name].upper()+' / '+theme.upper(),11,label_color,700),f'<g transform="translate({x+24} {y+62}) scale(.78)">{content}</g>']
(ROOT/'wordmark-sheet.svg').write_text(COPYRIGHT+'<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="640" viewBox="0 0 1440 640"><title>TAK on UDS concept wordmarks</title>'+''.join(lockup_parts)+'</svg>\n')
