"""Адмінка довідника видів заходів БПР.

Довідник плоский і на півтора десятка рядків, тож окремої сторінки
редагування немає: уся таблиця правиться і зберігається одним сабмітом --
той самий підхід, що в довіднику локацій.

Вживаний тип не видаляється, а деактивується. Інакше зміна номенклатури
лишила б курси з кодом, якого вже ніде немає, і вони показували б голий
латинський рядок замість назви.
"""
import logging
import re

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.admin import admin_bp
from app.admin._helpers import try_commit
from app.extensions import db
from app.i18n import PREFIXED_LANGUAGES
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.event_type import EventType
from app.rbac import permission_required
from app.services import event_types

audit_logger = logging.getLogger('audit')

# Код їде далі в партнерське API й xlsx як є (без FK, це природний ключ).
# HTML-форма підказує ("латиницею", maxlength=30), але без серверної
# перевірки код з пробілом чи кирилицею пройшов би і зламав обидва
# контракти нижче за течією. Дефіс лишаємо поруч із підкресленням --
# обидва вже трапляються в кодах (напр. службові тестові коди).
_CODE_RE = re.compile(r'[a-z0-9_-]{1,30}')

# Межі з моделі. HTML їх теж має (maxlength), але сабміт повз браузер
# інакше дійшов би до DataError на String(120) і відкотив УВЕСЬ сабміт
# таблиці з загальним "Помилка при збереженні" -- без натяку, який рядок
# винен.
_CODE_MAX = 30
_NAME_MAX = 120

# Скільки назв курсів показувати в розкривному списку рядка. Довше --
# це вже список курсів, і там для цього є фільтр.
_PREVIEW_COURSES = 5


def _usage():
    """{code: скільки курсів і проведень цим типом}.

    Живе тут, а не в службі читання довідника: це запитання адмінки, і
    службі назв воно додавало б залежність від двох моделей, яких їй
    більше нізащо не треба.

    Адмінці це і вага рядка, і запобіжник: вживаний тип видаляти не можна,
    його деактивують.
    """
    counts = {}
    for model in (Course, CourseInstance):
        rows = (
            db.session.query(model.event_type, db.func.count(model.id))
            .filter(model.event_type.isnot(None), model.event_type != '')
            .group_by(model.event_type)
            .all()
        )
        for code, count in rows:
            counts[code] = counts.get(code, 0) + count
    return counts


def _courses_by_type():
    """{code: [назви курсів]} -- перші кілька назв на рядок довідника.

    Потрібно рівно в момент, коли тип збираються деактивувати: питання
    "а що я цим зламаю" інакше вимагає піти в список курсів і згадати,
    як він фільтрується.
    """
    preview = {}
    rows = (
        db.session.query(Course.event_type, Course.title)
        .filter(Course.event_type.isnot(None), Course.event_type != '')
        .order_by(Course.title)
        .all()
    )
    for code, title in rows:
        preview.setdefault(code, []).append(title)
    return preview


def _rows():
    """Рядок таблиці збираємо тут, а не в шаблоні: розкопувати JSON
    перекладів у Jinja -- логіка не на своєму поверсі."""
    usage = _usage()
    courses = _courses_by_type()
    rows = []
    # Довідник уже прочитаний і закешований у g службою; другий такий
    # самий запит тут був би дарма.
    for row in event_types.directory().values():
        stored = row.translations or {}
        titles = courses.get(row.code, [])
        # Ключ саме 'tr': row.values у Jinja дало б метод dict.values.
        rows.append({
            'type': row,
            'tr': {lang: ((stored.get(lang) or {}).get('name') or '')
                   for lang in PREFIXED_LANGUAGES},
            'uses': usage.get(row.code, 0),
            'course_titles': titles[:_PREVIEW_COURSES],
            'more_courses': max(0, len(titles) - _PREVIEW_COURSES),
            # Тип без відмінків друкує в сертифікаті називний замість
            # знахідного ("успішно завершив(-ла) наукова конференція") --
            # рівно той дефект, заради якого довідник і робився. Тихо це
            # не лишаємо.
            'needs_cases': not (row.name_accusative and row.name_genitive),
        })
    return rows


