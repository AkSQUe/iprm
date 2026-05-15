"""XLSX export/import для адмінки: курси (з program_blocks + faq) і
проведення курсів (CourseInstance).

Загальний контракт:
  - Експорт повертає `io.BytesIO` з готовим xlsx, який віддається через
    `send_file` в роуті.
  - Імпорт працює у дві стадії:
      1. `parse_*_xlsx(file_path) -> ImportPlan` -- read + validate, БЕЗ
         запису в БД. Якщо є помилки, plan.errors заповнений; apply
         відмовляється виконувати.
      2. `apply_*_plan(plan) -> ApplyResult` -- atomic commit. Усе або
         нічого.
  - Тимчасовий xlsx-файл під час preview зберігається у
    `instance/xlsx_imports/{token}.xlsx`, де token = uuid4. Apply
    видаляє файл після успіху.

Дизайн-рішення (узгоджено з admin-користувачем):
  - Рядки, що є в БД, але відсутні у xlsx, -> залишаємо без змін.
  - program_blocks та faq для course_slug, який присутній у відповідній
    sheet, ПОВНІСТЮ замінюються (REPLACE). Якщо course_slug не зустрі-
    чається у sheet -> блоки/FAQ цього курсу не чіпаємо.
  - Trainer-FK у xlsx подається як trainer_slug (human-readable).
"""
from __future__ import annotations

import io
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from flask import current_app
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.program_block import ProgramBlock
from app.models.trainer import Trainer

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Загальні константи / утиліти
# ----------------------------------------------------------------------

KYIV = timezone(timedelta(hours=3))  # UTC+3

HEADER_FILL = PatternFill('solid', fgColor='4F46E5')
HEADER_FONT = Font(color='FFFFFF', bold=True)
WRAP = Alignment(wrap_text=True, vertical='top')

# ----- Number formats ------------------------------------------------
# Дроблені формати для різних типів даних. Use cell.number_format = ...
FMT_INT = '0'
FMT_CURRENCY_UAH = '#,##0 "₴"'
FMT_DATETIME = 'YYYY-MM-DD HH:MM'

# Per-key number_format мапа. Якщо ключ відсутній — формат не виставляємо
# (текстовий за замовчуванням).
NUMBER_FORMATS = {
    # Courses
    'id': FMT_INT,
    'base_price': FMT_CURRENCY_UAH,
    'cpd_points': FMT_INT,
    'max_participants': FMT_INT,
    # Instances
    'price': FMT_CURRENCY_UAH,
    'start_date': FMT_DATETIME,
    'end_date': FMT_DATETIME,
    # Program blocks
    'sort_order': FMT_INT,
}

# ----- Color fills для enum-полів ------------------------------------
def _fill(hex_color: str) -> PatternFill:
    return PatternFill('solid', fgColor=hex_color)

EVENT_TYPE_FILLS = {
    'course': _fill('DBEAFE'),       # blue-100
    'seminar': _fill('FED7AA'),      # orange-200
    'webinar': _fill('D1FAE5'),      # green-100 (для онлайн-формату)
    'masterclass': _fill('E9D5FF'),  # purple-200
    'conference': _fill('FEF3C7'),   # yellow-100
}

EVENT_FORMAT_FILLS = {
    'online': _fill('DBEAFE'),       # blue
    'offline': _fill('D1FAE5'),      # green
    'hybrid': _fill('E9D5FF'),       # purple
}

STATUS_FILLS = {
    'draft': _fill('F3F4F6'),        # gray
    'published': _fill('DBEAFE'),    # blue
    'active': _fill('D1FAE5'),       # green
    'completed': _fill('A7F3D0'),    # darker green
    'cancelled': _fill('FECACA'),    # red
}

BOOL_TRUE_FILL = _fill('D1FAE5')     # light green
BOOL_FALSE_FILL = _fill('FEE2E2')    # light red

# Ledь-помітна зебра для непарних data-рядків. Робимо її вручну (а не
# через Excel TableStyle), бо вбудовані стилі дають занадто помітне
# банінг -- ledь-помітної опції серед них нема.
ZEBRA_FILL = _fill('FAFAFA')

# ----- Column widths (ширина = "шт. символів"). ----------------------
# Дають xlsx-у форму "зручний для перегляду", не "ALL DEFAULT 14".
COURSE_WIDTHS = {
    'id': 6,
    'slug': 32,
    'title': 55,
    'subtitle': 40,
    'short_description': 50,
    'description': 60,
    'event_type': 16,
    'base_price': 14,
    'cpd_points': 10,
    'max_participants': 12,
    'trainer_slug': 24,
    'hero_image': 50,
    'card_image': 50,
    'speaker_info': 40,
    'agenda': 40,
    'target_audience': 50,
    'tags': 28,
    'is_active': 12,
    'is_featured': 14,
}

INSTANCE_WIDTHS = {
    'id': 6,
    'course_slug': 32,
    'start_date': 22,
    'end_date': 22,
    'event_format': 14,
    'price': 14,
    'cpd_points': 10,
    'max_participants': 12,
    'trainer_slug': 24,
    'location': 18,
    'online_link': 40,
    'status': 14,
}

PROGRAM_WIDTHS = {
    'course_slug': 32,
    'sort_order': 10,
    'heading': 40,
    'items': 70,
}

FAQ_WIDTHS = {
    'course_slug': 32,
    'question': 50,
    'answer': 70,
}

TRAINER_WIDTHS = {'slug': 28, 'full_name': 36, 'role': 50}

VALID_EVENT_TYPES = {t[0] for t in Course.EVENT_TYPES}
VALID_FORMATS = {t[0] for t in CourseInstance.FORMATS}
VALID_STATUSES = {t[0] for t in CourseInstance.STATUSES}

# key -> Ukrainian label (для відображення в xlsx).
EVENT_TYPE_LABEL = dict(Course.EVENT_TYPES)
EVENT_TYPE_KEY_BY_LABEL = {v: k for k, v in EVENT_TYPE_LABEL.items()}

FORMAT_LABEL = dict(CourseInstance.FORMATS)  # 'online' -> 'Онлайн' тощо
FORMAT_KEY_BY_LABEL = {v: k for k, v in FORMAT_LABEL.items()}

STATUS_LABEL = dict(CourseInstance.STATUSES)  # 'draft' -> 'Чернетка' тощо
STATUS_KEY_BY_LABEL = {v: k for k, v in STATUS_LABEL.items()}


