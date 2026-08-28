#!/usr/bin/env python
"""Знімок обчислених стилів: чи змінився КАСКАД від правки в CSS.

Навіщо. Знімок розмітки (`html_snapshot.py`) доводить, що не змінився HTML.
Для правок у CSS він сліпий: розмітка та сама, а вигляд поїхав. Цей
інструмент відповідає на інше питання -- чи бачить браузер ті самі значення
властивостей після правки.

Потрібен там, де компонент зводиться до одного власника: клас, оголошений у
двох файлах, зливають в один, і треба довести, що жодна властивість не
загубилась. Побайтовий збіг обчислених стилів -- це доказ; око такого
доказу не дає.

Три речі, без яких він марний (і які тут ураховані):

1. НЕ беремо `width`/`height`. Це вже ВИКОРИСТАНІ значення, які рахує
   розкладка: вони гуляють між прогонами через гонку завантаження шрифтів,
   і шум вийде більший за справжню правку. Беремо оголошувані: падінги,
   межі, кольори, шрифт, флекс, `gap`.
2. Шум міряється у ДВОХ ПРОЦЕСАХ (`noise`). В одному процесі два прогони
   ділять ad-hoc TTL-кеші воркера й показують нуль там, де його немає --
   на цьому вже спіткнувся `html_snapshot.py`.
3. Зуби перевіряються на ЖИВОМУ оголошенні (`selftest`): якщо навмання
   взяти перебите правило, знімок «не помітить» правки, і ти повіриш у
   несправний інструмент.

БЕЗПЕКА. Сервер піднімається ВИКЛЮЧНО з `create_app('testing')` -- in-memory
SQLite, TESTING=True. Це не формальність: у конфізі за замовчуванням база
береться з DATABASE_URL (config.py:17), а create_app наприкінці підіймає
APScheduler (app/__init__.py:638); єдиний запобіжник від розсилки
запланованих листів живим людям стоїть саме на TESTING
(app/services/scheduler_service.py:66).

Використання:
    python tools/ds/computed_snapshot.py noise
    python tools/ds/computed_snapshot.py selftest
    python tools/ds/computed_snapshot.py capture --label before
    ...правки в CSS...
    python tools/ds/computed_snapshot.py capture --label after
    python tools/ds/computed_snapshot.py diff before after

    --only .apple-btn,.iprm-hero   обійти лише сторінки, де є ці класи
    --pages /,/courses/            явний перелік замість автопідбору

Код повернення: 0 -- розбіжностей немає; 1 -- є; 2 -- знімати нема чого.

ЗАМІРЯНІ МЕЖІ (стан на 28.08.2026 -- перевіряй прогоном, не вір тексту).

Шум НУЛЬ доведено на наборі публічних сторінок (`--only .apple-btn,...`,
16 сторінок). На наборі з адмінськими сторінками шум НЕ нульовий:

* `admin.error_logs` показує, що зламалось під час цього ж прогону --
  виключено через SKIP_ENDPOINTS;
* на решті адмінських лишається ~1900 розбіжностей, і причина в КЛЮЧІ:
  шлях будується з nth-of-type, тож один зайвий елемент (флеш-повідомлення,
  умовний алерт) зсуває індекси, і далі порівнюються різні елементи.
  Полагодити -- це або стабілізувати рендер адмінки, або зробити ключ
  стійкішим за позицію.

Псевдоелементи (`::before`, `::after`, `::placeholder`) НЕ знімаються.
Спроба їх додати дала 449 розбіжностей шуму. Наслідок практичний:
зведення, де один файл гасить псевдоелемент іншого (`content: none`), цей
знімок засвідчить як "змін немає". Такі правки потребують іншої перевірки.

ПЕРЕД КОЖНИМ НОВИМ НАБОРОМ СТОРІНОК МІРЯЙ ШУМ ЗАНОВО. "Шум нуль" --
твердження про конкретний набір, а не про інструмент.

Межа інструмента. Він бачить лише те, що відрендерилось: база порожня, тож
непорожні реєстри сюди не потрапляють, а сторінки з аргументом у шляху
(`/courses/<slug>`) не обходяться взагалі. Стани `:hover`, `:focus` і
медіа-запити інших ширин теж поза знімком -- вікно одне, 1440x900.

Вивід (tools/ds/computed/) у .gitignore: у git живе інструмент, не результат.
"""
import argparse
import json
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT_DIR = Path(__file__).resolve().parent / 'computed'
PORT = 5099

