"""Генерація та видача сертифікатів учасникам заходів.

Формат -- PDF через HTML (WeasyPrint). Фон-молекули генеруються як
детермінований статичний SVG (JS-плагін у PDF не виконується). Логотип --
готовий SVG з app/static/svg. Підписи та печатка -- плейсхолдери.

Публічний API:
  * issue_certificate(registration, issued_by=None) -> Certificate
  * regenerate_pdf(certificate) -> str (абсолютний шлях)
  * certificate_abs_path(certificate) -> str
  * read_pdf_bytes(certificate) -> bytes
"""
import logging
import math
import os
import random

from flask import current_app, render_template
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.certificate import Certificate
from app.models.mixins import utcnow

logger = logging.getLogger(__name__)

# Колір фону-молекул -- м'який сіро-бузковий (як на зразку сертифіката).
_MOLECULE = (176, 168, 196)


def _blend_on_white(rgb, alpha):
    """Змішати колір з білим (alpha -- частка кольору). Повертає 'rgb(r,g,b)'.

    Кольори запікаємо заздалегідь замість stroke/fill-opacity: WeasyPrint
    непослідовно рендерить per-element opacity у SVG, що давало поодинокі
    темні лінії. Суцільний світлий колір гарантує рівний блідий фон.
    """
    r, g, b = rgb
    inv = 1 - alpha
    return (
        f'rgb({round(r * alpha + 255 * inv)},'
        f'{round(g * alpha + 255 * inv)},'
        f'{round(b * alpha + 255 * inv)})'
    )

_UA_MONTHS = [
    '', 'січня', 'лютого', 'березня', 'квітня', 'травня', 'червня',
    'липня', 'серпня', 'вересня', 'жовтня', 'листопада', 'грудня',
]


def format_ua_date(dt):
    """31 травня 2026 року. Повертає '' для None."""
    if not dt:
        return ''
    return f'{dt.day} {_UA_MONTHS[dt.month]} {dt.year} року'


def molecular_svg(seed, width=794, height=1123, node_count=74, link_distance=150):
    """Детермінований статичний SVG-фон з молекул (портретний A4).

    М'який сіро-бузковий мережевий візерунок, як на еталонному сертифікаті:
    тонкі лінії-зв'язки + вузли, де частина -- більші напівпрозорі диски.

    seed -- будь-який рядок (номер сертифіката), щоб візерунок був стабільним
    для конкретного сертифіката, але різним між ними.
    """
    rnd = random.Random(seed)
    nodes = []
    gap = 6.0            # мінімальний зазор між колами
    max_attempts = 80    # спроб знайти вільне місце для вузла
    for _ in range(node_count):
        # Різний розмір: малі/середні/великі, центр ~12 (поточний середній).
        r = rnd.triangular(6.0, 18.0, 12.0)
        for _ in range(max_attempts):
            x = rnd.uniform(0, width)
            y = rnd.uniform(0, height)
            # Без накладань: відстань між центрами > сума радіусів + зазор.
            if all(
                math.hypot(x - n['x'], y - n['y']) > r + n['r'] + gap
                for n in nodes
            ):
                nodes.append({'x': x, 'y': y, 'r': r})
                break
        # якщо вільного місця не знайдено -- вузол пропускаємо

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}">'
    ]

    # Кандидати-зв'язки між близькими вузлами, від найкоротших.
    candidates = []
    for i, a in enumerate(nodes):
        for j in range(i + 1, len(nodes)):
            b = nodes[j]
            dist = math.hypot(a['x'] - b['x'], a['y'] - b['y'])
            if dist < link_distance:
                candidates.append((dist, i, j))
    candidates.sort()

    # Union-find: додаємо зв'язок лише якщо об'єднана зв'язка <= MAX_GROUP
    # вузлів. Так кожна група з'єднаних кружечків має не більше 7 елементів.
    max_group = 7
    parent = list(range(len(nodes)))
    group_size = [1] * len(nodes)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    # Лінії-зв'язки (колір запечено з білим).
    for dist, i, j in candidates:
        ri, rj = find(i), find(j)
        if ri == rj or group_size[ri] + group_size[rj] > max_group:
            continue
        parent[ri] = rj
        group_size[rj] += group_size[ri]
        a, b = nodes[i], nodes[j]
        alpha = 0.15 * (1 - dist / link_distance)
        parts.append(
            f'<line x1="{a["x"]:.1f}" y1="{a["y"]:.1f}" '
            f'x2="{b["x"]:.1f}" y2="{b["y"]:.1f}" '
            f'stroke="{_blend_on_white(_MOLECULE, alpha)}" stroke-width="2.2"/>'
        )

    # Вузли -- усі однакового розміру й однакової насиченості.
    node_fill = _blend_on_white(_MOLECULE, 0.13)
    for n in nodes:
        parts.append(
            f'<circle cx="{n["x"]:.1f}" cy="{n["y"]:.1f}" r="{n["r"]:.1f}" '
            f'fill="{node_fill}"/>'
        )

    parts.append('</svg>')
    return ''.join(parts)