def _import_dir() -> Path:
    """instance/xlsx_imports -- лежить поза static, недоступне з вебу."""
    inst = Path(current_app.instance_path)
    target = inst / 'xlsx_imports'
    target.mkdir(parents=True, exist_ok=True)
    return target


def save_uploaded_xlsx(file_storage) -> str:
    """Зберегти upload з UI у тимчасову директорію, повернути token."""
    token = uuid.uuid4().hex
    path = _import_dir() / f'{token}.xlsx'
    file_storage.save(str(path))
    return token


def get_uploaded_path(token: str) -> Path | None:
    """Знайти збережений файл за token. Захист від path traversal."""
    if not token.isalnum() or len(token) != 32:
        return None
    p = _import_dir() / f'{token}.xlsx'
    return p if p.is_file() else None


def cleanup_upload(token: str) -> None:
    p = get_uploaded_path(token)
    if p is not None:
        try:
            p.unlink()
        except OSError:
            logger.exception('Failed to remove temp xlsx %s', p)


def cleanup_stale_xlsx_uploads(max_age_minutes: int = 30) -> int:
    """Видалити завантажені для preview xlsx-файли, старші за `max_age_minutes`.

    Викликається з APScheduler-job-у. Повертає кількість видалених файлів
    (для логування).
    """
    target = _import_dir()
    cutoff = datetime.now().timestamp() - max_age_minutes * 60
    removed = 0
    for p in target.glob('*.xlsx'):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
        except OSError:
            logger.exception('Failed to inspect/remove stale xlsx %s', p)
    if removed:
        logger.info('Cleaned up %d stale xlsx upload(s)', removed)
    return removed


def _style_header(ws, columns: list[str], labels: dict[str, str] | None = None) -> None:
    """Записати заголовки (без виставлення ширин — ширини окремо через
    `_set_column_widths`, бо вони залежать від типу контенту).
    """
    for col_idx, key in enumerate(columns, start=1):
        display = labels.get(key, key) if labels else key
        cell = ws.cell(row=1, column=col_idx, value=display)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical='center', horizontal='left')
    ws.freeze_panes = 'A2'
    # Висота header-рядка для зручності
    ws.row_dimensions[1].height = 22


def _set_column_widths(ws, columns: list[str], widths: dict[str, int]) -> None:
    """Виставити ширину кожної колонки за мапою `widths`. Якщо ключа немає,
    використовуємо дефолт 14."""
    for col_idx, key in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = widths.get(key, 14)


def _apply_number_formats(ws, columns: list[str], last_row: int) -> None:
    """Призначити number_format на кожну колонку (одразу на всі дата-клітинки
    від рядка 2 до last_row), якщо key є в NUMBER_FORMATS."""
    if last_row < 2:
        return
    for col_idx, key in enumerate(columns, start=1):
        fmt = NUMBER_FORMATS.get(key)
        if not fmt:
            continue
        for r in range(2, last_row + 1):
            ws.cell(row=r, column=col_idx).number_format = fmt


def _apply_table_style(ws, columns: list[str], table_name: str, last_data_row: int) -> None:
    """Перетворити діапазон A1:<last_col><last_data_row> на Excel-Table.

    Дає авто-фільтри в заголовку + іменований range. Зебру самі малюємо
    через `_apply_zebra` (бо вбудоване Excel-банінг -- надто помітне).
    """
    if last_data_row < 2:
        return
    last_col = get_column_letter(len(columns))
    ref = f'A1:{last_col}{last_data_row}'
    table = Table(displayName=table_name, ref=ref)
    table.tableStyleInfo = TableStyleInfo(
        name='TableStyleLight1',   # майже-білий, без сильних кольорів
        showFirstColumn=False,
        showLastColumn=False,
        showRowStripes=False,      # ВЛАСНА зебра нижче
        showColumnStripes=False,
    )
    ws.add_table(table)


def _apply_zebra(ws, n_cols: int, first_data_row: int, last_data_row: int) -> None:
    """Заповнити кожен 2-й data-рядок ledь-помітним сірим. Викликати
    ПЕРЕД призначенням enum-fills, щоб кольорові клітинки (event_type,
    status, is_active, ...) перекривали zebra-fill своїм кольором.
    """
    if last_data_row < first_data_row:
        return
    # Колір на другому, четвертому, шостому data-рядку
    # (visually -- стовпчик `1st row=white, 2nd row=gray, 3rd=white...`).
    for row in range(first_data_row + 1, last_data_row + 1, 2):
        for col in range(1, n_cols + 1):
            ws.cell(row, col).fill = ZEBRA_FILL


