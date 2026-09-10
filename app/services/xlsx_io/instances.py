"""XLSX: розклад проведень (CourseInstance).

Структурно дзеркалить модуль курсів -- ті самі чотири кроки
export/parse/diff/apply. Спільне між ними живе в _common; якщо доводиться
правити однакову логіку в обох, їй місце там, а не тут.

Проведення завжди належить курсу, тож розбір спершу резолвить course_slug
і відхиляє рядок, у якого курсу немає -- створювати курс «на льоту» тут
не можна, інакше друкарська помилка в slug тихо породжувала б новий курс.
"""

from __future__ import annotations

import io

from dataclasses import (
    dataclass,
    field,
)
from datetime import (
    datetime,
    timezone,
)
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
from app.models.course_instance import CourseInstance
from app.models.trainer import Trainer
from app.services import trainer_links
from app.utils import ensure_utc

from ._common import (
    EVENT_FORMAT_FILLS,
    FORMAT_KEY_BY_LABEL,
    FORMAT_LABEL,
    INSTANCE_WIDTHS,
    STATUS_FILLS,
    STATUS_KEY_BY_LABEL,
    STATUS_LABEL,
    VALID_FORMATS,
    VALID_STATUSES,
    WRAP,
    _APPLY_FAILED_MESSAGE,
    _add_inline_dropdown,
    _add_trainers_sheet,
    _apply_number_formats,
    _apply_table_style,
    _apply_zebra,
    _check_min_values,
    _decimal,
    _dt,
    _find_sheet,
    _int,
    _points_cell,
    _read_sheet,
    _resolve_trainer_ids,
    _set_column_widths,
    _str,
    _style_header,
    _to_kyiv_naive,
    build_trainer_lookup,
    logger,
    record_row_error,
    write_cell,
)


# ======================================================================
# COURSE INSTANCES (розклад)
# ======================================================================

INSTANCE_COLS = [
    'id', 'course_slug', 'start_date', 'end_date', 'event_format',
    'price', 'cpd_points_online', 'cpd_points_offline', 'max_participants',
    'trainer_slugs', 'location', 'online_link', 'status',
]

INSTANCE_LABELS = {
    'id': 'ID',
    'course_slug': 'Курс (slug)',
    'start_date': 'Початок',
    'end_date': 'Кінець',
    'event_format': 'Формат',
    'price': 'Ціна (грн)',
    'cpd_points_online': 'Бали БПР онлайн',
    'cpd_points_offline': 'Бали БПР офлайн',
    'max_participants': 'Макс. учасників',
    'trainer_slugs': 'Тренери',
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
    # (ключ аркуша, номер рядка, текст) -- для повернення помилок
    # у копію завантаженого файлу.
    row_errors: list[tuple[str, int, str]] = field(default_factory=list)

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

    q = (
        CourseInstance.query
        .options(joinedload(CourseInstance.trainers))
        .order_by(CourseInstance.start_date)
    )
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
            float(i.cpd_points_online) if i.cpd_points_online is not None else None,
            float(i.cpd_points_offline) if i.cpd_points_offline is not None else None,
            i.max_participants,
            # Порядок тренерів = порядок лекторів (перший -- головний), той
            # самий формат, що й у Курсах (див. export_courses_xlsx).
            '; '.join(t.full_name for t in i.trainers),
            i.location or '',
            i.online_link or '',
            STATUS_LABEL.get(i.status, i.status or 'draft'),
        ]
        for col_idx, v in enumerate(values, start=1):
            cell = write_cell(ws, row_idx, col_idx, v)
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

    # Reference sheet з тренерами -- як і в Курсах, без drop-down у самій
    # колонці (список значень, а не одне) -- див. коментар у export_courses_xlsx.
    _add_trainers_sheet(wb)

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
    trainer_id_by_slug, trainer_id_by_name, ambiguous_names = build_trainer_lookup(
        Trainer.query.all()
    )
    # selectinload -- з тієї самої причини, що й у розборі курсів:
    # _diff_instance читає existing.trainers на кожному рядку.
    existing_by_id = {
        i.id: i
        for i in CourseInstance.query.options(
            selectinload(CourseInstance.trainers)
        ).all()
    }

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
                    f'event_format={event_format_raw!r} – допустимі: {allowed}'
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
                    f'status={status_raw!r} – допустимі: {allowed}'
                )

            # Колонка "Тренери" -- перелік через ';'/',' (ПІБ і/або slug),
            # у порядку запису: перший -- головний лектор.
            trainer_ids = _resolve_trainer_ids(
                raw.get('trainer_slugs'), trainer_id_by_slug, trainer_id_by_name,
                ambiguous_names,
            )

            parsed = {
                'id': _int(raw.get('id')),
                'course_id': course_id,
                'course_slug': course_slug,
                'start_date': start_date,
                'end_date': end_date,
                'event_format': event_format,
                'price': _decimal(raw.get('price')),
                'cpd_points_online': _points_cell(raw.get('cpd_points_online')),
                'cpd_points_offline': _points_cell(raw.get('cpd_points_offline')),
                'max_participants': _int(raw.get('max_participants')),
                'trainer_ids': trainer_ids,
                'location': location,
                'online_link': online_link,
                'status': status,
            }
            _check_min_values(parsed)

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
            record_row_error(plan, 'instances', line_no, exc, 'Instances')
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
    # Дати -- через ensure_utc: SQLite віддає їх naive, а з файлу вони
    # приходять з київською tz. Порівняння naive з aware не падає, а просто
    # ЗАВЖДИ нерівне, тож на dev кожне наявне проведення показувалось як
    # "оновити". На PostgreSQL (prod) колонки timezone-aware і збігу немає.
    for f in ('start_date', 'end_date'):
        if ensure_utc(getattr(existing, f)) != ensure_utc(parsed[f]):
            changed.append(f)
    for f in ('event_format', 'cpd_points_online', 'cpd_points_offline',
              'max_participants', 'online_link', 'status'):
        ev = getattr(existing, f)
        pv = parsed[f]
        if (ev or None) != (pv or None):
            changed.append(f)
    # Тренери -- порядок, а не множина: перший є головним лектором, тож
    # переставлення без зміни складу теж має вважатись зміною.
    if [t.id for t in existing.trainers] != parsed['trainer_ids']:
        changed.append('trainer_slugs')
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
    vanished = []

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
                if inst is None:
                    # Те саме, що й у курсах: проведення могли видалити, поки
                    # людина читала прев'ю. Одна зникла сутність не має
                    # відкочувати весь імпорт.
                    vanished.append(ex_id)
                    continue
                updated += 1

            inst.course_id = p['course_id']
            inst.start_date = p['start_date']
            inst.end_date = p['end_date']
            inst.event_format = p['event_format']
            inst.price = p['price']
            inst.cpd_points_online = p['cpd_points_online']
            inst.cpd_points_offline = p['cpd_points_offline']
            inst.max_participants = p['max_participants']
            inst.location = p['location']
            inst.online_link = p['online_link']
            inst.status = p['status']
            # Порядок -- ознака ролі (перший = головний лектор); set_trainers
            # сам подбає про flush нового проведення, якщо йому ще бракує id.
            trainer_links.set_trainers(inst, p['trainer_ids'])

        db.session.commit()
        return {'ok': True, 'created': created, 'updated': updated,
                'vanished': vanished}
    except Exception:
        db.session.rollback()
        logger.exception('apply_instances_plan failed')
        return {'ok': False, 'reason': _APPLY_FAILED_MESSAGE}