def _rounded_rect_path(x, y, w, h, r):
    """SVG path-дані для прямокутника із заокругленими кутами."""
    return (
        f'M{x + r:.2f},{y:.2f} H{x + w - r:.2f} '
        f'A{r:.2f},{r:.2f} 0 0 1 {x + w:.2f},{y + r:.2f} '
        f'V{y + h - r:.2f} A{r:.2f},{r:.2f} 0 0 1 {x + w - r:.2f},{y + h:.2f} '
        f'H{x + r:.2f} A{r:.2f},{r:.2f} 0 0 1 {x:.2f},{y + h - r:.2f} '
        f'V{y + r:.2f} A{r:.2f},{r:.2f} 0 0 1 {x + r:.2f},{y:.2f} Z'
    )


def frame_ring_svg(width=794, height=1123, inset_mm=7.0, thickness_mm=1.0, radius_mm=3.0):
    """Градієнтна рамка як порожнє кільце (заливка path з evenodd-діркою).

    Перевага над stroke: рендериться як суцільна фігура -> однакова товщина
    з усіх боків (stroke у масштабованому SVG WeasyPrint робив верх/низ
    товщими). Кути заокруглені, центр прозорий -> молекули видно крізь нього.
    """
    u = width / 210.0  # мм -> одиниці viewBox
    inset = inset_mm * u
    t = thickness_mm * u
    r_out = radius_mm * u
    r_in = max(r_out - t, 0.1)
    outer = _rounded_rect_path(inset, inset, width - 2 * inset, height - 2 * inset, r_out)
    inner = _rounded_rect_path(
        inset + t, inset + t, width - 2 * (inset + t), height - 2 * (inset + t), r_in,
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        '<defs><linearGradient id="frameGrad" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#f0a02a"/>'
        '<stop offset="0.5" stop-color="#b85a7e"/>'
        '<stop offset="1" stop-color="#7055a4"/>'
        '</linearGradient></defs>'
        f'<path fill-rule="evenodd" fill="url(#frameGrad)" d="{outer} {inner}"/>'
        '</svg>'
    )


def _event_snapshot(registration):
    """Витягти незмінні дані заходу з реєстрації."""
    instance = registration.instance
    course = instance.course if instance else None
    title = course.title if course else (registration.target_title or 'Захід')
    event_date = instance.start_date if instance else None
    cpd = registration.cpd_points_awarded
    if cpd is None and instance is not None:
        cpd = instance.effective_cpd_points
    trainer = instance.effective_trainer if instance else None
    lecturer = trainer.full_name if trainer else None
    signature = (trainer.signature or '').strip() if trainer and trainer.signature else None
    specialties = (course.bpr_specialties or '').strip() if course and course.bpr_specialties else None
    event_type = course.event_type_label.lower() if course and course.event_type else None
    place = (instance.location or '').strip() if instance and instance.location else None
    return title, event_date, cpd, lecturer, signature, specialties, event_type, place


