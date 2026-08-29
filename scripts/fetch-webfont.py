#!/usr/bin/env python
"""Завантажити self-hosted веб-шрифт (latin + cyrillic) у app/static/fonts/.

НАВІЩО SELF-HOSTING: сторонній CDN -- це третя сторона в CSP, зайвий DNS і
запит на критичному шляху рендеру, плюс шрифт, який може зникнути. Файли
лежать у репозиторії, тож для роботи застосунку й тестів мережа НЕ потрібна:
скрипт запускають лише коли треба ДОДАТИ сімʼю або оновити версію.

ПІДМНОЖИНИ навмисно лише дві:
  latin     -- цифри, дати, ціни, латиниця в інтерфейсі;
  cyrillic  -- українська й російська (і/ї/є у U+0400-045F, ґ у U+0490-0491).
latin-ext / greek / vietnamese не тягнемо: символів з них у контенті немає, а
за unicode-range браузер відкотиться на системний шрифт для поодинокого гліфа,
якщо такий колись трапиться.

КИРИЛИЦЯ ОБОВʼЯЗКОВА. На цьому вже спіймались: перші статичні файли Inter
кирилиці не мали зовсім, і ВЕСЬ український текст мовчки малювався системним
шрифтом -- сторінка виглядала правильно рівно доти, доки дивишся на латиницю.
Скрипт падає, якщо кирилична підмножина не знайшлась.

ВАРІАТИВНИЙ проти статичного: варіативний файл покриває весь діапазон ваг
одним запитом. Для Inter це дало 65 КБ замість 118 КБ і на три запити менше.
Статичні накреслення беремо лише там, де варіативної версії немає (Carlito).

Запуск:
    python scripts/fetch-webfont.py roboto
    python scripts/fetch-webfont.py --all

Ліцензії: Inter, Nunito, Carlito -- SIL OFL 1.1; Roboto -- Apache 2.0.
Усі чотири дозволяють self-hosting.

Залежності: лише стандартна бібліотека.
"""
import argparse
import os
import re
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS_DIR = os.path.join(ROOT, 'app', 'static', 'fonts')

# Без сучасного UA Google віддає ttf замість woff2.
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')

SUBSETS = ('latin', 'cyrillic')

# family -- як його називає Google Fonts;
# axis   -- діапазон ваг для варіативного файлу або None для статичних;
# weights -- статичні накреслення (лише коли axis is None);
# prefix -- початок імені файлу в app/static/fonts/.
FAMILIES = {
    'inter': {'family': 'Inter', 'axis': '400..900', 'prefix': 'inter-var'},
    'roboto': {'family': 'Roboto', 'axis': '400..900', 'prefix': 'roboto-var'},
    'nunito': {'family': 'Nunito', 'axis': '400..900', 'prefix': 'nunito-var'},
    # Carlito варіативної версії не має -- беремо два накреслення, яких
    # вистачає: 400 для тексту, 700 для заголовків. Проміжні ваги браузер
    # синтезує, і для метрично-сумісного клону Calibri це прийнятно.
    'carlito': {'family': 'Carlito', 'weights': (400, 700), 'axis': None,
                'prefix': 'carlito'},
}

BLOCK_RE = re.compile(r'/\*\s*([a-z-]+)\s*\*/\s*@font-face\s*\{(.*?)\}', re.S)
URL_RE = re.compile(r'url\((https[^)]+)\)')
RANGE_RE = re.compile(r'unicode-range:\s*([^;]+);')
WEIGHT_RE = re.compile(r'font-weight:\s*([\d ]+);')


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def css_url(spec):
    if spec['axis']:
        return (f"https://fonts.googleapis.com/css2?family="
                f"{spec['family']}:wght@{spec['axis']}&display=optional")
    weights = ';'.join(str(w) for w in spec['weights'])
    return (f"https://fonts.googleapis.com/css2?family="
            f"{spec['family']}:wght@{weights}&display=optional")


def download(key):
    """Повертає dict subset -> (файл, розмір, unicode-range) або кидає."""
    spec = FAMILIES[key]
    css = fetch(css_url(spec)).decode('utf-8')
    blocks = BLOCK_RE.findall(css)
    if not blocks:
        raise SystemExit(f'{key}: не вдалось розібрати CSS -- змінився формат?')

    saved = {}
    for subset, body in blocks:
        if subset not in SUBSETS:
            continue
        url = URL_RE.search(body)
        if not url:
            continue
        weight = WEIGHT_RE.search(body)
        # Статичні сімʼї віддають по блоку на вагу; варіативні -- один.
        suffix = ''
        if spec['axis'] is None and weight:
            suffix = '-' + weight.group(1).strip().split()[0]
        name = f"{spec['prefix']}{suffix}-{subset}.woff2"
        data = fetch(url.group(1))
        with open(os.path.join(FONTS_DIR, name), 'wb') as fh:
            fh.write(data)
        rng = RANGE_RE.search(body)
        saved[name] = (len(data), rng.group(1).strip() if rng else '')
        print(f'  {name:34s} {len(data) / 1024:6.1f} КБ')

    got = {s for s in SUBSETS if any(f'-{s}.woff2' in n for n in saved)}
    missing = set(SUBSETS) - got
    if missing:
        raise SystemExit(f'{key}: не знайдено підмножин {sorted(missing)} -- '
                         'без кирилиці шрифт у цей проєкт не годиться')
    return saved


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('family', nargs='?', choices=sorted(FAMILIES))
    ap.add_argument('--all', action='store_true', help='усі сімʼї')
    args = ap.parse_args()
    if not args.family and not args.all:
        ap.error('вкажіть сімʼю або --all')

    keys = sorted(FAMILIES) if args.all else [args.family]
    total = 0
    ranges = {}
    for key in keys:
        print(f'{key}:')
        saved = download(key)
        total += sum(size for size, _ in saved.values())
        for name, (_, rng) in saved.items():
            ranges[name] = rng

    print(f'\nразом {total / 1024:.1f} КБ')
    print('\nunicode-range для app/static/css/fonts.css:')
    for name, rng in ranges.items():
        print(f'  /* {name} */\n  {rng}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
