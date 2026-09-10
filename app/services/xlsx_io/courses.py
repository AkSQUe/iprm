"""XLSX: курси разом із блоками програми і FAQ.

Три аркуші одного файлу, бо вони й редагуються разом: «Курси» -- самі
курси, «Програма» і «FAQ» -- підпорядкований вміст. Обидва підпорядковані
аркуші працюють у режимі REPLACE, але лише для тих slug, які у файлі
зустрічаються: курс, не згаданий в аркуші, свої блоки зберігає.
"""

from __future__ import annotations

import io

from dataclasses import (
    dataclass,
    field,
)
from decimal import Decimal
from pathlib import Path

from openpyxl import (
    Workbook,
    load_workbook,
)
from sqlalchemy.orm import (
    joinedload,
    selectinload,
)

from app.extensions import db
from app.models.course import Course
from app.models.program_block import ProgramBlock
from app.models.trainer import Trainer
from app.services import trainer_links

from ._common import (
    BOOL_FALSE_FILL,
    BOOL_TRUE_FILL,
    COURSE_WIDTHS,
    FAQ_WIDTHS,
    PROGRAM_WIDTHS,
    WRAP,
    _APPLY_FAILED_MESSAGE,
    _add_inline_dropdown,
    _add_trainers_sheet,
    _apply_number_formats,
    _apply_table_style,
    _apply_zebra,
    _bool,
    _check_min_values,
    _decimal,
    _find_sheet,
    _from_lines,
    _int,
    _points_cell,
    _read_sheet,
    _resolve_media_id,
    _resolve_trainer_ids,
    _set_column_widths,
    _str,
    _style_header,
    _to_lines,
    build_trainer_lookup,
    event_type_dropdown_options,
    logger,
    normalize_event_type,
    record_row_error,
    write_cell,
)


# ======================================================================
# COURSES
# ======================================================================

COURSE_COLS = [
    'id', 'slug', 'title', 'subtitle', 'short_description', 'description',
    'event_type', 'base_price', 'cpd_points_online', 'cpd_points_offline',
    'max_participants',
    'trainer_slugs', 'hero_image', 'card_image', 'agenda',
    'final_cta_text', 'target_audience', 'tags', 'is_active', 'is_featured',
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
    'cpd_points_online': 'Бали БПР онлайн',
    'cpd_points_offline': 'Бали БПР офлайн',
    'max_participants': 'Макс. учасників',
    'trainer_slugs': 'Тренери',
    'hero_image': 'Hero-зображення',
    'card_image': 'Зображення картки',
    'agenda': 'Програма (опис)',
    'final_cta_text': 'Фінальний заклик',
    'target_audience': 'Цільова аудиторія',
    'tags': 'Теги',
    'is_active': 'Активний',
    'is_featured': 'Рекомендований',
}