_POINTS_BADGE_DIR = ('images', 'certificates')
_POINTS_BADGE_DEFAULT = 10

# Запасний підпис (коли у тренера немає власного) -- спільне зображення.
_DEFAULT_SIGNATURE = 'images/certificates/trainer-sign.webp'


def points_badge_url(cpd_points):
    """Відносний (від static) шлях до розетки балів БПР під цю кількість.

    Конвенція файлів: images/certificates/{N}-points-BPR.webp.
    Якщо файлу під конкретну кількість ще немає -- беремо дефолт (10 балів).
    """
    base = os.path.join(current_app.static_folder, *_POINTS_BADGE_DIR)
    points = cpd_points or _POINTS_BADGE_DEFAULT
    fname = f'{points}-points-BPR.webp'
    if not os.path.exists(os.path.join(base, fname)):
        fname = f'{_POINTS_BADGE_DEFAULT}-points-BPR.webp'
    return '/'.join(_POINTS_BADGE_DIR) + '/' + fname


_QR_FALLBACK_URL = 'https://iprm.space'


def _site_url():
    """Канонічна адреса сайту з налаштувань (fallback -- iprm.space).

    Той самий патерн, що в email_service: беремо website_url із SiteSettings,
    щоб QR вів на бойовий домен незалежно від SERVER_NAME у конфігу.
    """
    from app.models.site_settings import SiteSettings
    return (SiteSettings.get().website_url or '').strip().rstrip('/') or _QR_FALLBACK_URL


def qr_svg(url, border=2):
    """Inline-SVG QR-коду на задану адресу, у брендовому градієнті.

    Модулі малюємо як залиті квадрати одним path із fill="url(#qrGrad)"
    (той самий помаранчево-рожево-фіолетовий градієнт, що й рамка). Свідомо
    НЕ використовуємо segno.svg_inline (там модулі -- stroke-лінії): WeasyPrint
    непослідовно рендерить градієнт на stroke, але стабільно -- на fill
    (як у frame_ring_svg). error='h' дає корекцію до 30% -- запас під друк,
    скан і логотип у центрі (overlay в шаблоні). Розмір задається через CSS.
    """
    import segno
    matrix = list(segno.make(url, error='h').matrix)
    n = len(matrix)
    size = n + 2 * border

    # Заокруглені модулі зі злиттям: кут заокруглюється ЛИШЕ коли обидва
    # сусіди, що його утворюють, відсутні. Якщо поряд є модуль -- кут на стику
    # лишається прямим, тож сусідні модулі зливаються у суцільні лінії.
    rad = 0.5

    def filled(r, c):
        return 0 <= r < n and 0 <= c < len(matrix[r]) and matrix[r][c]

    def module(r, c):
        x, y = c + border, r + border
        up, down = not filled(r - 1, c), not filled(r + 1, c)
        left, right = not filled(r, c - 1), not filled(r, c + 1)
        tl = rad if up and left else 0
        tr = rad if up and right else 0
        br = rad if down and right else 0
        bl = rad if down and left else 0
        # Обхід контуру за годинниковою; дуга лише за ненульового радіуса.
        p = [f'M{x + tl:.2f},{y:.2f}', f'h{1 - tl - tr:.2f}']
        if tr:
            p.append(f'a{rad},{rad} 0 0 1 {rad},{rad}')
        p.append(f'v{1 - tr - br:.2f}')
        if br:
            p.append(f'a{rad},{rad} 0 0 1 -{rad},{rad}')
        p.append(f'h-{1 - br - bl:.2f}')
        if bl:
            p.append(f'a{rad},{rad} 0 0 1 -{rad},-{rad}')
        p.append(f'v-{1 - bl - tl:.2f}')
        if tl:
            p.append(f'a{rad},{rad} 0 0 1 {rad},-{rad}')
        p.append('z')
        return ''.join(p)

    squares = ''.join(
        module(r, c)
        for r, row in enumerate(matrix)
        for c, val in enumerate(row) if val
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'width="{size}" height="{size}">'
        # userSpaceOnUse + spreadMethod=pad: градієнт прив'язаний до всього
        # холста (0,0)->(size,size), а не до bounding box шляху. Інакше
        # WeasyPrint при objectBoundingBox дає зсув на 1-2px і протікання
        # помаранчевого (offset 0) тонкою смугою з протилежного краю.
        f'<defs><linearGradient id="qrGrad" gradientUnits="userSpaceOnUse" '
        f'x1="0" y1="0" x2="{size}" y2="{size}" spreadMethod="pad">'
        '<stop offset="0" stop-color="#f0a02a"/>'
        '<stop offset="0.5" stop-color="#b85a7e"/>'
        '<stop offset="1" stop-color="#7055a4"/>'
        '</linearGradient></defs>'
        f'<rect width="{size}" height="{size}" fill="#ffffff"/>'
        f'<path fill="url(#qrGrad)" d="{squares}"/>'
        '</svg>'
    )


