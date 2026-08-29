#!/usr/bin/env python
"""Знімок вихідного HTML: чи не змінилась розмітка від правки в шаблонах.

Навіщо. Правка, яка мала лишити розмітку тією самою (перехід на макрос,
винесення партіала, злиття двох написань одного компонента), або лишає її
тією самою -- або ні. Око цього не бачить: між `<span class="x">` і
`<div class="x">` на екрані різниці немає, поки не поїде розкладка на
вужчому вікні. Знімок порівнює вихідний HTML побайтово, тож "нуль
розбіжностей" -- це доказ, а не враження.

Як це працює:
  1. піднімається додаток у конфізі `testing` -- in-memory SQLite, TESTING=True;
  2. перебираються всі GET-роути, які не потребують аргументів;
  3. кожен рендериться тестовим клієнтом, лишаються ті, що дали 200 і text/html;
  4. відповідь нормалізується (версія статики, пробіли між тегами) і лягає
     файлом у каталог знімка.

БЕЗПЕКА. Інструмент піднімає додаток ВИКЛЮЧНО з конфігом `testing` і падає,
якщо TESTING не виставлено. Це не формальність: у конфізі за замовчуванням
база береться з DATABASE_URL (config.py:17), а create_app наприкінці підіймає
APScheduler (app/__init__.py:637) -- єдиний запобіжник від розсилки
запланованих листів живим людям стоїть саме на TESTING
(app/services/scheduler_service.py:66). Ad-hoc скрипт, який робить
create_app() без аргументу, обходить обидва.

Хто дивиться. За замовчуванням -- залогінений адмін: без сесії 93 зі 127
роутів віддають редирект на логін, тобто вся адмінка (там, де живе
`admin.css` і куди дивиться дизайн-система) у знімок не потрапляє взагалі.
Користувач створюється в in-memory базі цього ж прогону й нікуди більше не
потрапляє. `--anonymous` знімає публічний вигляд -- те, що бачить гість.

Використання:
    python tools/ds/html_snapshot.py capture --label before
    ... правки ...
    python tools/ds/html_snapshot.py capture --label after
    python tools/ds/html_snapshot.py diff before after

    python tools/ds/html_snapshot.py noise          # два прогони: має бути 0
    python tools/ds/html_snapshot.py capture --label before --anonymous
    python tools/ds/html_snapshot.py capture --label before --langs ru,en
    python tools/ds/html_snapshot.py capture --label before --only courses,main

Код повернення: 0 -- розбіжностей немає; 1 -- є розбіжності; 2 -- знімати
нема чого (жодна сторінка не віддала 200).

Межа інструмента. Знімок бачить лише те, що відрендерилось. База порожня,
тож порожні стани сюди потрапляють, а НЕпорожні реєстри -- ні; сторінки під
логіном і сторінки з аргументом у шляху (`/courses/<slug>`) не знімаються
взагалі. Правку в них знімок покаже як "змін немає". Такі місця щупай окремо.

Результати прогонів (tools/ds/snapshots/) навмисно не в репозиторії: у git
живе інструмент, а не його вивід. Так само зроблено для tools/perf/runs/.
"""
import argparse
import difflib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SNAP_DIR = Path(__file__).resolve().parent / 'snapshots'

# Роути, які віддають не HTML. Решта відсіється сама -- за статусом і
# Content-Type, тож список навмисно короткий.
SKIP_ENDPOINTS = {'static'}

# Підпис картки вільного місця на /admin/backups -- див. нормалізатор нижче.
LABEL = 'Вільне місце'

# Динаміка, яка змінюється між прогонами й не є розміткою.
NORMALIZERS = [
    # ?v={{ assets_version }} -- залежить від mtime статики
    (re.compile(r'([?&]v=)[^"\'&\s>]+'), r'\1SNAP'),
    # csrf -- на випадок, якщо його колись увімкнуть і в testing
    (re.compile(r'(name="csrf_token"[^>]*value=")[^"]*'), r'\1SNAP'),
    # час доби. /admin/integrations друкує "Перевірено: 13:19:53 ...".
    # Нормалізуємо саме ЧАС, а не рядок цілком: дата лишається видимою, тож
    # підміну формату дати знімок усе одно помітить.
    (re.compile(r'\b\d{1,2}:\d{2}:\d{2}\b'), 'SNAP-TIME'),
    # вільне місце на диску. /admin/backups друкує його карткою, і воно
    # повзе саме собою -- зокрема тому, що знімок 77 сторінок його ж і
    # витрачає. Тобто інструмент виробляв власний шум і показував чужу
    # сторінку як "змінену" після будь-якої правки.
    #
    # Пробіли між тегами тут ще НЕ склеєні: NORMALIZERS застосовуються до
    # _BETWEEN_TAGS, тож патерн мусить їх допускати. Без \s* правило мовчки
    # не спрацьовує -- і виглядає як робоче.
    #
    # Глушиться РІВНО ця картка, а не всі розміри на сторінці: сусідні
    # картки друкують розмір копій і їхню кількість, і це справжній вміст,
    # який знімок мусить бачити. Прив'язка -- до підпису картки.
    (re.compile(r'(backup-stats__value">)[^<]*(</div>\s*<div class="backup-stats__label">\s*'
                + re.escape(LABEL) + ')'), r'\1SNAP-DISK\2'),
]