@admin_bp.route('/event-types', methods=['GET'])
@permission_required('event_types.view')
def event_types_list():
    rows = _rows()
    return render_template(
        'admin/event_types.html',
        rows=rows,
        languages=PREFIXED_LANGUAGES,
        active_count=sum(1 for r in rows if r['type'].is_active),
        needs_cases_count=sum(1 for r in rows if r['needs_cases']),
    )


def _field(name):
    """Значення поля форми, обрізане по краях, або None."""
    value = (request.form.get(name) or '').strip()
    return value or None


@admin_bp.route('/event-types/save', methods=['POST'])
@permission_required('event_types.manage')
def event_types_save():
    """Зберегти всю таблицю одним сабмітом."""
    rows = EventType.query.order_by(EventType.sort_order, EventType.name).all()
    errors = []
    changed = 0
    active_after = 0

    for row in rows:
        name_key = f'name__{row.id}'
        if name_key not in request.form:
            # Рядок не прийшов у сабміті -- лишаємо як є, разом з активністю.
            active_after += 1 if row.is_active else 0
            continue

        fields = {
            'name': (_field(name_key), 'назва'),
            'name_accusative': (_field(f'accusative__{row.id}'), 'знахідний'),
            'name_genitive': (_field(f'genitive__{row.id}'), 'родовий'),
        }
        translations = {
            lang: _field(f'tr__{lang}__{row.id}') for lang in PREFIXED_LANGUAGES
        }
        for value, title in list(fields.values()) + [
            (v, f'переклад {lang}') for lang, v in translations.items()
        ]:
            if value and len(value) > _NAME_MAX:
                errors.append(f'{row.code}: {title} довша за {_NAME_MAX} символів')

        sort_raw = (request.form.get(f'sort__{row.id}') or '').strip()
        sort_value = row.sort_order
        if sort_raw:
            try:
                sort_value = int(sort_raw)
            except ValueError:
                # Мовчазне ігнорування тут гірше за помилку: сторінка
                # писала б "Довідник збережено", а значення лишалось старим.
                errors.append(f'{row.code}: «{sort_raw}» не число в полі «Порядок»')

        # Незнята галка чекбокса просто не приходить у form -- саме так
        # рядок і деактивують.
        is_active = f'active__{row.id}' in request.form
        active_after += 1 if is_active else 0

        if errors:
            continue

        if fields['name'][0]:
            row.name = fields['name'][0]
        row.name_accusative = fields['name_accusative'][0]
        row.name_genitive = fields['name_genitive'][0]
        row.sort_order = sort_value
        row.is_active = is_active
        for lang, value in translations.items():
            row.set_translation(lang, 'name', value)
        changed += 1

    if not errors and rows and not active_after:
        # Порожній довідник активних типів робить форму створення курсу
        # непрохідною: choices порожній, а поле обов'язкове. Вийти з цього
        # через інтерфейс не можна нічим, крім як увімкнути тип назад.
        errors.append('Хоча б один тип мусить лишатись активним: '
                      'інакше в формі курсу не буде чого обрати')

    if errors:
        db.session.rollback()
        for message in errors[:5]:
            flash(message, 'error')
        if len(errors) > 5:
            flash(f'…і ще {len(errors) - 5} схожих зауважень', 'error')
        return redirect(url_for('admin.event_types_list'))

    if try_commit(log_context='event_types_save'):
        event_types.reset_cache()
        audit_logger.info('Admin %s updated event type directory (%s rows)',
                          current_user.email, changed)
        flash('Довідник збережено.', 'success')
    return redirect(url_for('admin.event_types_list'))