def certificate_abs_path(certificate):
    """Абсолютний шлях до збереженого PDF.

    pdf_path зберігається у posix-форматі (прямі слеші), тож розбиваємо
    і збираємо через os.path.join для коректності на будь-якій ОС.
    """
    base = current_app.config['CERTIFICATE_FOLDER']
    return os.path.join(base, *certificate.pdf_path.split('/'))


def _meta_date(dt):
    """28 листопада 2025 р. (для мета-блоку). '' для None."""
    if not dt:
        return ''
    return f'{dt.day} {_UA_MONTHS[dt.month]} {dt.year} р.'


def _event_size_class(title):
    """Адаптивний CSS-клас розміру для назви заходу: довші назви -- дрібніший
    шрифт, щоб не переповнювати блок тіла (класи визначені у шаблоні)."""
    n = len(title or '')
    if n <= 38:
        return 'cert__event--xl'
    if n <= 70:
        return 'cert__event--lg'
    if n <= 110:
        return 'cert__event--md'
    if n <= 160:
        return 'cert__event--sm'
    return 'cert__event--xs'


# Родовий відмінок типу заходу для рядка "лектору(-ці) <тип>" на лекторському
# сертифікаті (напр. "тренінг" -> "тренінгу"). Невідомий тип -> як є.
_EVENT_TYPE_GENITIVE = {
    'семінар': 'семінару',
    'вебінар': 'вебінару',
    'курс': 'курсу',
    'майстер-клас': 'майстер-класу',
    'конференція': 'конференції',
    'конгрес': 'конгресу',
    'симпозіум': 'симпозіуму',
    'тренінг': 'тренінгу',
    'фахова школа': 'фахової школи',
    'фахову школу': 'фахової школи',
}


def event_type_genitive(label):
    """Родовий відмінок типу заходу для лекторського серта ('заходу' за умовч.)."""
    key = (label or '').strip().lower()
    if not key:
        return 'заходу'
    return _EVENT_TYPE_GENITIVE.get(key, key)


