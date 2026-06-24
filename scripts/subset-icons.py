#!/usr/bin/env python
"""Субсет Material Symbols Rounded рівно до іконок, що використовує застосунок.

Регенерує:
  * app/static/fonts/material-symbols-rounded.woff2 -- served субсет (~6 КБ
    замість 407 КБ повного шрифту);
  * блок ICON_CODEPOINTS у app/icons.py (мапа назва -> кодпойнт для рендеру).

КОЛИ ЗАПУСКАТИ: після додавання/видалення icon('<name>') у шаблонах або зміни
динамічних наборів (EXTRA_ICONS). CI-тест tests/test_icons.py перевіряє, що
коміт лишається синхронним (усі вжиті назви присутні у мапі та шрифті).

Джерела (повний шрифт + codepoints) кешуються у scripts/.cache/ (gitignored);
за відсутності -- завантажуються з Google. Мережа потрібна лише для регенерації,
не для роботи застосунку чи тестів.

Залежність: fonttools (вже у requirements.lock).
"""
import os
import re
import glob
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'scripts', '.cache')
FULL_FONT = os.path.join(CACHE, 'material-symbols-rounded-full.woff2')
CODEPOINTS = os.path.join(CACHE, 'material-symbols.codepoints')
SERVED = os.path.join(ROOT, 'app', 'static', 'fonts', 'material-symbols-rounded.woff2')
ICONS_PY = os.path.join(ROOT, 'app', 'icons.py')
TEMPLATES = os.path.join(ROOT, 'app', 'templates')

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36'
CSS2_URL = ('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded'
            ':opsz,wght,FILL,GRAD@24,300,0,0')
CODEPOINTS_URL = ('https://raw.githubusercontent.com/google/material-design-icons'
                  '/master/variablefont/'
                  'MaterialSymbolsRounded%5BFILL%2CGRAD%2Copsz%2Cwght%5D.codepoints')

# Іконки, що задаються ДИНАМІЧНО (через змінну) -- скан icon('literal') їх не
# бачить. Тримати синхронно з даними у шаблонах.
EXTRA_ICONS = {
    # admin/instances.html -> set pills = [(key, label, icon_name), ...]
    'apps', 'event_upcoming', 'looks_3', 'history', 'calendar_month',
    'how_to_reg', 'person_off', 'event_available', 'event_busy', 'priority_high',
}

ICON_CALL_RE = re.compile(r"icon\('([a-z0-9_]+)'")


def _fetch(url, dest, binary=True):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    mode = 'wb' if binary else 'w'
    with open(dest, mode) as f:
        f.write(data if binary else data.decode('utf-8'))


def ensure_sources():
    os.makedirs(CACHE, exist_ok=True)
    if not os.path.exists(CODEPOINTS):
        print('  downloading codepoints...')
        _fetch(CODEPOINTS_URL, CODEPOINTS, binary=False)
    if not os.path.exists(FULL_FONT):
        print('  resolving woff2 url...')
        req = urllib.request.Request(CSS2_URL, headers={'User-Agent': UA})
        css = urllib.request.urlopen(req, timeout=30).read().decode('utf-8')
        m = re.search(r'https://fonts\.gstatic\.com/[^) ]+\.woff2', css)
        if not m:
            sys.exit('ERROR: could not resolve woff2 url from css2')
        print('  downloading full font...')
        _fetch(m.group(0), FULL_FONT, binary=True)


def load_codepoints():
    cp = {}
    for line in open(CODEPOINTS, encoding='utf-8'):
        parts = line.split()
        if len(parts) == 2:
            cp[parts[0]] = int(parts[1], 16)
    return cp


def collect_used():
    used = set(EXTRA_ICONS)
    for f in glob.glob(os.path.join(TEMPLATES, '**', '*.html'), recursive=True):
        used.update(ICON_CALL_RE.findall(open(f, encoding='utf-8').read()))
    return used


def regen_icons_py(name_to_cp):
    src = open(ICONS_PY, encoding='utf-8').read()
    lines = ['ICON_CODEPOINTS = {']
    for name in sorted(name_to_cp):
        lines.append("    %r: 0x%x," % (name, name_to_cp[name]))
    lines.append('}')
    block = '\n'.join(lines)
    new = re.sub(r'ICON_CODEPOINTS = \{.*?\n\}', block, src, count=1, flags=re.DOTALL)
    open(ICONS_PY, 'w', encoding='utf-8').write(new)


def main():
    print('subset-icons: collecting used icons...')
    ensure_sources()
    cp = load_codepoints()
    used = collect_used()
    unknown = sorted(n for n in used if n not in cp)
    if unknown:
        sys.exit('ERROR: icons not found in codepoints file: %s' % ', '.join(unknown))
    name_to_cp = {n: cp[n] for n in used}
    print('  %d distinct icons used' % len(used))

    # 1) субсет шрифту рівно до потрібних кодпойнтів (без лігатур/літер).
    from fontTools import subset
    unicodes = sorted(name_to_cp.values())
    opts = subset.Options()
    opts.flavor = 'woff2'
    opts.layout_features = []
    opts.hinting = False
    opts.desubroutinize = True
    font = subset.load_font(FULL_FONT, opts)
    subsetter = subset.Subsetter(options=opts)
    subsetter.populate(unicodes=unicodes)
    subsetter.subset(font)
    subset.save_font(font, SERVED, opts)
    size = os.path.getsize(SERVED)
    print('  wrote %s (%d bytes)' % (os.path.relpath(SERVED, ROOT), size))

    # 2) регенерувати ICON_CODEPOINTS у app/icons.py.
    regen_icons_py(name_to_cp)
    print('  regenerated ICON_CODEPOINTS in %s' % os.path.relpath(ICONS_PY, ROOT))
    print('done.')


if __name__ == '__main__':
    main()