_BETWEEN_TAGS = re.compile(r'>\s+<')
_MANY_SPACES = re.compile(r'[ \t]{2,}')


def build_app():
    """Додаток у конфізі testing. Інакше -- відмова, а не спроба."""
    from app import create_app
    from app.extensions import db

    app = create_app('testing')
    if not app.config.get('TESTING'):
        raise SystemExit(
            'ВІДМОВА: додаток піднявся без TESTING. Знімати HTML можна лише '
            'на testing-конфізі (in-memory SQLite); інакше запит піде в базу '
            'з DATABASE_URL, а планувальник -- у роботу.'
        )
    uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if 'memory' not in uri:
        raise SystemExit('ВІДМОВА: очікував in-memory SQLite, отримав %r.' % uri)
    with app.app_context():
        db.create_all()
    return app


def login_admin(app, client):
    """Посадити в сесію клієнта адміна з in-memory бази.

    Через session_transaction, а не через форму логіну: форма -- це ще один
    шлях, який може змінитись і зламати інструмент; сесія Flask-Login --
    контракт, що не змінюється.
    """
    from app.extensions import db
    from app.models.user import User

    with app.app_context():
        user = User(email='ds-snapshot@example.invalid')
        user.is_admin = True
        user.email_confirmed = True
        db.session.add(user)
        db.session.commit()
        user_id = str(user.id)

    with client.session_transaction() as sess:
        sess['_user_id'] = user_id
        sess['_fresh'] = True


def targets(app, langs, only):
    """(endpoint, url) для GET-роутів без обов'язкових аргументів.

    LocalizedBlueprint реєструє КОЖНЕ правило двічі -- без префікса (з
    defaults={'lang_code': 'uk'}) і з /<any(ru, en):lang_code>
    (app/i18n.py:221-231). Тобто перебір url_map дає ту саму сторінку двічі, а
    з розкриттям префікса -- тричі. Ключ дедуплікації -- endpoint: беремо
    непрефіксоване правило, а мовні варіанти додаємо лише на явну вимогу
    (--langs), бо в них перевіряється переклад, а не розмітка.
    """
    seen = {}
    for rule in app.url_map.iter_rules():
        if 'GET' not in (rule.methods or set()):
            continue
        if rule.endpoint in SKIP_ENDPOINTS:
            continue
        if only and rule.endpoint.split('.')[0] not in only:
            continue
        required = set(rule.arguments) - set((rule.defaults or {}).keys())
        if required:
            continue
        # префіксоване правило тієї самої сторінки -- пропускаємо
        if 'lang_code' in rule.arguments and not rule.defaults:
            continue
        seen.setdefault(rule.endpoint, rule.rule)

    out = sorted(seen.items())
    for lang in langs:
        for endpoint, url in sorted(seen.items()):
            if app.url_map.is_endpoint_expecting(endpoint, 'lang_code'):
                out.append(('%s@%s' % (endpoint, lang), '/%s%s' % (lang, url)))
    return out


def normalize(html):
    for pattern, repl in NORMALIZERS:
        html = pattern.sub(repl, html)
    html = _BETWEEN_TAGS.sub('><', html)
    html = _MANY_SPACES.sub(' ', html)
    return '\n'.join(line.strip() for line in html.splitlines() if line.strip())