def resolve_signature(lecturer_name):
    """Знайти шлях до підпису тренера за ПІБ лектора (для adhoc-генерації).

    Спершу точний збіг повного імені (так лектор обирається з випадаючого
    списку в xlsx). Як запасний варіант -- збіг за прізвищем + ініціалами
    (напр. "Гусак В.С." -> "Гусак Валерія Сергіївна"). Повертає шлях або None.
    """
    name = (lecturer_name or '').strip()
    if not name:
        return None
    from app.models.trainer import Trainer
    exact = Trainer.query.filter(
        Trainer.signature.isnot(None), Trainer.full_name == name,
    ).first()
    if exact and exact.signature:
        return exact.signature.strip()
    tokens = [t for t in name.replace('.', ' ').split() if t]
    if not tokens:
        return None
    surname = tokens[0].lower()
    inits = [t[0].lower() for t in tokens[1:]]
    for t in Trainer.query.filter(Trainer.signature.isnot(None)).all():
        ftoks = t.full_name.split()
        if not ftoks or ftoks[0].lower() != surname:
            continue
        finits = [x[0].lower() for x in ftoks[1:]]
        if inits and finits[:len(inits)] == inits and t.signature:
            return t.signature.strip()
    return None


def render_certificate_html(certificate, kind='participant'):
    """Відрендерити HTML сертифіката для WeasyPrint.

    kind: 'participant' (учасник, за замовчуванням) або 'lecturer' (лектор --
    інший текст тіла, лише підпис Директора). Стиль/верстка спільні.

    Номери провайдера й заходу беремо із сегментів номера сертифіката
    (РРРР-ПППП-ЗЗЗЗЗЗЗ-УУУУУУ) -- працює і для БД-, і для adhoc-рендеру.
    """
    parts = (certificate.number or '').split('-')
    provider_number = parts[1] if len(parts) >= 2 else ''
    event_number = parts[2].lstrip('0') or parts[2] if len(parts) >= 3 else ''
    return render_template(
        'certificates/certificate.html',
        certificate=certificate,
        cert_kind=kind,
        issued_date=format_ua_date(certificate.issued_at),
        event_date=format_ua_date(certificate.event_date),
        event_date_short=(certificate.event_date.strftime('%d.%m.%Y')
                          if certificate.event_date else ''),
        meta_date=_meta_date(certificate.event_date),
        molecules_svg=molecular_svg(certificate.number),
        frame_svg=frame_ring_svg(),
        points_badge=points_badge_url(certificate.cpd_points),
        specialties=getattr(certificate, 'specialties', None),
        event_type=getattr(certificate, 'event_type_label', None),
        event_place=getattr(certificate, 'event_place', None),
        event_size_class=_event_size_class(certificate.event_title),
        lecturer_signature=(getattr(certificate, 'lecturer_signature', None)
                            or _DEFAULT_SIGNATURE),
        provider_number=provider_number,
        event_number=event_number,
        qr_svg=qr_svg(_site_url()),
        site_domain=_site_url().split('://')[-1].rstrip('/'),
    )


def render_pdf_bytes(certificate, font_config=None, kind='participant'):
    """Згенерувати PDF-байти сертифіката (без запису у файл).

    font_config -- спільний weasyprint FontConfiguration; передається у
    батч-генерації, щоб не перепарсювати шрифти на кожному сертифікаті.
    WeasyPrint імпортується ліниво (на машинах без GTK імпорт може падати).
    """
    from weasyprint import HTML  # noqa: WPS433 (ліниво)

    html = render_certificate_html(certificate, kind=kind)
    return HTML(string=html, base_url=current_app.static_folder).write_pdf(
        font_config=font_config,
    )


def render_adhoc_pdf(*, number, recipient_name, event_title, event_date=None,
                     cpd_points=None, lecturer_name=None, lecturer_signature=None,
                     specialties=None, event_type=None, event_place=None,
                     issued_at=None, font_config=None, kind='participant'):
    """Згенерувати PDF із довільних даних (без запису в БД).

    Використовується генератором сертифікатів з xlsx та для лекторського
    серта (kind='lecturer'). Передаємо легкий обʼєкт у той самий рендер.
    """
    from types import SimpleNamespace
    cert = SimpleNamespace(
        number=number,
        recipient_name=recipient_name,
        event_title=event_title,
        event_date=event_date,
        cpd_points=cpd_points,
        lecturer_name=lecturer_name,
        lecturer_signature=lecturer_signature,
        specialties=specialties,
        event_type_label=event_type,
        event_place=event_place,
        issued_at=issued_at or utcnow(),
    )
    return render_pdf_bytes(cert, font_config=font_config, kind=kind)