# Сторінки, вміст яких залежить від самого прогону.
SKIP_ENDPOINTS = {'admin.error_logs'}

# ОГОЛОШУВАНІ властивості. width/height свідомо відсутні -- див. докстрінг.
PROPS = [
    'color', 'background-color', 'background-image',
    'border-top-width', 'border-right-width', 'border-bottom-width', 'border-left-width',
    'border-top-color', 'border-right-color', 'border-bottom-color', 'border-left-color',
    'border-top-left-radius', 'border-top-right-radius',
    'border-bottom-left-radius', 'border-bottom-right-radius',
    'border-top-style', 'border-right-style', 'border-bottom-style', 'border-left-style',
    'padding-top', 'padding-right', 'padding-bottom', 'padding-left',
    # margin-* свідомо ВІДСУТНІ: `margin: auto` браузер віддає вже
    # РОЗРАХОВАНИМ ("507.828px"), тобто це теж використане значення --
    # воно гуляє від ширини тексту, а та від гонки завантаження шрифтів.
    'font-family', 'font-size', 'font-weight', 'font-style', 'line-height',
    'letter-spacing', 'text-align', 'text-transform', 'text-decoration-line',
    'display', 'flex-direction', 'flex-wrap', 'align-items', 'justify-content',
    'gap', 'row-gap', 'column-gap',
    # grid-template-* свідомо ВІДСУТНІ: браузер віддає їх уже
    # РОЗРАХОВАНИМИ в px ("305.391px 281.391px"), тобто це використані
    # значення, як width/height, і вони гуляють від висоти контенту.
    'position', 'box-shadow', 'opacity', 'overflow-x', 'overflow-y',
    'text-overflow', 'white-space', 'z-index', 'box-sizing', 'cursor',
]

# Обхід DOM: шлях елемента + значення властивостей. Шлях будується з
# nth-of-type, а не з класів: клас -- це саме те, що ми міняємо, і ключ,
# зроблений із нього, з'їхав би разом із правкою.


# Чекати, доки DOM перестане мінятись: жодної мутації протягом QUIET мс,
# але не довше за CAP. Фіксована пауза тут не працює -- скрипти дописують
# елементи в body з різною затримкою на різних сторінках.
_SETTLE_JS = """
() => new Promise((resolve) => {
  const QUIET = 500, CAP = 6000;
  // Перед тишею в DOM чекаємо, доки БРАУЗЕР ЗАСТОСУЄ всі таблиці стилів.
  // networkidle цього не гарантує: на одній сторінці другий прогін знімав
  // елементи з дефолтами браузера (border 0px, колір rgb(0,0,0)), бо
  // stylesheet ще не був розібраний -- 25 хибних розбіжностей на рівному
  // місці, які виглядали як справжня втрата стилів.
  const sheetsReady = () => Array.from(
    document.querySelectorAll('link[rel="stylesheet"]')
  ).every((l) => { try { return l.sheet !== null; } catch (e) { return true; } });
  let timer = null;
  const done = () => {
    if (!sheetsReady() && Date.now() - started < CAP) {
      timer = setTimeout(done, 100);
      return;
    }
    obs.disconnect();
    clearTimeout(hard);
    resolve(true);
  };
  const started = Date.now();
  const obs = new MutationObserver(() => {
    clearTimeout(timer);
    timer = setTimeout(done, QUIET);
  });
  obs.observe(document.documentElement,
              {childList: true, subtree: true, attributes: true});
  timer = setTimeout(done, QUIET);
  const hard = setTimeout(done, CAP);
})
"""