def capture(label, langs, only, anonymous=False, quiet=False):
    app = build_app()
    pages = targets(app, langs, only)
    outdir = SNAP_DIR / label
    if outdir.exists():
        for old in outdir.glob('*.html'):
            old.unlink()
    outdir.mkdir(parents=True, exist_ok=True)

    kept = 0
    skipped = []
    client = app.test_client()
    if not anonymous:
        login_admin(app, client)
    for endpoint, url in pages:
        try:
            resp = client.get(url)
        except Exception as exc:                            # noqa: BLE001
            skipped.append('виняток %s' % type(exc).__name__)
            continue
        if resp.status_code != 200:
            skipped.append(str(resp.status_code))
            continue
        if 'text/html' not in resp.headers.get('Content-Type', ''):
            skipped.append('не html')
            continue
        body = normalize(resp.get_data(as_text=True))
        name = endpoint.replace('/', '_') + '.html'
        (outdir / name).write_text(body, encoding='utf-8')
        kept += 1

    if not quiet:
        print('знімок "%s" (%s): %d сторінок з %d роутів -> %s'
              % (label, 'гість' if anonymous else 'адмін', kept, len(pages), outdir))
        if skipped:
            reasons = {}
            for why in skipped:
                reasons[why] = reasons.get(why, 0) + 1
            summary = ', '.join('%s: %d' % (why, n) for why, n in sorted(reasons.items()))
            print('  не знято %d (%s)' % (len(skipped), summary))
    return kept


def compare(before, after, quiet=False):
    dir_a, dir_b = SNAP_DIR / before, SNAP_DIR / after
    for path in (dir_a, dir_b):
        if not path.exists():
            raise SystemExit('немає знімка %s' % path)
    files_a = {p.name for p in dir_a.glob('*.html')}
    files_b = {p.name for p in dir_b.glob('*.html')}

    changed = []
    for name in sorted(files_a & files_b):
        text_a = (dir_a / name).read_text(encoding='utf-8')
        text_b = (dir_b / name).read_text(encoding='utf-8')
        if text_a != text_b:
            changed.append(name)
    only_a = sorted(files_a - files_b)
    only_b = sorted(files_b - files_a)

    if not quiet:
        print('звірено %d сторінок: %d з розбіжністю'
              % (len(files_a & files_b), len(changed)))
        for name in changed:
            lines_a = (dir_a / name).read_text(encoding='utf-8').splitlines()
            lines_b = (dir_b / name).read_text(encoding='utf-8').splitlines()
            delta = list(difflib.unified_diff(
                lines_a, lines_b, before, after, lineterm='', n=1))
            print('\n--- %s ---' % name)
            print('\n'.join(delta[:40]))
            if len(delta) > 40:
                print('  ... ще %d рядків різниці' % (len(delta) - 40))
        if only_a:
            print('\nзникли у "%s": %s' % (after, ', '.join(only_a)))
        if only_b:
            print('\nз\'явились у "%s": %s' % (after, ', '.join(only_b)))
    return len(changed) + len(only_a) + len(only_b)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='cmd', required=True)

    cap = sub.add_parser('capture', help='зняти знімок')
    cap.add_argument('--label', required=True, help='ім\'я знімка (before / after)')
    cap.add_argument('--langs', default='', help='мовні варіанти через кому: ru,en')
    cap.add_argument('--only', default='', help='лише ці блюпринти, через кому')
    cap.add_argument('--anonymous', action='store_true',
                     help='без сесії адміна -- публічний вигляд')

    dif = sub.add_parser('diff', help='порівняти два знімки')
    dif.add_argument('before')
    dif.add_argument('after')

    noi = sub.add_parser('noise', help='два прогони поспіль: розбіжностей має бути 0')
    noi.add_argument('--anonymous', action='store_true')

    args = parser.parse_args()

    if args.cmd == 'capture':
        langs = [x for x in args.langs.split(',') if x]
        only = {x for x in args.only.split(',') if x}
        return 0 if capture(args.label, langs, only, args.anonymous) else 2

    if args.cmd == 'diff':
        return 1 if compare(args.before, args.after) else 0

    # Кожен прогін -- ОКРЕМИЙ процес. В одному процесі два знімки ділили б
    # ad-hoc TTL-кеші, що живуть у пам'яті воркера (integration_health,
    # home_service._stats_cache, JWKS), і шум, який вони маскують, спливав би
    # не тут, а на справжньому порівнянні before/after -- де його вже не
    # відрізнити від власної правки. Саме так ця перевірка й показала
    # спершу НУЛЬ там, де насправді був час на /admin/integrations.
    import subprocess

    for label in ('_noise_a', '_noise_b'):
        cmd = [sys.executable, str(Path(__file__).resolve()),
               'capture', '--label', label]
        if args.anonymous:
            cmd.append('--anonymous')
        if subprocess.call(cmd) != 0:
            return 2
    noise = compare('_noise_a', '_noise_b')
    if noise:
        print('\nшум інструмента: %d розбіжностей -- знімок НЕПРИДАТНИЙ. '
              'Знайди джерело і внеси в NORMALIZERS.' % noise)
        return 1
    print('\nшум інструмента: НУЛЬ -- знімок придатний.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