def _write_pdf(certificate):
    """Згенерувати PDF і записати у файл. Повертає абсолютний шлях."""
    pdf_bytes = render_pdf_bytes(certificate)
    abs_path = certificate_abs_path(certificate)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, 'wb') as fh:
        fh.write(pdf_bytes)
    logger.info('Certificate PDF written: %s (%d bytes)', abs_path, len(pdf_bytes))
    return abs_path


def regenerate_pdf(certificate):
    """Перегенерувати PDF для вже виданого сертифіката."""
    return _write_pdf(certificate)


def read_pdf_bytes(certificate):
    """Прочитати байти PDF; за відсутності файлу -- перегенерувати."""
    abs_path = certificate_abs_path(certificate)
    if not os.path.exists(abs_path):
        logger.warning('Certificate PDF missing, regenerating: %s', abs_path)
        regenerate_pdf(certificate)
    with open(abs_path, 'rb') as fh:
        return fh.read()


def issue_certificate(registration, issued_by=None):
    """Видати сертифікат для реєстрації (ідемпотентно).

    Якщо чинний сертифікат уже існує -- повертає його без змін.
    Створює запис, генерує PDF, зберігає файл. Повертає Certificate.
    """
    existing = registration.certificate
    if existing is not None and not existing.revoked:
        return existing

    (title, event_date, cpd, lecturer, signature, specialties,
     event_type, place) = _event_snapshot(registration)
    issued_at = utcnow()

    # Сегменти номера БПР: рік проведення, номер провайдера, номер заходу.
    from app.models.site_settings import SiteSettings
    instance = registration.instance
    course = instance.course if instance else None
    provider = (SiteSettings.get().bpr_provider_number or '').strip()
    event_num = (course.bpr_event_number or '').strip() if course and course.bpr_event_number else ''
    year = (event_date or issued_at).year
    if not provider:
        raise ValueError('Не задано реєстраційний номер провайдера БПР '
                         '(Адмінка -> Налаштування сайту).')
    if not event_num:
        raise ValueError('Не задано реєстраційний номер заходу БПР '
                         '(Адмінка -> Курс -> редагувати).')

    # Якщо є відкликаний сертифікат -- повторно використовуємо запис.
    cert = existing if existing is not None else Certificate(
        registration_id=registration.id,
    )
    cert.user_id = registration.user_id
    cert.recipient_name = registration.user.full_name
    cert.event_title = title
    cert.event_date = event_date
    cert.cpd_points = cpd
    cert.lecturer_name = lecturer
    cert.lecturer_signature = signature
    cert.specialties = specialties
    cert.event_type_label = event_type
    cert.event_place = place
    cert.issued_at = issued_at
    cert.issued_by_id = issued_by.id if issued_by else None
    cert.revoked = False
    cert.revoked_at = None

    # Номер + шлях. Retry на випадок гонки за унікальним номером.
    for attempt in range(5):
        number = Certificate.generate_number(year, provider, event_num)
        cert.number = number
        # posix-формат (прямі слеші) -- незалежно від ОС генерації.
        cert.pdf_path = f'{issued_at.year}/{number}.pdf'
        if existing is None and attempt == 0:
            db.session.add(cert)
        try:
            db.session.flush()
            break
        except IntegrityError:
            db.session.rollback()
            # Після rollback об'єкт від'єднано -- перечіплюємо у наступній ітерації.
            db.session.add(cert)
            logger.warning('Certificate number collision (%s), retrying', number)
    else:
        raise RuntimeError('Не вдалося згенерувати унікальний номер сертифіката')

    _write_pdf(cert)
    db.session.commit()
    logger.info(
        'Certificate %s issued for reg=%s by=%s',
        cert.number, registration.id, issued_by.email if issued_by else 'system',
    )
    return cert