_SHEETS_JS = """
// Таблиці стилів, які НЕ готові: або браузер їх не отримав (`sheet === null`),
// або отримав, але не розібрав -- тоді `cssRules` кидає SecurityError чи дає
// нуль правил. Друге трапляється саме на дев-сервері під навантаженням
// статики, і воно небезпечніше за перше: `sheet` не null, сторінка виглядає
// цілою, а частина правил не діє. Знімок при цьому пише дефолти браузера
// (border 0px, rgb(0,0,0)) -- і це не відрізнити від справжньої втрати
// стилів під час зведення компонентів.
() => Array.from(document.querySelectorAll('link[rel=\"stylesheet\"]'))
  .filter((l) => {
    if (l.sheet === null) return true;
    try { return l.sheet.cssRules.length === 0; } catch (e) { return true; }
  })
  .map((l) => (l.getAttribute('href') || '').split('/').pop())
"""

_WALK_JS = """
(arg) => {
  const props = arg.props, wanted = arg.wanted;
  const out = {};
  // Ключ елемента -- ПІДПИС (тег + класи), а не позиція серед сусідів.
  //
  // Позиційний ключ (`div[3]/p[1]`) виглядає нейтральним, але ламається
  // від однієї зайвої вставки: флеш-повідомлення в одному прогоні зсуває
  // індекси всіх наступних сусідів, і далі порівнюються РІЗНІ елементи.
  // На адмінських сторінках це давало ~1900 хибних розбіжностей.
  //
  // Класи для цієї задачі стабільні: знімок порівнює правки в CSS, а вони
  // розмітки не міняють. Якщо клас усе ж змінили, елемент чесно покажеться
  // як зниклий і новий -- це видима зміна, а не тихий зсув.
  function sigOf(el) {
    const cls = Array.from(el.classList).sort().join('.');
    return el.tagName.toLowerCase() + (cls ? '.' + cls : '');
  }
  function pathOf(el) {
    const parts = [];
    while (el && el.nodeType === 1 && el.tagName !== 'HTML') {
      const parent = el.parentElement;
      const sig = sigOf(el);
      let idx = 1;
      if (parent) {
        for (const sib of parent.children) {
          if (sib === el) break;
          if (sigOf(sib) === sig) idx++;
        }
      }
      parts.unshift(sig + '[' + idx + ']');
      el = parent;
    }
    return parts.join('/');
  }
  // Обходимо СЕРВЕРНИЙ каркас сторінки -- header/main/footer, -- а не
  // весь body. Усе, що лежить у body поза ними, малює й ховає JS:
  // фоновий canvas (#molecular-background, ще й із власним слуханням
  // prefers-reduced-motion), смуга найближчих подій, нагадування, тости,
  // кнопка «вгору», one-tap. Вони з'являються то в одному прогоні, то в
  // іншому й до компонентів, які ми зводимо, стосунку не мають.
  const roots = document.querySelectorAll('body > header, body > main, body > footer');
  const scope = roots.length ? roots : (document.body ? [document.body] : []);
  const all = [];
  for (const root of scope) {
    all.push(root);
    for (const el of root.querySelectorAll('*')) all.push(el);
  }
  for (const el of all) {
    // Звуження до елементів, які нас цікавлять. Без нього знімок тягне
    // всю сторінку, і будь-який чужий віджет зі станом (валідація форми,
    // мовні вкладки, фокус) дає розбіжності, що не стосуються правки.
    if (wanted.length && !wanted.some((c) => el.classList.contains(c))) continue;
    const key = pathOf(el);
    // Псевдоелементи знімаємо ОКРЕМО. Без них знімок сліпий рівно там, де
    // компоненти найчастіше розходяться: галочка списку, стрілка, плейсхолдер.
    // `content: none` в іншому файлі гасить цілий псевдоелемент, не змінивши
    // в розмітці жодного байта -- і знімок без цього блоку засвідчить таку
    // правку як "змін немає".
    for (const pseudo of [null, '::before', '::after', '::placeholder']) {
      const cs = getComputedStyle(el, pseudo);
      if (pseudo && pseudo !== '::placeholder'
          && cs.getPropertyValue('content') === 'none') continue;
      const rec = {};
      for (const p of props) rec[p] = cs.getPropertyValue(p);
      if (pseudo) rec['content'] = cs.getPropertyValue('content');
      out[key + (pseudo || '')] = rec;
    }
  }
  // Службовий запис: які таблиці стилів реально застосувались і скільки в
  // них правил. Якщо два прогони дають різні значення -- проблема не в
  // знімку, а в тому, що сторінка щоразу малюється інакше.
  out['__sheets__'] = {
    'list': Array.from(document.styleSheets).map((s) => {
      let n = -1;
      try { n = s.cssRules.length; } catch (e) { n = -2; }
      return (s.href ? s.href.split('/').pop() : 'inline') + ':' + n;
    }).join(' | '),
  };
  return out;
}
"""