def _to_kyiv_naive(dt):
    """Зняти TZ, попередньо переконвертувавши в Київ. openpyxl попереджує
    про tz-aware datetimes; у клітинці маємо bare datetime, який Excel
    розуміє як «локальний час»."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(KYIV).replace(tzinfo=None)
    return dt


def _str(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _to_lines(value: list | None) -> str:
    """JSON list -> текст по 1 елементу на рядок."""
    if not value:
        return ''
    return '\n'.join(str(x) for x in value)


def _from_lines(value: str | None) -> list[str]:
    if not value:
        return []
    return [line.strip() for line in str(value).splitlines() if line.strip()]


def _bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    s = str(v).strip().lower()
    return s in {'true', 'yes', 'y', '1', 'так', 'true ', 'TRUE'.lower()}


def _decimal(v) -> Decimal | None:
    if v is None or v == '':
        return None
    try:
        return Decimal(str(v).replace(' ', '').replace(',', '.'))
    except (InvalidOperation, ValueError):
        raise ValueError(f'не число: {v!r}')


def _int(v) -> int | None:
    if v is None or v == '':
        return None
    try:
        return int(float(str(v).replace(' ', '').replace(',', '.')))
    except (TypeError, ValueError):
        raise ValueError(f'не ціле число: {v!r}')


def _dt(v) -> datetime | None:
    """Прийняти або datetime (openpyxl auto-parses), або ISO-рядок."""
    if v is None or v == '':
        return None
    if isinstance(v, datetime):
        dt = v
    else:
        try:
            dt = datetime.fromisoformat(str(v))
        except ValueError:
            raise ValueError(f'неможливо розпарсити дату: {v!r}')
    if dt.tzinfo is None:
        # припускаємо Київ (UTC+3), щоб збігалось з seed-розкладом
        dt = dt.replace(tzinfo=KYIV)
    return dt


# ======================================================================
# COURSES
# ======================================================================

COURSE_COLS = [
    'id', 'slug', 'title', 'subtitle', 'short_description', 'description',
    'event_type', 'base_price', 'cpd_points', 'max_participants',
    'trainer_slug', 'hero_image', 'card_image', 'speaker_info', 'agenda',
    'target_audience', 'tags', 'is_active', 'is_featured',
]

# Українські назви колонок для заголовків xlsx. Імпорт приймає обидва
# варіанти (англ. internal key АБО українську підпис) -- це гарантує
# що файли, експортовані раніше зі старими заголовками, ще можна
# завантажувати.
COURSE_LABELS = {
    'id': 'ID',
    'slug': 'Slug (URL)',
    'title': 'Назва',
    'subtitle': 'Підзаголовок',
    'short_description': 'Короткий опис',
    'description': 'Повний опис',
    'event_type': 'Тип',
    'base_price': 'Ціна (грн)',
    'cpd_points': 'Бали БПР',
    'max_participants': 'Макс. учасників',
    'trainer_slug': 'Тренер',
    'hero_image': 'Hero-зображення',
    'card_image': 'Зображення картки',
    'speaker_info': 'Інфо про спікера',
    'agenda': 'Програма (опис)',
    'target_audience': 'Цільова аудиторія',
    'tags': 'Теги',
    'is_active': 'Активний',
    'is_featured': 'Рекомендований',
}

PROGRAM_COLS = ['course_slug', 'sort_order', 'heading', 'items']
PROGRAM_LABELS = {
    'course_slug': 'Курс (slug)',
    'sort_order': 'Порядок',
    'heading': 'Заголовок',
    'items': 'Пункти',
}

FAQ_COLS = ['course_slug', 'question', 'answer']
FAQ_LABELS = {
    'course_slug': 'Курс (slug)',
    'question': 'Запитання',
    'answer': 'Відповідь',
}

# Назви sheet-ів. Експортуємо в українській, парсинг приймає обидва.
SHEET_ALIASES = {
    'courses': ['Курси', 'Courses'],
    'program_blocks': ['Блоки програми', 'Program blocks'],
    'faq': ['FAQ'],
    'instances': ['Розклад', 'Instances'],
}


def _find_sheet(wb, key: str):
    """Знайти sheet за будь-яким з прийнятних псевдонімів."""
    for name in SHEET_ALIASES.get(key, []):
        if name in wb.sheetnames:
            return wb[name]
    return None


# Кількість рядків, на які поширюється data-validation drop-down у
# колонці trainer_slug. Менеджер може дописувати нові рядки знизу --
# валідація все одно покриватиме. 500 з запасом.
_DROPDOWN_BUFFER_ROWS = 500
_TRAINERS_SHEET_NAME = 'Тренери'


def _add_trainers_sheet(wb) -> int:
    """Додати reference-sheet з активними тренерами. ПІБ йде в колонці A,
    щоб саме воно потрапляло у drop-down тренерів. Slug -- у колонці B
    (для довідки). Повертає номер останнього рядка з даними."""
    ws = wb.create_sheet(_TRAINERS_SHEET_NAME)
    cols = ['full_name', 'slug', 'role']
    _style_header(
        ws,
        cols,
        {'full_name': 'ПІБ (значення)', 'slug': 'Slug', 'role': 'Посада'},
    )

    trainers = (
        Trainer.query.filter_by(is_active=True)
        .order_by(Trainer.full_name)
        .all()
    )
    for row_idx, t in enumerate(trainers, start=2):
        ws.cell(row=row_idx, column=1, value=t.full_name).alignment = WRAP
        ws.cell(row=row_idx, column=2, value=t.slug)
        ws.cell(row=row_idx, column=3, value=t.role or '').alignment = WRAP

    widths = {'full_name': 36, 'slug': 28, 'role': 50}
    _set_column_widths(ws, cols, widths)
    _apply_zebra(ws, len(cols), first_data_row=2, last_data_row=1 + len(trainers))
    _apply_table_style(ws, cols, 'tblTrainers', last_data_row=1 + len(trainers))
    return 1 + len(trainers)


def _add_inline_dropdown(ws, column_key: str, columns: list[str],
                         options: list[str], last_data_row: int,
                         title: str = '', hint: str = '') -> None:
    """Прикріпити drop-down зі статичним списком значень.

    Використовується для невеликих enum-полів (event_type, формат, статус).
    Excel-обмеження inline-list у formula1 -- 255 символів; для довших
    списків потрібен окремий sheet з reference-значеннями.
    """
    if not options:
        return
    col_letter = get_column_letter(columns.index(column_key) + 1)
    # Inline-list у formula1 має бути обгорнутий лапками й розділений комами.
    formula = '"' + ','.join(options) + '"'
    dv = DataValidation(
        type='list',
        formula1=formula,
        allow_blank=False,
        showDropDown=False,  # False у XML = ПОКАЗУВАТИ стрілочку
        errorStyle='stop',
        error=f'Оберіть значення зі списку: {", ".join(options)}',
        errorTitle='Невалідне значення',
        prompt=hint,
        promptTitle=title,
    )
    final_row = max(last_data_row, 1) + _DROPDOWN_BUFFER_ROWS
    dv.add(f'{col_letter}2:{col_letter}{final_row}')
    ws.add_data_validation(dv)


def _add_trainer_dropdown(ws, column_key: str, columns: list[str],
                          last_data_row: int, trainers_last_row: int) -> None:
    """Прикріпити data-validation drop-down з тренерами до вказаної
    колонки. range покриває існуючі рядки + буфер для додавання нових.
    """
    if trainers_last_row < 2:  # порожній список тренерів
        return
    col_letter = get_column_letter(columns.index(column_key) + 1)
    formula = f"={_TRAINERS_SHEET_NAME}!$A$2:$A${trainers_last_row}"
    dv = DataValidation(
        type='list',
        formula1=formula,
        allow_blank=True,
        # showDropDown у OOXML інвертоване: False = ПОКАЗУВАТИ стрілочку
        showDropDown=False,
        errorStyle='warning',
        error='Тренер з таким slug відсутній у sheet "Тренери".',
        errorTitle='Невідомий тренер',
        prompt='Оберіть тренера зі списку (натисніть стрілочку)',
        promptTitle='Тренер',
    )
    final_row = max(last_data_row, 1) + _DROPDOWN_BUFFER_ROWS
    dv.add(f'{col_letter}2:{col_letter}{final_row}')
    ws.add_data_validation(dv)


@dataclass
class CourseChange:
    slug: str
    action: str  # 'create' | 'update' | 'unchanged' | 'error'
    fields_changed: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class CoursesImportPlan:
    courses: list[dict] = field(default_factory=list)   # parsed rows
    program_blocks: dict[str, list[dict]] = field(default_factory=dict)  # slug -> list
    faq: dict[str, list[dict]] = field(default_factory=dict)
    changes: list[CourseChange] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # slug в файлі (для оцінки яких program_blocks/faq REPLACE)
    program_slugs_in_file: set[str] = field(default_factory=set)
    faq_slugs_in_file: set[str] = field(default_factory=set)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    @property
    def counts(self) -> dict[str, int]:
        c = {'create': 0, 'update': 0, 'unchanged': 0, 'error': 0}
        for ch in self.changes:
            c[ch.action] = c.get(ch.action, 0) + 1
        return c


def export_courses_xlsx(active: str = 'all') -> io.BytesIO:
    """Згенерувати xlsx з 3 sheet: Courses / Program blocks / FAQ.

    Параметри:
      active: 'all' | 'true' | 'false' -- фільтр за полем is_active.
              Дефолтно 'all' (історична поведінка -- усі курси).
    """
    wb = Workbook()
    ws = wb.active
    ws.title = 'Курси'
    _style_header(ws, COURSE_COLS, COURSE_LABELS)

    # Тренер у клітинці — ПІБ (Ukrainian). На імпорті повертаємо в slug.
    trainer_name_by_id = {t.id: t.full_name for t in Trainer.query.all()}

    q = Course.query.order_by(Course.id)
    if active == 'true':
        q = q.filter(Course.is_active.is_(True))
    elif active == 'false':
        q = q.filter(Course.is_active.is_(False))
    courses = q.all()
    for row_idx, c in enumerate(courses, start=2):
        values = [
            c.id,
            c.slug,
            c.title or '',
            c.subtitle or '',
            c.short_description or '',
            c.description or '',
            EVENT_TYPE_LABEL.get(c.event_type, c.event_type or ''),
            float(c.base_price) if c.base_price is not None else 0,
            c.cpd_points,
            c.max_participants,
            trainer_name_by_id.get(c.trainer_id, '') if c.trainer_id else '',
            c.hero_image or '',
            c.card_image or '',
            c.speaker_info or '',
            c.agenda or '',
            _to_lines(c.target_audience),
            _to_lines(c.tags),
            bool(c.is_active),
            bool(c.is_featured),
        ]
        for col_idx, v in enumerate(values, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=v)
            cell.alignment = WRAP

    courses_last_row = ws.max_row

    # ЗЕБРА перед enum-кольорами, щоб enum-fills перекрили її на своїх клітинках.
    _apply_zebra(ws, len(COURSE_COLS), first_data_row=2, last_data_row=courses_last_row)

    # ----- Кольори за значенням -----------------------------------------
    et_col = COURSE_COLS.index('event_type') + 1
    ia_col = COURSE_COLS.index('is_active') + 1
    if_col = COURSE_COLS.index('is_featured') + 1
    for row_idx, c in enumerate(courses, start=2):
        if c.event_type and c.event_type in EVENT_TYPE_FILLS:
            ws.cell(row=row_idx, column=et_col).fill = EVENT_TYPE_FILLS[c.event_type]
        ws.cell(row=row_idx, column=ia_col).fill = (
            BOOL_TRUE_FILL if c.is_active else BOOL_FALSE_FILL
        )
        if c.is_featured:
            ws.cell(row=row_idx, column=if_col).fill = BOOL_TRUE_FILL

    _set_column_widths(ws, COURSE_COLS, COURSE_WIDTHS)
    _apply_number_formats(ws, COURSE_COLS, courses_last_row)

    # Program blocks
    ws_p = wb.create_sheet('Блоки програми')
    _style_header(ws_p, PROGRAM_COLS, PROGRAM_LABELS)
    row_idx = 2
    for c in courses:
        for b in sorted(c.program_blocks, key=lambda x: x.sort_order or 0):
            ws_p.cell(row=row_idx, column=1, value=c.slug)
            ws_p.cell(row=row_idx, column=2, value=b.sort_order or 0)
            ws_p.cell(row=row_idx, column=3, value=b.heading or '').alignment = WRAP
            ws_p.cell(row=row_idx, column=4, value=_to_lines(b.items)).alignment = WRAP
            row_idx += 1
    program_last_row = ws_p.max_row
    _apply_zebra(ws_p, len(PROGRAM_COLS), first_data_row=2, last_data_row=program_last_row)
    _set_column_widths(ws_p, PROGRAM_COLS, PROGRAM_WIDTHS)
    _apply_number_formats(ws_p, PROGRAM_COLS, program_last_row)

    # FAQ
    ws_f = wb.create_sheet('FAQ')
    _style_header(ws_f, FAQ_COLS, FAQ_LABELS)
    row_idx = 2
    for c in courses:
        for item in (c.faq or []):
            if not isinstance(item, dict):
                continue
            ws_f.cell(row=row_idx, column=1, value=c.slug)
            ws_f.cell(row=row_idx, column=2, value=item.get('question') or '').alignment = WRAP
            ws_f.cell(row=row_idx, column=3, value=item.get('answer') or '').alignment = WRAP
            row_idx += 1
    faq_last_row = ws_f.max_row
    _apply_zebra(ws_f, len(FAQ_COLS), first_data_row=2, last_data_row=faq_last_row)
    _set_column_widths(ws_f, FAQ_COLS, FAQ_WIDTHS)

    # Reference sheet з тренерами (вже з Table) + drop-down у колонці trainer_slug.
    trainers_last_row = _add_trainers_sheet(wb)
    _add_trainer_dropdown(
        ws, 'trainer_slug', COURSE_COLS,
        last_data_row=courses_last_row,
        trainers_last_row=trainers_last_row,
    )

    # Drop-down для типу заходу.
    _add_inline_dropdown(
        ws, 'event_type', COURSE_COLS,
        options=[label for _key, label in Course.EVENT_TYPES],
        last_data_row=courses_last_row,
        title='Тип заходу',
        hint='Оберіть зі списку: Семінар, Вебінар, Курс, Майстер-клас, Конференція',
    )

    # Excel Tables (forматовані з зеброю + auto-filter).
    _apply_table_style(ws, COURSE_COLS, 'tblCourses', courses_last_row)
    _apply_table_style(ws_p, PROGRAM_COLS, 'tblProgramBlocks', program_last_row)
    _apply_table_style(ws_f, FAQ_COLS, 'tblFAQ', faq_last_row)

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out


def _read_sheet(ws, columns: list[str], labels: dict[str, str] | None = None) -> list[dict]:
    """Прочитати sheet у list[dict].

    Заголовки приймаються або як internal key (англ., 'slug'), або як
    українські labels (з `labels`), для зворотньої сумісності зі старими
    xlsx-файлами.
    """
    if ws.max_row < 2:
        return []
    header = [c.value for c in ws[1]]

    # accepted: будь-яка валідна назва заголовка -> internal key
    accepted: dict[str, str] = {}
    for key in columns:
        accepted[key] = key
        accepted[key.lower()] = key
        if labels and key in labels:
            ua = labels[key]
            accepted[ua] = key
            accepted[ua.lower()] = key

    col_idx: dict[str, int] = {}
    for i, hv in enumerate(header):
        if hv is None:
            continue
        key = accepted.get(str(hv).strip()) or accepted.get(str(hv).strip().lower())
        if key:
            col_idx[key] = i + 1

    missing = [c for c in columns if c not in col_idx]
    if missing:
        pretty = [(labels.get(k, k) if labels else k) for k in missing]
        raise ValueError(
            f'Sheet "{ws.title}": бракує колонок: {", ".join(pretty)}'
        )

    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not any(v is not None and str(v).strip() for v in row):
            continue  # повністю порожній рядок
        d = {name: row[col_idx[name] - 1] for name in columns}
        rows.append(d)
    return rows


def parse_courses_xlsx(path: Path) -> CoursesImportPlan:
    plan = CoursesImportPlan()
    try:
        wb = load_workbook(filename=str(path), read_only=False, data_only=True)
    except Exception as exc:
        plan.errors.append(f'Не вдалося відкрити xlsx: {exc}')
        return plan

    # ---- Courses sheet ----
    ws_c = _find_sheet(wb, 'courses')
    if ws_c is None:
        plan.errors.append('Відсутній sheet "Курси"')
        return plan

    try:
        rows = _read_sheet(ws_c, COURSE_COLS, COURSE_LABELS)
    except ValueError as exc:
        plan.errors.append(str(exc))
        return plan

    _all_trainers = Trainer.query.all()
    trainer_id_by_slug = {t.slug: t.id for t in _all_trainers}
    trainer_id_by_name = {t.full_name: t.id for t in _all_trainers}
    existing_by_id = {c.id: c for c in Course.query.all()}
    existing_by_slug = {c.slug: c for c in existing_by_id.values()}

    seen_slugs = set()
    for line_no, raw in enumerate(rows, start=2):
        try:
            slug = _str(raw.get('slug'))
            if not slug:
                raise ValueError('порожній slug')
            if slug in seen_slugs:
                raise ValueError(f'дублюючий slug у файлі: {slug!r}')
            seen_slugs.add(slug)

            event_type_raw = _str(raw.get('event_type')) or 'course'
            # Приймаємо і англ. internal key ('course'), і українську назву
            # з drop-down ('Курс'). Нормалізуємо у key.
            event_type = EVENT_TYPE_KEY_BY_LABEL.get(event_type_raw, event_type_raw)
            if event_type not in VALID_EVENT_TYPES:
                allowed = sorted(VALID_EVENT_TYPES) + sorted(EVENT_TYPE_KEY_BY_LABEL.keys())
                raise ValueError(
                    f'event_type={event_type_raw!r} -- допустимі: {allowed}'
                )

            # Колонка "Тренер" може містити або slug (старі файли), або ПІБ
            # (новий експорт + drop-down). Спершу шукаємо за slug, потім за
            # full_name -- так покриваємо обидва формати.
            trainer_raw = _str(raw.get('trainer_slug'))
            trainer_id = None
            if trainer_raw:
                trainer_id = (
                    trainer_id_by_slug.get(trainer_raw)
                    or trainer_id_by_name.get(trainer_raw)
                )
                if trainer_id is None:
                    raise ValueError(
                        f'тренера {trainer_raw!r} не знайдено '
                        f'(ні за slug, ні за ПІБ)'
                    )

            parsed = {
                'id': _int(raw.get('id')),
                'slug': slug,
                'title': _str(raw.get('title')) or '',
                'subtitle': _str(raw.get('subtitle')),
                'short_description': _str(raw.get('short_description')),
                'description': _str(raw.get('description')),
                'event_type': event_type,
                'base_price': _decimal(raw.get('base_price')) or Decimal(0),
                'cpd_points': _int(raw.get('cpd_points')),
                'max_participants': _int(raw.get('max_participants')),
                'trainer_id': trainer_id,
                'hero_image': _str(raw.get('hero_image')),
                'card_image': _str(raw.get('card_image')),
                'speaker_info': _str(raw.get('speaker_info')),
                'agenda': _str(raw.get('agenda')),
                'target_audience': _from_lines(raw.get('target_audience')),
                'tags': _from_lines(raw.get('tags')),
                'is_active': _bool(raw.get('is_active')),
                'is_featured': _bool(raw.get('is_featured')),
            }

            if not parsed['title']:
                raise ValueError('порожній title')
            if parsed['base_price'] < 0:
                raise ValueError('base_price < 0')

            # знайти існуючий: id має пріоритет, потім slug
            existing = None
            if parsed['id'] is not None:
                existing = existing_by_id.get(parsed['id'])
                if existing is None:
                    raise ValueError(
                        f'id={parsed["id"]} не існує в БД '
                        f'(використайте порожній id для нового курсу)'
                    )
                if existing.slug != slug and slug in existing_by_slug:
                    raise ValueError(
                        f'slug={slug!r} вже зайнятий іншим курсом'
                    )
            else:
                existing = existing_by_slug.get(slug)

            plan.courses.append({'parsed': parsed, 'existing_id': existing.id if existing else None})

            if existing is None:
                plan.changes.append(CourseChange(slug=slug, action='create'))
            else:
                diff = _diff_course(existing, parsed, trainer_id_by_slug)
                if diff:
                    plan.changes.append(CourseChange(
                        slug=slug, action='update', fields_changed=diff,
                    ))
                else:
                    plan.changes.append(CourseChange(slug=slug, action='unchanged'))
        except Exception as exc:
            plan.errors.append(f'Рядок {line_no} (Courses): {exc}')
            plan.changes.append(CourseChange(
                slug=_str(raw.get('slug')) or f'#{line_no}',
                action='error',
                error=str(exc),
            ))

    # ---- Program blocks sheet ----
    ws_p = _find_sheet(wb, 'program_blocks')
    if ws_p is not None:
        try:
            p_rows = _read_sheet(ws_p, PROGRAM_COLS, PROGRAM_LABELS)
        except ValueError as exc:
            plan.errors.append(str(exc))
            p_rows = []
        for line_no, raw in enumerate(p_rows, start=2):
            try:
                slug = _str(raw.get('course_slug'))
                if not slug:
                    raise ValueError('порожній course_slug')
                heading = _str(raw.get('heading'))
                if not heading:
                    raise ValueError('порожній heading')
                sort_order = _int(raw.get('sort_order')) or 0
                items = _from_lines(raw.get('items'))
                plan.program_blocks.setdefault(slug, []).append({
                    'sort_order': sort_order,
                    'heading': heading,
                    'items': items,
                })
                plan.program_slugs_in_file.add(slug)
            except Exception as exc:
                plan.errors.append(f'Рядок {line_no} (Program blocks): {exc}')

    # ---- FAQ sheet ----
    ws_f = _find_sheet(wb, 'faq')
    if ws_f is not None:
        try:
            f_rows = _read_sheet(ws_f, FAQ_COLS, FAQ_LABELS)
        except ValueError as exc:
            plan.errors.append(str(exc))
            f_rows = []
        for line_no, raw in enumerate(f_rows, start=2):
            try:
                slug = _str(raw.get('course_slug'))
                if not slug:
                    raise ValueError('порожній course_slug')
                question = _str(raw.get('question'))
                if not question:
                    raise ValueError('порожнє question')
                answer = _str(raw.get('answer'))
                plan.faq.setdefault(slug, []).append({
                    'question': question, 'answer': answer or '',
                })
                plan.faq_slugs_in_file.add(slug)
            except Exception as exc:
                plan.errors.append(f'Рядок {line_no} (FAQ): {exc}')

    # перевірити, що course_slug у program/faq sheets існує у Courses
    # sheet або в БД (програмні блоки не повинні висіти без курсу)
    db_slugs = set(existing_by_slug.keys())
    file_slugs = {c['parsed']['slug'] for c in plan.courses}
    all_known = db_slugs | file_slugs
    for slug in plan.program_slugs_in_file:
        if slug not in all_known:
            plan.errors.append(
                f'Program blocks: course_slug={slug!r} не існує ні в xlsx, '
                f'ні в БД'
            )
    for slug in plan.faq_slugs_in_file:
        if slug not in all_known:
            plan.errors.append(
                f'FAQ: course_slug={slug!r} не існує ні в xlsx, ні в БД'
            )

    return plan


def _diff_course(existing: Course, parsed: dict, trainer_id_by_slug: dict) -> list[str]:
    """Повернути список імен змінених полів. Порівняння помилкостійке."""
    changed = []
    fields = [
        'title', 'subtitle', 'short_description', 'description', 'event_type',
        'cpd_points', 'max_participants', 'trainer_id', 'hero_image',
        'card_image', 'speaker_info', 'agenda', 'is_active', 'is_featured',
    ]
    for f in fields:
        if (getattr(existing, f) or None) != (parsed[f] or None) and not (
            (getattr(existing, f) in ('', None)) and (parsed[f] in ('', None))
        ):
            changed.append(f)
    if (existing.base_price or Decimal(0)) != parsed['base_price']:
        changed.append('base_price')
    if (existing.target_audience or []) != parsed['target_audience']:
        changed.append('target_audience')
    if (existing.tags or []) != parsed['tags']:
        changed.append('tags')
    return changed


def apply_courses_plan(plan: CoursesImportPlan) -> dict:
    """Atomic upsert. Очікує plan.is_valid==True."""
    if not plan.is_valid:
        return {'ok': False, 'reason': 'plan has errors'}

    created = 0
    updated = 0
    blocks_touched = 0
    faq_touched = 0

    try:
        # 1) courses upsert
        for item in plan.courses:
            p = item['parsed']
            ex_id = item['existing_id']
            if ex_id is None:
                course = Course(slug=p['slug'])
                db.session.add(course)
                created += 1
            else:
                course = db.session.get(Course, ex_id)
                updated += 1

            course.title = p['title']
            course.slug = p['slug']
            course.subtitle = p['subtitle']
            course.short_description = p['short_description']
            course.description = p['description']
            course.event_type = p['event_type']
            course.base_price = p['base_price']
            course.cpd_points = p['cpd_points']
            course.max_participants = p['max_participants']
            course.trainer_id = p['trainer_id']
            course.hero_image = p['hero_image']
            course.card_image = p['card_image']
            course.speaker_info = p['speaker_info']
            course.agenda = p['agenda']
            course.target_audience = p['target_audience']
            course.tags = p['tags']
            course.is_active = p['is_active']
            course.is_featured = p['is_featured']

        db.session.flush()

        # 2) program blocks: REPLACE для курсів, чий slug згаданий у sheet
        slug_to_course = {c.slug: c for c in Course.query.all()}
        for slug in plan.program_slugs_in_file:
            course = slug_to_course.get(slug)
            if course is None:
                continue
            ProgramBlock.query.filter_by(course_id=course.id).delete()
            blocks = plan.program_blocks.get(slug, [])
            for b in blocks:
                db.session.add(ProgramBlock(
                    course_id=course.id,
                    heading=b['heading'],
                    items=b['items'],
                    sort_order=b['sort_order'],
                ))
                blocks_touched += 1

        # 3) faq: REPLACE як JSON-stored у Course.faq
        for slug in plan.faq_slugs_in_file:
            course = slug_to_course.get(slug)
            if course is None:
                continue
            faq_list = plan.faq.get(slug, [])
            course.faq = faq_list
            faq_touched += len(faq_list)

        db.session.commit()
        return {
            'ok': True,
            'created': created,
            'updated': updated,
            'blocks_touched': blocks_touched,
            'faq_touched': faq_touched,
        }
    except Exception as exc:
        db.session.rollback()
        logger.exception('apply_courses_plan failed')
        return {'ok': False, 'reason': str(exc)}


# ======================================================================
# COURSE INSTANCES (розклад)
# ======================================================================

INSTANCE_COLS = [
    'id', 'course_slug', 'start_date', 'end_date', 'event_format',
    'price', 'cpd_points', 'max_participants', 'trainer_slug',
    'location', 'online_link', 'status',
]

INSTANCE_LABELS = {
    'id': 'ID',
    'course_slug': 'Курс (slug)',
    'start_date': 'Початок',
    'end_date': 'Кінець',
    'event_format': 'Формат',
    'price': 'Ціна (грн)',
    'cpd_points': 'Бали БПР',
    'max_participants': 'Макс. учасників',
    'trainer_slug': 'Тренер',
    'location': 'Локація',
    'online_link': 'Онлайн-лінк',
    'status': 'Статус',
}


@dataclass
class InstanceChange:
    line_no: int
    course_slug: str
    start_date: str
    action: str  # 'create' | 'update' | 'unchanged' | 'error'
    fields_changed: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class InstancesImportPlan:
    instances: list[dict] = field(default_factory=list)
    changes: list[InstanceChange] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    @property
    def counts(self) -> dict[str, int]:
        c = {'create': 0, 'update': 0, 'unchanged': 0, 'error': 0}
        for ch in self.changes:
            c[ch.action] = c.get(ch.action, 0) + 1
        return c


def export_instances_xlsx(
    year: int | None = None,
    upcoming_only: bool = False,
    status: str | None = None,
) -> io.BytesIO:
    """Експорт розкладу. Усі фільтри необов'язкові.

    Параметри:
      year: int -- лише проведення з start_date у вказаному році.
      upcoming_only: True -- лише з start_date >= зараз.
      status: 'draft'|'published'|'active'|'completed'|'cancelled' -- фільтр статусу.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = 'Розклад'
    _style_header(ws, INSTANCE_COLS, INSTANCE_LABELS)

    course_slug_by_id = {c.id: c.slug for c in Course.query.all()}
    trainer_name_by_id = {t.id: t.full_name for t in Trainer.query.all()}

    q = CourseInstance.query.order_by(CourseInstance.start_date)
    if year:
        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        q = q.filter(
            CourseInstance.start_date >= start,
            CourseInstance.start_date < end,
        )
    if upcoming_only:
        q = q.filter(CourseInstance.start_date >= datetime.now(timezone.utc))
    if status:
        q = q.filter(CourseInstance.status == status)
    instances = q.all()
    for row_idx, i in enumerate(instances, start=2):
        values = [
            i.id,
            course_slug_by_id.get(i.course_id, ''),
            _to_kyiv_naive(i.start_date),
            _to_kyiv_naive(i.end_date),
            FORMAT_LABEL.get(i.event_format, i.event_format or ''),
            float(i.price) if i.price is not None else None,
            i.cpd_points,
            i.max_participants,
            trainer_name_by_id.get(i.trainer_id, '') if i.trainer_id else '',
            i.location or '',
            i.online_link or '',
            STATUS_LABEL.get(i.status, i.status or 'draft'),
        ]
        for col_idx, v in enumerate(values, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=v)
            cell.alignment = WRAP

    instances_last_row = ws.max_row

    # ЗЕБРА до enum-кольорів, щоб ті перекрили її.
    _apply_zebra(ws, len(INSTANCE_COLS), first_data_row=2, last_data_row=instances_last_row)

    # ----- Кольори за значенням -----------------------------------------
    fmt_col = INSTANCE_COLS.index('event_format') + 1
    st_col = INSTANCE_COLS.index('status') + 1
    for row_idx, i in enumerate(instances, start=2):
        if i.event_format in EVENT_FORMAT_FILLS:
            ws.cell(row=row_idx, column=fmt_col).fill = EVENT_FORMAT_FILLS[i.event_format]
        if i.status in STATUS_FILLS:
            ws.cell(row=row_idx, column=st_col).fill = STATUS_FILLS[i.status]

    _set_column_widths(ws, INSTANCE_COLS, INSTANCE_WIDTHS)
    _apply_number_formats(ws, INSTANCE_COLS, instances_last_row)

    # Reference sheet з тренерами + drop-down у колонці trainer_slug розкладу.
    trainers_last_row = _add_trainers_sheet(wb)
    _add_trainer_dropdown(
        ws, 'trainer_slug', INSTANCE_COLS,
        last_data_row=instances_last_row,
        trainers_last_row=trainers_last_row,
    )

    # Drop-down для формату та статусу — українські labels.
    _add_inline_dropdown(
        ws, 'event_format', INSTANCE_COLS,
        options=[label for _key, label in CourseInstance.FORMATS],
        last_data_row=instances_last_row,
        title='Формат',
        hint='Оберіть формат: Онлайн / Офлайн / Гібрид',
    )
    _add_inline_dropdown(
        ws, 'status', INSTANCE_COLS,
        options=[label for _key, label in CourseInstance.STATUSES],
        last_data_row=instances_last_row,
        title='Статус',
        hint='Чернетка / Опубліковано / Активний / Завершено / Скасовано',
    )

    # Excel Table style.
    _apply_table_style(ws, INSTANCE_COLS, 'tblSchedule', instances_last_row)

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out