# ---- Лекторський сертифікат ----
def issue_lecturer_certificate(instance, issued_by=None):
    """Видати (або повернути наявний) сертифікат лектора для проведення.

    Один запис на instance (повторна видача -> той самий номер). Дані -- знімки
    з курсу/проведення/тренера на момент видачі. Номер учасника у діапазоні
    1xxxxx (окремий лічильник). Тип заходу зберігаємо у родовому відмінку.
    """
    from app.models.site_settings import SiteSettings
    from app.models.lecturer_certificate import LecturerCertificate

    existing = LecturerCertificate.query.filter_by(instance_id=instance.id).first()
    if existing is not None:
        return existing

    course = instance.course
    trainer = instance.effective_trainer
    if trainer is None:
        raise ValueError('У проведення не задано лектора (тренера).')
    provider = (SiteSettings.get().bpr_provider_number or '').strip()
    event_num = (course.bpr_event_number or '').strip() if course and course.bpr_event_number else ''
    if not provider:
        raise ValueError('Не задано реєстраційний номер провайдера БПР '
                         '(Адмінка -> Налаштування сайту).')
    if not event_num:
        raise ValueError('Не задано реєстраційний номер заходу БПР '
                         '(Адмінка -> Курс -> редагувати).')
    points = course.bpr_lecturer_points if course else None
    if points is None:
        raise ValueError('Не задано бали БПР лектору '
                         '(Адмінка -> Курс -> редагувати).')

    issued_at = utcnow()
    event_date = instance.start_date
    year = (event_date or issued_at).year
    event_type = event_type_genitive(course.event_type_label) if course and course.event_type else None

    lc = LecturerCertificate(
        instance_id=instance.id,
        trainer_id=trainer.id,
        recipient_name=(trainer.full_name_dative or '').strip() or trainer.full_name,
        event_title=course.title if course else (instance.title or 'Захід'),
        event_date=event_date,
        cpd_points=points,
        specialties=(course.bpr_specialties or '').strip() if course and course.bpr_specialties else None,
        event_type_label=event_type,
        event_place=(instance.location or '').strip() or None,
        issued_at=issued_at,
        issued_by_id=issued_by.id if issued_by else None,
    )

    for attempt in range(5):
        lc.number = LecturerCertificate.generate_number(year, provider, event_num)
        if attempt == 0:
            db.session.add(lc)
        try:
            db.session.flush()
            break
        except IntegrityError:
            db.session.rollback()
            # instance_id-unique міг спрацювати, якщо паралельно вже створили.
            dup = LecturerCertificate.query.filter_by(instance_id=instance.id).first()
            if dup is not None:
                return dup
            db.session.add(lc)
            logger.warning('Lecturer cert number collision (%s), retrying', lc.number)
    else:
        raise RuntimeError('Не вдалося згенерувати унікальний номер серта лектора')

    db.session.commit()
    logger.info('Lecturer certificate %s issued for instance=%s by=%s',
                lc.number, instance.id, issued_by.email if issued_by else 'system')
    return lc


def render_lecturer_pdf(lecturer_cert, font_config=None):
    """PDF лекторського серта зі збереженого запису (рендер за знімками)."""
    return render_adhoc_pdf(
        kind='lecturer',
        number=lecturer_cert.number,
        recipient_name=lecturer_cert.recipient_name,
        event_title=lecturer_cert.event_title,
        event_date=lecturer_cert.event_date,
        cpd_points=lecturer_cert.cpd_points,
        specialties=lecturer_cert.specialties,
        event_type=lecturer_cert.event_type_label,
        event_place=lecturer_cert.event_place,
        issued_at=lecturer_cert.issued_at,
        font_config=font_config,
    )
