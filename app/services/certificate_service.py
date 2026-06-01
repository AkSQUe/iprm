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
    return title, event_date, cpd, lecturer


_POINTS_BADGE_DIR = ('images', 'certificates')
_POINTS_BADGE_DEFAULT = 10


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


def certificate_abs_path(certificate):
    """Абсолютний шлях до збереженого PDF.

    pdf_path зберігається у posix-форматі (прямі слеші), тож розбиваємо
    і збираємо через os.path.join для коректності на будь-якій ОС.
    """
    base = current_app.config['CERTIFICATE_FOLDER']
    return os.path.join(base, *certificate.pdf_path.split('/'))


def render_certificate_html(certificate):
    """Відрендерити HTML сертифіката для WeasyPrint."""
    return render_template(
        'certificates/certificate.html',
        certificate=certificate,
        issued_date=format_ua_date(certificate.issued_at),
        event_date=format_ua_date(certificate.event_date),
        molecules_svg=molecular_svg(certificate.number),
        frame_svg=frame_ring_svg(),
        points_badge=points_badge_url(certificate.cpd_points),
    )


def _write_pdf(certificate):
    """Згенерувати PDF і записати у файл. Повертає абсолютний шлях.

    WeasyPrint імпортується ліниво: на машинах без нативних GTK-бібліотек
    імпорт може падати, і ми хочемо, щоб решта застосунку працювала.
    """
    from weasyprint import HTML  # noqa: WPS433 (ліниво)

    html = render_certificate_html(certificate)
    pdf_bytes = HTML(
        string=html,
        base_url=current_app.static_folder,
    ).write_pdf()

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

    title, event_date, cpd, lecturer = _event_snapshot(registration)
    issued_at = utcnow()

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
    cert.issued_at = issued_at
    cert.issued_by_id = issued_by.id if issued_by else None
    cert.revoked = False
    cert.revoked_at = None

    # Номер + шлях. Retry на випадок гонки за унікальним номером.
    for attempt in range(5):
        number = Certificate.generate_number(issued_at)
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