@admin_bp.route('/event-types/add', methods=['POST'])
@permission_required('event_types.manage')
def event_types_add():
    code = (request.form.get('code') or '').strip().lower()
    name = _field('name')
    accusative = _field('accusative')
    genitive = _field('genitive')

    if not code or not name:
        flash('Вкажіть і код, і назву типу', 'error')
        return redirect(url_for('admin.event_types_list'))

    if len(code) > _CODE_MAX or not _CODE_RE.fullmatch(code):
        flash(f'Код мусить бути латиницею, цифрами, підкресленням або '
              f'дефісом, без пробілів (до {_CODE_MAX} символів)', 'error')
        return redirect(url_for('admin.event_types_list'))

    for value, title in ((name, 'Назва'), (accusative, 'Знахідний'),
                         (genitive, 'Родовий')):
        if value and len(value) > _NAME_MAX:
            flash(f'{title} довша за {_NAME_MAX} символів', 'error')
            return redirect(url_for('admin.event_types_list'))

    # Відмінки обов'язкові саме тут, на створенні: тип без них друкує в
    # сертифікаті називний замість знахідного, помилку видно вже на
    # виданому документі, і виправлення довідника її звідти не прибирає.
    if not accusative or not genitive:
        flash('Впишіть обидва відмінки: без них сертифікат надрукує '
              'називний («завершив(-ла) наукова конференція»)', 'error')
        return redirect(url_for('admin.event_types_list'))

    if EventType.query.filter_by(code=code).first():
        flash(f'Тип з кодом "{code}" уже є в довіднику', 'info')
        return redirect(url_for('admin.event_types_list'))

    last = db.session.query(db.func.max(EventType.sort_order)).scalar() or 0
    db.session.add(EventType(
        code=code,
        name=name,
        name_accusative=accusative,
        name_genitive=genitive,
        sort_order=last + 1,
        is_active=True,
    ))
    if try_commit(log_context=f'event_types_add code={code!r}',
                  error_msg='Не вдалося додати тип (можливо, його щойно '
                            'додав інший адміністратор)'):
        event_types.reset_cache()
        audit_logger.info('Admin %s added event type %r', current_user.email, code)
        flash(f'Додано "{name}". Впишіть переклади та збережіть.', 'success')
    return redirect(url_for('admin.event_types_list'))


@admin_bp.route('/event-types/<int:type_id>/move', methods=['POST'])
@permission_required('event_types.manage')
def event_types_move(type_id):
    """Переставити тип на сусідню позицію.

    Порядок -- числове поле, і перестановка двох типів через нього
    вимагає порахувати й вписати два числа. Кнопка робить те саме
    обміном sort_order із сусідом.
    """
    direction = request.form.get('direction')
    if direction not in ('up', 'down'):
        flash('Невідомий напрямок переставляння', 'error')
        return redirect(url_for('admin.event_types_list'))

    rows = EventType.query.order_by(EventType.sort_order, EventType.name).all()
    index = next((i for i, row in enumerate(rows) if row.id == type_id), None)
    if index is None:
        flash('Тип не знайдено', 'error')
        return redirect(url_for('admin.event_types_list'))

    neighbour = index - 1 if direction == 'up' else index + 1
    if not 0 <= neighbour < len(rows):
        return redirect(url_for('admin.event_types_list'))

    row, other = rows[index], rows[neighbour]
    # Порядок не унікальний, і два сусіди можуть мати однакове число --
    # тоді простий обмін нічого не змінив би. Перенумеровуємо позиції.
    row.sort_order, other.sort_order = neighbour, index
    for position, item in enumerate(rows):
        if item.id not in (row.id, other.id):
            item.sort_order = position

    if try_commit(log_context=f'event_types_move id={type_id} {direction}'):
        event_types.reset_cache()
    return redirect(url_for('admin.event_types_list'))


@admin_bp.route('/event-types/<int:type_id>/delete', methods=['POST'])
@permission_required('event_types.delete')
def event_types_delete(type_id):
    row = db.session.get(EventType, type_id)
    if row is None:
        flash('Тип не знайдено', 'error')
        return redirect(url_for('admin.event_types_list'))

    uses = _usage().get(row.code, 0)
    if uses:
        flash(f'"{row.name}" вживається у {uses} курсах і проведеннях. '
              f'Зніміть галку «Активний» замість видалення.', 'error')
        return redirect(url_for('admin.event_types_list'))

    name = row.name
    code = row.code
    db.session.delete(row)
    if try_commit(log_context=f'event_types_delete id={type_id}'):
        event_types.reset_cache()
        audit_logger.info('Admin %s deleted event type %r', current_user.email, name)
        flash(f'"{name}" видалено з довідника.', 'success')
        # Запобіжник вище читає usage() до видалення, тож курс, створений
        # між читанням і комітом, лишився б із кодом, якого вже немає.
        # Вікно вузьке, шкода не фатальна (картка покаже голий код), але
        # мовчати про неї не варто -- слід у логах дає це помітити.
        if _usage().get(code, 0):
            audit_logger.warning(
                'Event type %r was used by a course created during deletion; '
                'those courses now show a raw code', code,
            )
    return redirect(url_for('admin.event_types_list'))
