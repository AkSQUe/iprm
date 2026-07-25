#!/usr/bin/env python
"""Завантажити варіативний Inter (latin + cyrillic) у app/static/fonts/.

Регенерує:
  * app/static/fonts/inter-var-latin.woff2
  * app/static/fonts/inter-var-cyrillic.woff2

НАВІЩО: статичні накреслення 400/500/600/700/800 важили 118.6 КБ і
завантажувались УСІ на кожній сторінці (виміряно). Варіативний шрифт покриває
весь діапазон ваг 400-800 двома файлами (~65 КБ) і трьома запитами менше.

КОЛИ ЗАПУСКАТИ: якщо треба оновити версію шрифту або додати підмножину
(напр. latin-ext). Для роботи застосунку й тестів мережа НЕ потрібна --
файли лежать у репозиторії.

Джерело: Google Fonts CSS API (та сама сімʼя, що й раніші статичні файли).
Ліцензія Inter -- SIL Open Font License 1.1, self-hosting дозволено.

Підмножини навмисно лише дві:
  latin     -- цифри, дати, ціни, латиниця в інтерфейсі;
  cyrillic  -- українська й російська (і/ї/є у U+0400-045F, ґ у U+0490-0491).
latin-ext / greek / vietnamese не тягнемо: символів з них у контенті немає, а
за unicode-range браузер просто відкотиться на системний шрифт для поодинокого
глифа, якщо такий колись трапиться.

Залежності: лише стандартна бібліотека.
"""
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS_DIR = os.path.join(ROOT, 'app', 'static', 'fonts')

CSS_URL = ('https://fonts.googleapis.com/css2'
           '?family=Inter:wght@400..800&display=optional')
# Без сучасного UA Google віддає ttf замість woff2.
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')

WANTED = {'latin': 'inter-var-latin.woff2', 'cyrillic': 'inter-var-cyrillic.woff2'}

BLOCK_RE = re.compile(r'/\*\s*([a-z-]+)\s*\*/\s*@font-face\s*\{(.*?)\}', re.S)
URL_RE = re.compile(r'url\((https[^)]+)\)')
RANGE_RE = re.compile(r'unicode-range:\s*([^;]+);')


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def main():
    css = fetch(CSS_URL).decode('utf-8')
    blocks = BLOCK_RE.findall(css)
    if not blocks:
        print('Не вдалось розібрати CSS Google Fonts -- змінився формат?')
        return 1

    seen = {}
    for subset, body in blocks:
        if subset not in WANTED:
            continue
        m = URL_RE.search(body)
        rng = RANGE_RE.search(body)
        if not m:
            continue
        data = fetch(m.group(1))
        dst = os.path.join(FONTS_DIR, WANTED[subset])
        with open(dst, 'wb') as fh:
            fh.write(data)
        seen[subset] = (len(data), rng.group(1).strip() if rng else '')
        print(f'{WANTED[subset]:28s} {len(data) / 1024:6.1f} КБ')

    missing = set(WANTED) - set(seen)
    if missing:
        print(f'Не знайдено підмножин: {sorted(missing)}')
        return 1

    print('\nunicode-range для app/static/css/fonts.css:')
    for subset, (_, rng) in seen.items():
        print(f'  /* {subset} */ {rng}')
    total = sum(size for size, _ in seen.values())
    print(f'\nразом {total / 1024:.1f} КБ (статичні 400-800 важили 118.6 КБ)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