def build_app():
    from app import create_app
    from app.extensions import db

    app = create_app('testing')
    if not app.config.get('TESTING'):
        raise SystemExit('ВІДМОВА: додаток піднявся без TESTING.')
    if 'memory' not in app.config.get('SQLALCHEMY_DATABASE_URI', ''):
        raise SystemExit('ВІДМОВА: очікував in-memory SQLite.')
    with app.app_context():
        db.create_all()
        # Створюємо рядок налаштувань ЗАРАЗ: SiteSettings.get() робить це
        # ліниво, а сервер тут багатопотоковий -- два одночасні запити
        # вставляли id=1 разом і падали на UNIQUE.
        from app.models.site_settings import SiteSettings
        SiteSettings.get()
    return app


def make_admin(app):
    """Адмін у базі цього прогону. Без сесії адмінка віддає редирект, і
    сторінки, де живе admin.css, у знімок не потраплять зовсім."""
    from app.extensions import db
    from app.models.user import User

    with app.app_context():
        user = User(email='computed-snapshot@example.invalid')
        user.is_admin = True
        user.email_confirmed = True
        db.session.add(user)
        db.session.commit()
        return str(user.id)


def page_urls(app, user_id, explicit, only_classes):
    """Сторінки для обходу.

    Беремо ті самі цілі, що й html_snapshot (GET-роути без обов'язкових
    аргументів, дедупліковані за endpoint), лишаємо ті, що дали 200, і --
    якщо задано --only -- лише ті, у чиїй розмітці ці класи є. Обходити
    сторінку, де компонента немає, безглуздо: вона лише додасть шуму.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import html_snapshot

    targets = html_snapshot.targets(app, [], set())
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['_user_id'] = user_id
        sess['_fresh'] = True

    urls = []
    for endpoint, url in targets:
        # Журнал помилок показує, що зламалось під час ЦЬОГО прогону, тож
        # два прогони дають різну кількість рядків за визначенням. Це не
        # шум інструмента, а зміст сторінки.
        if endpoint in SKIP_ENDPOINTS:
            continue
        try:
            resp = client.get(url)
        except Exception:                                   # noqa: BLE001
            continue
        if resp.status_code != 200:
            continue
        if 'text/html' not in resp.headers.get('Content-Type', ''):
            continue
        if only_classes:
            body = resp.get_data(as_text=True)
            if not any(('class="' in body and cls.lstrip('.') in body)
                       for cls in only_classes):
                continue
        urls.append((endpoint, url))
    if explicit:
        wanted = set(explicit)
        urls = [(e, u) for e, u in urls if u in wanted]
    return urls


def capture(label, explicit, only_classes, theme='light', quiet=False):
    from werkzeug.serving import make_server
    from playwright.sync_api import sync_playwright

    app = build_app()
    user_id = make_admin(app)
    pages = page_urls(app, user_id, explicit, only_classes)
    if not pages:
        print('жодної сторінки не відібрано')
        return 0

    server = make_server('127.0.0.1', PORT, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    outdir = OUT_DIR / label
    if outdir.exists():
        for old in outdir.glob('*.json'):
            old.unlink()
    outdir.mkdir(parents=True, exist_ok=True)

    kept = 0
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            # reduced_motion + глушник переходів: без них opacity знімається
            # посеред reveal-анімації і дає до двох десятків хибних
            # розбіжностей на прогін. `!important` тут -- в інжектованому
            # стилі інструмента, не в коді проєкту.
            # Тему треба ЗАКРІПИТИ. Без color_scheme прогони беруть
            # системну, і знімок мовчки порівнює світлу тему з тёмною:
            # у першому ж вимірі це дало 1019 хибних розбіжностей.
            # Тёмна перевіряється окремим прогоном (--theme dark).
            context = browser.new_context(viewport={'width': 1440, 'height': 900},
                                          reduced_motion='reduce',
                                          color_scheme=theme)
            context.add_init_script("""
                const kill = document.createElement('style');
                kill.textContent = '*,*::before,*::after{' +
                    'transition:none !important;animation:none !important;}';
                document.addEventListener('DOMContentLoaded', () => {
                    document.head.appendChild(kill);
                });
            """)
            # Сесія Flask-Login через cookie: підписуємо її самим додатком.
            from flask.sessions import SecureCookieSessionInterface
            serializer = SecureCookieSessionInterface().get_signing_serializer(app)
            cookie = serializer.dumps({'_user_id': user_id, '_fresh': True})
            context.add_cookies([{
                'name': app.config.get('SESSION_COOKIE_NAME', 'session'),
                'value': cookie, 'domain': '127.0.0.1', 'path': '/',
            }])
            page = context.new_page()
            for endpoint, url in pages:
                page.goto('http://127.0.0.1:%d%s' % (PORT, url),
                          wait_until='networkidle')
                # Чекаємо на ТИШУ В DOM, а не на фіксований час. Скрипти
                # дописують у body canvas фону, кнопку «вгору», контейнер
                # тостів -- кожен у свій момент, і фіксована пауза ловить їх
                # то в одному прогоні, то в іншому: саме це давало вісім
                # хибних розбіжностей на прогін.
                page.evaluate(_SETTLE_JS)
                # Якщо якийсь stylesheet не застосувався, знімати НЕ МОЖНА:
                # браузер віддасть дефолти (border 0px, rgb(0,0,0)), і це
                # виглядатиме як справжня втрата стилів. Дев-сервер під
                # навантаженням статики іноді таки не віддає файл, тож одна
                # спроба перезавантажити -- і, якщо не допомогло, гучна
                # відмова замість тихого сміття.
                missing = page.evaluate(_SHEETS_JS)
                for _ in range(3):
                    if not missing:
                        break
                    page.reload(wait_until='networkidle')
                    page.evaluate(_SETTLE_JS)
                    missing = page.evaluate(_SHEETS_JS)
                if missing:
                    raise SystemExit(
                        'ВІДМОВА на %s: не застосувались таблиці стилів %s. '
                        'Знімок із дефолтами браузера гірший за відсутній.'
                        % (url, ', '.join(missing)))
                data = page.evaluate(_WALK_JS, {'props': PROPS,
                                'wanted': [c.lstrip('.') for c in only_classes]})
                (outdir / ('%s.json' % endpoint.replace('/', '_'))).write_text(
                    json.dumps(data, ensure_ascii=False, sort_keys=True, indent=0),
                    encoding='utf-8')
                kept += 1
            browser.close()
    finally:
        server.shutdown()

    if not quiet:
        print('знімок "%s" (%s тема): %d сторінок -> %s'
              % (label, theme, kept, outdir))
    return kept


def compare(before, after, quiet=False, limit=25):
    dir_a, dir_b = OUT_DIR / before, OUT_DIR / after
    for path in (dir_a, dir_b):
        if not path.exists():
            raise SystemExit('немає знімка %s' % path)

    names_a = {p.name for p in dir_a.glob('*.json')}
    names_b = {p.name for p in dir_b.glob('*.json')}
    diffs = []
    for name in sorted(names_a & names_b):
        data_a = json.loads((dir_a / name).read_text(encoding='utf-8'))
        data_b = json.loads((dir_b / name).read_text(encoding='utf-8'))
        for path in sorted(set(data_a) & set(data_b)):
            for prop in PROPS:
                va, vb = data_a[path].get(prop), data_b[path].get(prop)
                if va != vb:
                    diffs.append((name, path, prop, va, vb))
        for path in sorted(set(data_a) ^ set(data_b)):
            diffs.append((name, path, '(елемент)',
                          'є' if path in data_a else '-',
                          'є' if path in data_b else '-'))

    if not quiet:
        pages = len({d[0] for d in diffs})
        print('звірено %d сторінок: %d розбіжностей на %d сторінках'
              % (len(names_a & names_b), len(diffs), pages))
        for name, path, prop, va, vb in diffs[:limit]:
            print('  %s\n    %s\n    %-24s %s -> %s'
                  % (name, path[-90:], prop, va, vb))
        if len(diffs) > limit:
            print('  ... ще %d' % (len(diffs) - limit))
    return len(diffs)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='cmd', required=True)

    for name in ('capture', 'noise', 'selftest'):
        sp = sub.add_parser(name)
        if name == 'capture':
            sp.add_argument('--label', required=True)
        sp.add_argument('--theme', default='light', choices=('light', 'dark'))
        sp.add_argument('--only', default='',
                        help='лише сторінки з цими класами, через кому')
        sp.add_argument('--pages', default='', help='явні URL через кому')

    dif = sub.add_parser('diff')
    dif.add_argument('before')
    dif.add_argument('after')

    args = parser.parse_args()
    only = [c for c in getattr(args, 'only', '').split(',') if c]
    explicit = [p for p in getattr(args, 'pages', '').split(',') if p]

    if args.cmd == 'capture':
        return 0 if capture(args.label, explicit, only, args.theme) else 2

    if args.cmd == 'diff':
        return 1 if compare(args.before, args.after) else 0

    # noise і selftest -- обидва потребують двох прогонів в ОКРЕМИХ процесах
    self_path = str(Path(__file__).resolve())
    common = ['--theme', getattr(args, 'theme', 'light')]
    if only:
        common += ['--only', ','.join(only)]
    if explicit:
        common += ['--pages', ','.join(explicit)]

    if args.cmd == 'noise':
        for label in ('_noise_a', '_noise_b'):
            if subprocess.call([sys.executable, self_path, 'capture',
                                '--label', label] + common) != 0:
                return 2
        n = compare('_noise_a', '_noise_b')
        if n:
            print('\nшум інструмента: %d розбіжностей -- знімок НЕПРИДАТНИЙ.' % n)
            return 1
        print('\nшум інструмента: НУЛЬ -- знімок придатний.')
        return 0

    # selftest: перевірка зубів на ЖИВОМУ оголошенні
    print('selftest виконується вручну -- див. докстрінг і README:')
    print('  1) capture --label t0')
    print('  2) внести правку в 1px у ЖИВЕ оголошення')
    print('  3) capture --label t1 && diff t0 t1 -- має показати саме її')
    print('  4) відкотити правку')
    return 0


if __name__ == '__main__':
    sys.exit(main())