def parse_instances_xlsx(path: Path) -> InstancesImportPlan:
    plan = InstancesImportPlan()
    try:
        wb = load_workbook(filename=str(path), read_only=False, data_only=True)
    except Exception as exc:
        plan.errors.append(f'Не вдалося відкрити xlsx: {exc}')
        return plan

    ws_i = _find_sheet(wb, 'instances')
    if ws_i is None:
        plan.errors.append('Відсутній sheet "Розклад"')
        return plan

    try:
        rows = _read_sheet(ws_i, INSTANCE_COLS, INSTANCE_LABELS)
    except ValueError as exc:
        plan.errors.append(str(exc))
        return plan

    course_id_by_slug = {c.slug: c.id for c in Course.query.all()}
    _all_trainers = Trainer.query.all()
    trainer_id_by_slug = {t.slug: t.id for t in _all_trainers}
    trainer_id_by_name = {t.full_name: t.id for t in _all_trainers}
    existing_by_id = {i.id: i for i in CourseInstance.query.all()}

    for line_no, raw in enumerate(rows, start=2):
        try:
            course_slug = _str(raw.get('course_slug'))
            if not course_slug:
                raise ValueError('порожній course_slug')
            course_id = course_id_by_slug.get(course_slug)
            if course_id is None:
                raise ValueError(f'course_slug={course_slug!r} не існує')

            start_date = _dt(raw.get('start_date'))
            if start_date is None:
                raise ValueError('порожня start_date')
            end_date = _dt(raw.get('end_date'))
            if end_date is not None and end_date <= start_date:
                raise ValueError(
                    f'end_date ({end_date.isoformat()}) має бути пізніше за '
                    f'start_date ({start_date.isoformat()})'
                )

            event_format_raw = _str(raw.get('event_format'))
            # Приймаємо як ('Онлайн','Офлайн','Гібрид'), так і ('online',
            # 'offline','hybrid') -- нормалізуємо у internal key.
            event_format = (
                FORMAT_KEY_BY_LABEL.get(event_format_raw, event_format_raw)
                if event_format_raw else None
            )
            if event_format and event_format not in VALID_FORMATS:
                allowed = sorted(VALID_FORMATS) + sorted(FORMAT_KEY_BY_LABEL.keys())
                raise ValueError(
                    f'event_format={event_format_raw!r} -- допустимі: {allowed}'
                )

            online_link = _str(raw.get('online_link'))
            location = _str(raw.get('location')) or ''

            # Логічна узгодженість формат ↔ канал залишаємо warning-only:
            # порожній location у поточних seed-даних означає Київ за
            # замовчуванням; порожній online_link можна допилити в адмінці.
            # Hard-error лише на end_date < start_date (вище).

            status_raw = _str(raw.get('status')) or 'draft'
            status = STATUS_KEY_BY_LABEL.get(status_raw, status_raw)
            if status not in VALID_STATUSES:
                allowed = sorted(VALID_STATUSES) + sorted(STATUS_KEY_BY_LABEL.keys())
                raise ValueError(
                    f'status={status_raw!r} -- допустимі: {allowed}'
                )

            # Колонка "Тренер" -- ПІБ (новий формат) або slug (старий).
            trainer_raw = _str(raw.get('trainer_slug'))
            trainer_id = None
            if trainer_raw:
                trainer_id = (
                    trainer_id_by_slug.get(trainer_raw)
                    or trainer_id_by_name.get(trainer_raw)
                )
                if trainer_id is None:
                    raise ValueError(
                        f'тренера {trainer_raw!r} не знайдено '
                        f'(ні за slug, ні за ПІБ)'
                    )

            parsed = {
                'id': _int(raw.get('id')),
                'course_id': course_id,
                'course_slug': course_slug,
                'start_date': start_date,
                'end_date': end_date,
                'event_format': event_format,
                'price': _decimal(raw.get('price')),
                'cpd_points': _int(raw.get('cpd_points')),
                'max_participants': _int(raw.get('max_participants')),
                'trainer_id': trainer_id,
                'location': location,
                'online_link': online_link,
                'status': status,
            }

            existing = None
            if parsed['id'] is not None:
                existing = existing_by_id.get(parsed['id'])
                if existing is None:
                    raise ValueError(
                        f'id={parsed["id"]} не існує '
                        f'(використайте порожній id для нового проведення)'
                    )

            plan.instances.append({'parsed': parsed, 'existing_id': existing.id if existing else None})

            sd = start_date.strftime('%Y-%m-%d')
            if existing is None:
                plan.changes.append(InstanceChange(
                    line_no=line_no, course_slug=course_slug,
                    start_date=sd, action='create',
                ))
            else:
                diff = _diff_instance(existing, parsed)
                if diff:
                    plan.changes.append(InstanceChange(
                        line_no=line_no, course_slug=course_slug,
                        start_date=sd, action='update',
                        fields_changed=diff,
                    ))
                else:
                    plan.changes.append(InstanceChange(
                        line_no=line_no, course_slug=course_slug,
                        start_date=sd, action='unchanged',
                    ))
        except Exception as exc:
            plan.errors.append(f'Рядок {line_no} (Instances): {exc}')
            plan.changes.append(InstanceChange(
                line_no=line_no,
                course_slug=_str(raw.get('course_slug')) or '',
                start_date=str(raw.get('start_date') or ''),
                action='error',
                error=str(exc),
            ))

    return plan


