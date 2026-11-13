#!/usr/bin/python3
# Copyright 2026 uds-takserver authors
# SPDX-License-Identifier: GPL-3.0-only
"""Rebuild the selected Field mark with system fontTools and Inkscape."""
from pathlib import Path
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from html import escape
import base64
import re
import subprocess
R=Path(__file__).resolve().parents[2]; A=R/'assets'; P=A/'fieldmark'; P.mkdir(exist_ok=True)
COPY='<!-- Copyright 2026 uds-takserver authors; SPDX-License-Identifier: GPL-3.0-only -->\n'
D='M12 8H96L84 24H56V64H40V24H0Z M14 32H32V72H64V32H82V72L66 88H30L14 72Z'
def svg(body,w,h,title): return COPY+f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-labelledby="title"><title id="title">{escape(title)}</title>{body}</svg>\n'
def mark(ink,x=0,y=0,s=1): return f'<path fill="{ink}" transform="translate({x} {y}) scale({s})" d="{D}"/>'
def text(t,x,y,size,ink,bold=True):
 f=TTFont('/usr/share/fonts/truetype/liberation/LiberationSans-'+('Bold' if bold else 'Regular')+'.ttf'); gs=f.getGlyphSet(); cmap=f.getBestCmap(); pen=SVGPathPen(gs); pos=0; paths=[]
 for c in t:
  n=cmap[ord(c)]; p=SVGPathPen(gs); gs[n].draw(p); paths.append(f'<path transform="translate({pos} 0)" d="{p.getCommands()}"/>'); pos+=f['hmtx'][n][0]
 return f'<g fill="{ink}" transform="translate({x} {y}) scale({size/f["head"].unitsPerEm} {-size/f["head"].unitsPerEm})">'+''.join(paths)+'</g>'
def lock(ink,x=0,y=0,s=1): return f'<g transform="translate({x} {y}) scale({s})">'+mark(ink,0,2,1.1)+text('TAK Server',136,62,64,ink)+text('on UDS',139,104,39,ink,False)+'</g>'
for theme,ink in [('light','#000000'),('dark','#FFFFFF'),('mono','currentColor')]:
 (A/f'tak-mark-{theme}.svg').write_text(svg(mark(ink),96,96,'TAK Server on UDS — Field mark'))
 if theme!='mono': (A/f'tak-on-uds-{theme}.svg').write_text(svg(lock(ink),480,120,'TAK Server on UDS — Field mark'))
adaptive=svg('<style>.ink{fill:#000}@media(prefers-color-scheme:dark){.ink{fill:#fff}}</style>'+f'<path class="ink" d="{D}"/>',96,96,'TAK Server on UDS — Field mark')
for file in [A/'icon.svg',A/'tak-mark.svg',R/'docs-site/public/favicon.svg']:file.write_text(adaptive)
p=R/'zarf.yaml'
p.write_text(re.sub(r'(?m)^(    dev\.uds\.icon: ).*$', lambda m: m[1]+'data:image/svg+xml;base64,'+base64.b64encode((A/'icon.svg').read_bytes()).decode(),p.read_text()))
social=svg('<rect width="1200" height="630" fill="#000"/>'+lock('#fff',120,155,2)+text('All-in-one solution for packaging, deploying,',124,480,30,'#fff',False)+text('and operating TAK Server',124,520,30,'#fff',False),1200,630,'TAK Server on UDS')
(A/'tak-social.svg').write_text(social)
# A compact review proof includes the actual 16/24/32 px raster sizes, not enlarged marks.
proof='<rect width="1200" height="740" fill="#fff"/>'+text('FIELD MARK / SELECTED B',50,55,24,'#000')+mark('#000',75,105,2.6)+lock('#000',410,165,1.45)+'<rect x="40" y="390" width="1120" height="210" fill="#000"/>'+lock('#fff',90,435,1.1)
for i,size in enumerate((16,24,32)):
 proof+=mark('#000',100+i*105,655,size/96)+text(str(size)+' px',100+i*105,715,15,'#000',False)+mark('#fff',850+i*90,485,size/96)
(P/'preview.svg').write_text(svg(proof,1200,740,'Selected Field mark: light, dark, and actual favicon sizes'))
for src,dst in [(A/'tak-social.svg',R/'docs-site/public/og.png'),(P/'preview.svg',P/'preview.png')]:subprocess.run(['inkscape',str(src),'--export-type=png','--export-filename='+str(dst)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
for theme in ('light','dark'):
 for size in (16,24,32):subprocess.run(['inkscape',str(A/f'tak-mark-{theme}.svg'),'--export-type=png','--export-width='+str(size),'--export-height='+str(size),'--export-filename='+str(P/f'favicon-{theme}-{size}.png')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
for name in ('docs-site/astro.config.mjs','demo/README.md','demo/ui-reel/README.md'):
 p=R/name;p.write_text(p.read_text().replace('Connected stack','Field mark').replace('connected stack','field mark'))