# Колонки, додані після того, як менеджери вже мали на руках експорти.
# Їх відсутність не ламає імпорт старого файлу, а поле лишається як у БД --
# інакше кожне нове поле знецінювало б усі раніше збережені файли.
OPTIONAL_COURSE_COLS = ('final_cta_text',)

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
    # (ключ аркуша, номер рядка, текст) -- для повернення помилок
    # у копію завантаженого файлу.
    row_errors: list[tuple[str, int, str]] = field(default_factory=list)
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
    from app.services import event_types

    wb = Workbook()
    ws = wb.active
    ws.title = 'Курси'
    _style_header(ws, COURSE_COLS, COURSE_LABELS)

    q = Course.query.options(joinedload(Course.trainers)).order_by(Course.id)
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
            event_types.base_name(c.event_type) if c.event_type else '',
            float(c.base_price) if c.base_price is not None else 0,
            float(c.cpd_points_online) if c.cpd_points_online is not None else None,
            float(c.cpd_points_offline) if c.cpd_points_offline is not None else None,
            c.max_participants,
            # Порядок тренерів = порядок лекторів (перший -- головний):
            # relationship уже відсортований за position, зʼєднуємо '; ',
            # бо кома трапляється всередині самого ПІБ.
            '; '.join(t.full_name for t in c.trainers),
            # Експортуємо ОСНОВНИЙ media-URL (не варіант) -> резолвиться назад
            # у реєстр за file_path на імпорті (_resolve_media_id).
            c.hero_media.url if c.hero_media else '',
            c.card_media.url if c.card_media else '',
            c.agenda or '',
            c.final_cta_text or '',
            _to_lines(c.target_audience),
            _to_lines(c.tags),
            bool(c.is_active),
            bool(c.is_featured),
        ]
        for col_idx, v in enumerate(values, start=1):
            cell = write_cell(ws, row_idx, col_idx, v)
            cell.alignment = WRAP

    courses_last_row = ws.max_row

    # ЗЕБРА перед enum-кольорами, щоб enum-fills перекрили її на своїх клітинках.
    _apply_zebra(ws, len(COURSE_COLS), first_data_row=2, last_data_row=courses_last_row)

    # ----- Кольори за значенням -----------------------------------------
    # event_type тут колись мав власну заливку (EVENT_TYPE_FILLS), поки видів
    # було п'ять і вони жили в коді. Дванадцять редагованих у БД видів такій
    # мапі більше не піддаються -- прибрано разом з константою.
    ia_col = COURSE_COLS.index('is_active') + 1
    if_col = COURSE_COLS.index('is_featured') + 1
    for row_idx, c in enumerate(courses, start=2):
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

    # Reference sheet з тренерами (вже з Table): джерело точних написань
    # ПІБ для клітинки зі списком. Без drop-down у самій колонці -- клітинка
    # тримає кілька значень, а Excel вміє валідувати лише ОДНЕ значення з
    # діапазону: залишений drop-down мовчки відхиляв би коректний ввід.
    _add_trainers_sheet(wb)

    # Drop-down для типу заходу -- лише активні типи з довідника.
    _event_type_options = event_type_dropdown_options()
    _add_inline_dropdown(
        ws, 'event_type', COURSE_COLS,
        options=_event_type_options,
        last_data_row=courses_last_row,
        title='Тип заходу',
        hint='Оберіть зі списку: ' + ', '.join(_event_type_options),
    )

    # Excel Tables (forматовані з зеброю + auto-filter).
    _apply_table_style(ws, COURSE_COLS, 'tblCourses', courses_last_row)
    _apply_table_style(ws_p, PROGRAM_COLS, 'tblProgramBlocks', program_last_row)
    _apply_table_style(ws_f, FAQ_COLS, 'tblFAQ', faq_last_row)

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out




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
        rows = _read_sheet(ws_c, COURSE_COLS, COURSE_LABELS,
                           optional=OPTIONAL_COURSE_COLS)
    except ValueError as exc:
        plan.errors.append(str(exc))
        return plan

    trainer_id_by_slug, trainer_id_by_name, ambiguous_names = build_trainer_lookup(
        Trainer.query.all()
    )
    # selectinload: _diff_course читає existing.trainers на КОЖНОМУ рядку, а
    # relationship лінивий -- без цього прев'ю великого файлу робило по запиту
    # на курс.
    existing_by_id = {
        c.id: c
        for c in Course.query.options(selectinload(Course.trainers)).all()
    }
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

            # Приймаємо і внутрішній код ('seminar'), і українську назву з
            # drop-down ('Семінар'); застарілі типи теж проходять --
            # інакше архівні вигрузки перестали б імпортуватись.
            #
            # Дефолт для порожньої комірки -- 'seminar', а не колишній
            # 'course': 'course' деактивований, тож він показував би голий
            # код на публічній сторінці. Свідомо міняємо стару поведінку,
            # хоча архівний файл із порожніми клітинками тепер завозить
            # «Семінар» замість «Курс» -- ризик визнано прийнятним.
            event_type = normalize_event_type(raw.get('event_type')) or 'seminar'

            # Колонка "Тренери" -- перелік через ';'/',' (ПІБ і/або slug),
            # у порядку запису: перший -- головний лектор.
            trainer_ids = _resolve_trainer_ids(
                raw.get('trainer_slugs'), trainer_id_by_slug, trainer_id_by_name,
                ambiguous_names,
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
                'cpd_points_online': _points_cell(raw.get('cpd_points_online')),
                'cpd_points_offline': _points_cell(raw.get('cpd_points_offline')),
                'max_participants': _int(raw.get('max_participants')),
                'trainer_ids': trainer_ids,
                'hero_image': _str(raw.get('hero_image')),
                'card_image': _str(raw.get('card_image')),
                'agenda': _str(raw.get('agenda')),
                'target_audience': _from_lines(raw.get('target_audience')),
                'tags': _from_lines(raw.get('tags')),
                'is_active': _bool(raw.get('is_active')),
                'is_featured': _bool(raw.get('is_featured')),
            }
            # Опційні колонки кладемо в parsed ЛИШЕ якщо вони були у файлі:
            # відсутність колонки має лишити поле як є, а не занулити його.
            for opt in OPTIONAL_COURSE_COLS:
                if opt in raw:
                    parsed[opt] = _str(raw.get(opt))

            if not parsed['title']:
                raise ValueError('порожній title')
            _check_min_values(parsed)

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
                diff = _diff_course(existing, parsed)
                if diff:
                    plan.changes.append(CourseChange(
                        slug=slug, action='update', fields_changed=diff,
                    ))
                else:
                    plan.changes.append(CourseChange(slug=slug, action='unchanged'))
        except Exception as exc:
            record_row_error(plan, 'courses', line_no, exc, 'Courses')
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
                record_row_error(plan, 'program_blocks', line_no, exc, 'Program blocks')

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
                record_row_error(plan, 'faq', line_no, exc, 'FAQ')

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