def _diff_instance(existing: CourseInstance, parsed: dict) -> list[str]:
    changed = []
    if existing.course_id != parsed['course_id']:
        changed.append('course_slug')
    for f in ('start_date', 'end_date', 'event_format', 'cpd_points',
              'max_participants', 'trainer_id', 'online_link', 'status'):
        ev = getattr(existing, f)
        pv = parsed[f]
        if (ev or None) != (pv or None):
            changed.append(f)
    if (existing.location or '') != (parsed['location'] or ''):
        changed.append('location')
    ep = existing.price
    pp = parsed['price']
    if (ep is None) != (pp is None) or (ep is not None and pp is not None and ep != pp):
        changed.append('price')
    return changed


def apply_instances_plan(plan: InstancesImportPlan) -> dict:
    if not plan.is_valid:
        return {'ok': False, 'reason': 'plan has errors'}

    created = 0
    updated = 0

    try:
        for item in plan.instances:
            p = item['parsed']
            ex_id = item['existing_id']
            if ex_id is None:
                inst = CourseInstance(course_id=p['course_id'])
                db.session.add(inst)
                created += 1
            else:
                inst = db.session.get(CourseInstance, ex_id)
                updated += 1

            inst.course_id = p['course_id']
            inst.start_date = p['start_date']
            inst.end_date = p['end_date']
            inst.event_format = p['event_format']
            inst.price = p['price']
            inst.cpd_points = p['cpd_points']
            inst.max_participants = p['max_participants']
            inst.trainer_id = p['trainer_id']
            inst.location = p['location']
            inst.online_link = p['online_link']
            inst.status = p['status']

        db.session.commit()
        return {'ok': True, 'created': created, 'updated': updated}
    except Exception as exc:
        db.session.rollback()
        logger.exception('apply_instances_plan failed')
        return {'ok': False, 'reason': str(exc)}