def _diff_course(existing: Course, parsed: dict) -> list[str]:
    """Повернути список імен змінених полів. Порівняння помилкостійке."""
    changed = []
    # hero_image/card_image тут НЕМАЄ свідомо: після переходу на медіа-реєстр
    # (фаза 6) у Course лишились тільки *_media_id, і getattr по старій назві
    # кидав AttributeError -- через це будь-який рядок з ІСНУЮЧИМ курсом
    # ставав помилкою і файл цілком відхилявся. Зображення порівнюємо нижче,
    # резолвленими id.
    fields = [
        'title', 'subtitle', 'short_description', 'description', 'event_type',
        'cpd_points_online', 'cpd_points_offline', 'max_participants',
        'agenda', 'is_active', 'is_featured',
    ]
    for f in fields:
        if (getattr(existing, f) or None) != (parsed[f] or None) and not (
            (getattr(existing, f) in ('', None)) and (parsed[f] in ('', None))
        ):
            changed.append(f)
    # Тренери -- порядок, а не множина: перший є головним лектором, тож
    # переставлення без зміни складу теж має вважатись зміною.
    if [t.id for t in existing.trainers] != parsed['trainer_ids']:
        changed.append('trainer_slugs')
    if (existing.base_price or Decimal(0)) != parsed['base_price']:
        changed.append('base_price')
    if (existing.target_audience or []) != parsed['target_audience']:
        changed.append('target_audience')
    if (existing.tags or []) != parsed['tags']:
        changed.append('tags')
    # У файлі -- людиночитний URL; порівнюємо так само, як apply записує.
    for media_col, url_key in (('hero_media_id', 'hero_image'),
                               ('card_media_id', 'card_image')):
        if getattr(existing, media_col) != _resolve_media_id(parsed[url_key]):
            changed.append(url_key)
    for opt in OPTIONAL_COURSE_COLS:
        if opt in parsed and (getattr(existing, opt) or None) != (parsed[opt] or None):
            changed.append(opt)
    return changed


def apply_courses_plan(plan: CoursesImportPlan) -> dict:
    """Atomic upsert. Очікує plan.is_valid==True."""
    if not plan.is_valid:
        return {'ok': False, 'reason': 'plan has errors'}

    created = 0
    updated = 0
    vanished = []
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
                if course is None:
                    # План будується на знімку БД і показується людині на
                    # підтвердження; поки вона його читає, курс могли
                    # видалити. Без цієї перевірки наступний рядок звалився б
                    # AttributeError на None і відкотив УВЕСЬ імпорт через
                    # одну зниклу сутність. Пропускаємо і звітуємо окремо.
                    vanished.append(p['slug'])
                    continue
                updated += 1

            course.title = p['title']
            course.slug = p['slug']
            course.subtitle = p['subtitle']
            course.short_description = p['short_description']
            course.description = p['description']
            course.event_type = p['event_type']
            course.base_price = p['base_price']
            course.cpd_points_online = p['cpd_points_online']
            course.cpd_points_offline = p['cpd_points_offline']
            course.max_participants = p['max_participants']
            course.hero_media_id = _resolve_media_id(p['hero_image'])
            course.card_media_id = _resolve_media_id(p['card_image'])
            course.agenda = p['agenda']
            course.target_audience = p['target_audience']
            course.tags = p['tags']
            course.is_active = p['is_active']
            course.is_featured = p['is_featured']
            for opt in OPTIONAL_COURSE_COLS:
                if opt in p:
                    setattr(course, opt, p[opt])
            # Порядок -- ознака ролі (перший = головний лектор); set_trainers
            # сам подбає про flush нового курсу, якщо йому ще бракує id.
            trainer_links.set_trainers(course, p['trainer_ids'])

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
            'vanished': vanished,
            'blocks_touched': blocks_touched,
            'faq_touched': faq_touched,
        }
    except Exception:
        db.session.rollback()
        logger.exception('apply_courses_plan failed')
        return {'ok': False, 'reason': _APPLY_FAILED_MESSAGE}


