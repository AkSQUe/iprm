"""Course + CourseInstance CRUD business logic."""
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import case, func

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.course_request import CourseRequest
from app.models.program_block import ProgramBlock
from app.utils import slugify

logger = logging.getLogger(__name__)


def _clean_text(value):
    """Strip-нути значення, повернути None якщо порожнє."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def _opt_media_id(value):
    """Рядок/int media_id -> існуючий MediaFile.id або None (валідуємо наявність)."""
    from app.models.media_file import MediaFile
    s = str(value or '').strip()
    if s.isdigit() and db.session.get(MediaFile, int(s)):
        return int(s)
    return None


def attach_course_media(course):
    """Прив'язати MediaFile (hero/card) до курсу після збереження.

    Виставляє entity_type/entity_id/usage_type для зображень курсу. Відв'язані
    не видаляємо автоматично. Ідемпотентно."""
    from app.models.media_file import MediaFile
    assignments = {}
    if course.hero_media_id:
        assignments[course.hero_media_id] = 'hero'
    if course.card_media_id:
        assignments.setdefault(course.card_media_id, 'card')
    if not assignments:
        return
    from app.services import media_service
    rows = MediaFile.query.filter(MediaFile.id.in_(list(assignments))).all()
    for m in rows:
        m.entity_type = 'course'
        m.entity_id = course.id
        m.usage_type = assignments[m.id]
        # Читабельне ім'я файлу: {slug}-hero / {slug}-card (hero/card -- по одному).
        media_service.rename_for_entity(m, course.slug)
    try:
        db.session.commit()
    except Exception:
        logger.exception('Failed to attach media to course %s', course.id)
        db.session.rollback()


def parse_gallery_entries(raw):
    """Розібрати JSON редактора галереї у [{media_id, caption}].

    Приходить із прихованого поля форми, тому все, що не схоже на запис,
    тихо відкидаємо: зіпсований JSON не має валити збереження курсу.
    """
    import json

    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning('Invalid gallery JSON in form, ignored')
        return []
    if not isinstance(data, list):
        return []
    entries = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            media_id = int(item.get('media_id'))
        except (TypeError, ValueError):
            continue
        caption = (item.get('caption') or '').strip()[:255] or None
        entries.append({'media_id': media_id, 'caption': caption})
    return entries


def gallery_to_json(media_files):
    """Серіалізувати галерею для редактора в адмінці.

    Крім media_id і підпису віддаємо мініатюру: інакше редактор мусив би
    ходити по URL кожного файла окремим запитом.
    """
    import json

    return json.dumps([
        {
            'media_id': m.id,
            'caption': m.caption or '',
            'thumb': m.variant_url('thumb'),
        }
        for m in media_files
    ], ensure_ascii=False)


def save_gallery(owner, entries, entity_type):
    """Синхронізувати галерею сутності з тим, що прийшло з форми.

    Галерея живе не окремою таблицею, а в медіа-реєстрі: MediaFile із
    usage_type='gallery' і порядком у sort_order. Тому "зберегти" означає
    переставити прапорці на рядках реєстру.

    Прибрані з галереї файли НЕ видаляємо і не деактивуємо -- лише знімаємо
    прив'язку. Файл міг використовуватись деінде, а видалення з реєстру --
    окрема свідома дія в медіа-бібліотеці.

    Коміт -- на caller-ові.
    """
    from app.models.media_file import MediaFile
    from app.services import media_service

    wanted = {e['media_id']: e for e in entries}

    current = MediaFile.query.filter_by(
        entity_type=entity_type, entity_id=owner.id, usage_type='gallery',
    ).all()
    for media in current:
        if media.id not in wanted:
            media.entity_type = None
            media.entity_id = None
            media.usage_type = 'main'
            media.sort_order = 0

    if not wanted:
        return

    rows = {m.id: m for m in MediaFile.query.filter(
        MediaFile.id.in_(list(wanted))).all()}
    for index, entry in enumerate(entries, start=1):
        media = rows.get(entry['media_id'])
        if not media:
            continue
        media.entity_type = entity_type
        media.entity_id = owner.id
        media.usage_type = 'gallery'
        media.sort_order = index
        media.caption = entry['caption']
        # Читабельне ім'я файлу: {slug}-gallery-N -- як у дописах блогу.
        media_service.rename_for_entity(media, owner.slug, index)


# ========== Shared helpers (text <-> list/faq conversions) ==========

# Порожній рядок між блоками FAQ (переноси вже нормалізовані до \n);
# "порожній" рядок може містити пробіли чи таби.
_FAQ_BLOCK_SEPARATOR = re.compile(r'\n[ \t]*\n+')


def lines_to_list(text):
    """Convert newline-separated text to a list of stripped strings."""
    if not text:
        return []
    return [line.strip() for line in text.strip().splitlines() if line.strip()]


def list_to_lines(items):
    """Convert a list of strings to newline-separated text."""
    if not items:
        return ''
    return '\n'.join(items)


def blocks_text_to_list(text, head_key, body_key):
    """Розібрати текст у список {head_key, body_key}.

    Формат: блоки, розділені порожнім рядком; перший рядок -- заголовок,
    решта -- тіло. Одна механіка для FAQ і для карток переваг: редактор
    вводить їх однаково, тож і парсер має бути один.

    Перед розбиттям нормалізуємо переноси: браузер надсилає textarea з CRLF,
    тож літерал '\\n\\n' не збігався б ніколи і весь текст ставав одним
    блоком. Порожній рядок-роздільник може містити пробіли чи таби.
    """
    if not text:
        return []
    normalized = text.replace('\r\n', '\n').replace('\r', '\n')
    blocks = _FAQ_BLOCK_SEPARATOR.split(normalized.strip())
    out = []
    for block in blocks:
        lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
        if lines:
            out.append({head_key: lines[0], body_key: '\n'.join(lines[1:])})
    return out


def blocks_list_to_text(items, head_key, body_key):
    """Зворотне до blocks_text_to_list."""
    if not items:
        return ''
    blocks = []
    for item in items:
        head = item.get(head_key, '')
        body = item.get(body_key, '')
        blocks.append(f'{head}\n{body}' if body else head)
    return '\n\n'.join(blocks)


def faq_text_to_list(text):
    """FAQ як список {question, answer}."""
    return blocks_text_to_list(text, 'question', 'answer')


def faq_list_to_text(items):
    """FAQ у редагований текст."""
    return blocks_list_to_text(items, 'question', 'answer')


# Пари "значення | підпис" -- смуга цифр довіри й короткі цифри тренера.
# Роздільник саме "|": тире й дефіси зустрічаються всередині самих значень
# ("13-15 років"), а вертикальна риска в такому тексті не трапляється.
_PAIR_SEPARATOR = '|'


def pairs_text_to_list(text):
    """Розібрати рядки "значення | підпис" у список {value, label}.

    Рядок без роздільника стає значенням без підпису: краще показати саму
    цифру, ніж мовчки викинути введене.
    """
    if not text:
        return []
    out = []
    for line in text.replace('\r\n', '\n').replace('\r', '\n').splitlines():
        line = line.strip()
        if not line:
            continue
        value, _, label = line.partition(_PAIR_SEPARATOR)
        value = value.strip()
        if value:
            out.append({'value': value, 'label': label.strip()})
    return out


def pairs_list_to_text(items):
    """Зворотне до pairs_text_to_list."""
    if not items:
        return ''
    lines = []
    for item in items:
        value = (item or {}).get('value', '')
        label = (item or {}).get('label', '')
        lines.append(f'{value} {_PAIR_SEPARATOR} {label}' if label else str(value))
    return '\n'.join(lines)


class InvalidStatusTransition(ValueError):
    """Невалідний перехід між статусами проведення."""


#: Статуси, які партнерський API віддає назовні (`ALLOWED_STATUSES` в
#: `app/api/v1/events.py`). `draft` серед них немає навмисно: чернетка — це
#: проведення, якого для партнера ЩЕ не існує.
PARTNER_VISIBLE_STATUSES = ('published', 'active', 'completed', 'cancelled')


def live_registration_count(instance):
    """Скільки живих реєстрацій тримає проведення. Незбережене — нуль."""
    from app.models.registration import EventRegistration

    if instance is None or instance.id is None:
        return 0
    return (
        EventRegistration.query
        .filter(EventRegistration.instance_id == instance.id,
                EventRegistration.status != 'cancelled')
        .count()
    )


def ensure_status_change_allowed(instance, new_status):
    """Заборонити ховати від партнерів проведення, на яке вже записались.

    ЩО ЦЕ ЛОВИТЬ. Переведення в `draft` проведення, яке партнер уже бачив.
    Для нього це не «стало чернеткою», а «зникло»: `draft` не входить у
    `PARTNER_VISIBLE_STATUSES`, тобто ендпоінт `/events` не віддає такий
    рядок НІ В ЯКОМУ запиті — його не можна навіть попросити.

    ЧОМУ ЦЕ ВАРТЕ ОКРЕМОГО ГВАРДА. 31.08.2026 в дзеркалі MM Medic не
    вистачило 25 реєстрацій, і три з них — саме через це. Проведення 52
    (5 вересня, курс «Терапевтична сила плазми») перевели в `draft` уже
    ПІСЛЯ того, як на нього записалась і заплатила людина: 1000 грн через
    LiqPay. Партнер побачив зникнення проведення, вирішив, що ми його
    видалили, прибрав його в себе — і реєстрація пішла слідом по CASCADE.
    На проведенні 37 так само загубилась оплата на 7500 грн.

    ЩО РОБИТИ НАТОМІСТЬ. `cancelled`. Він у списку видимих саме для цього:
    партнер, який будує розклад, мусить ПОКАЗАТИ «Захід скасовано», а не
    мовчки прибрати рядок — інакше скасування й видалення виглядають для
    нього однаково. Ця відмінність описана в `api/v1/events.py` і тепер
    підкріплена перевіркою, а не лише коментарем.

    Зворотний напрямок (`draft` -> будь-що) не обмежується: сховати можна
    лише те, що ще нікому не показували.
    """
    if new_status != 'draft':
        return
    if instance is None or instance.status == 'draft':
        return
    if instance.status not in PARTNER_VISIBLE_STATUSES:
        return

    live = live_registration_count(instance)
    if live:
        raise InvalidStatusTransition(
            f'На проведення записано {live} — у «Чернетку» його повернути '
            f'не можна: для партнерів воно просто зникне разом із їхніми '
            f'копіями реєстрацій. Щоб зняти захід, оберіть «Скасовано».'
        )


def change_instance_status(instance, new_status):
    """Змінити статус проведення з валідацією переходу.

    Повертає tuple (old_status, new_status). Кидає InvalidStatusTransition
    якщо перехід заборонений або якщо проведення ховають від партнерів разом
    із чужими реєстраціями (`ensure_status_change_allowed`). Коміт —
    відповідальність caller.
    """
    valid = dict(CourseInstance.STATUSES)
    if new_status not in valid:
        raise InvalidStatusTransition(f'Невідомий статус: {new_status}')

    old_status = instance.status
    if old_status == new_status:
        return old_status, new_status

    if not instance.can_transition_to(new_status):
        raise InvalidStatusTransition(
            f'Перехід {old_status} -> {new_status} заборонений'
        )

    ensure_status_change_allowed(instance, new_status)

    instance.status = new_status
    return old_status, new_status


def populate_course_from_form(course, form):
    """Map CourseForm data onto a Course model instance."""
    course.title = (form.title.data or '').strip()
    course.subtitle = _clean_text(form.subtitle.data)
    course.short_description = _clean_text(form.short_description.data)
    course.description = _clean_text(form.description.data)
    course.event_type = form.event_type.data
    course.hero_media_id = _opt_media_id(form.hero_media_id.data)
    course.card_media_id = _opt_media_id(form.card_media_id.data)
    course.target_audience = lines_to_list(form.target_audience_text.data)
    course.tags = lines_to_list(form.tags_text.data)
    course.speaker_info = _clean_text(form.speaker_info.data)
    course.agenda = _clean_text(form.agenda.data)
    course.faq = faq_text_to_list(form.faq_text.data)
    course.final_cta_text = _clean_text(form.final_cta_text.data)
    course.proof_stats = pairs_text_to_list(form.proof_stats_text.data)
    course.benefits = blocks_text_to_list(form.benefits_text.data, 'title', 'text')
    course.practice_note_title = _clean_text(form.practice_note_title.data)
    course.practice_note_text = _clean_text(form.practice_note_text.data)
    course.gallery_intro = _clean_text(form.gallery_intro.data)
    course.base_price = form.base_price.data or 0
    course.difficulty_level = form.difficulty_level.data or None
    course.roi_hint = _clean_text(form.roi_hint.data)
    course.cpd_points = form.cpd_points.data
    course.max_participants = form.max_participants.data
    course.bpr_event_number = _clean_text(form.bpr_event_number.data)
    course.bpr_specialties = _clean_text(form.bpr_specialties.data)
    course.bpr_lecturer_points = form.bpr_lecturer_points.data
    course.trainer_id = form.trainer_id.data or None
    course.is_active = form.is_active.data
    course.is_featured = form.is_featured.data
    course.is_pinned = form.is_pinned.data
    course.sort_order = form.sort_order.data if form.sort_order.data is not None else 0


def copy_course_tariffs_to_instance(instance, replace=False):
    """Скопіювати активні шаблонні тарифи курсу в проведення (copy-on-create).

    Копіюються лише шаблони, що пасують формату проведення (гібрид отримує
    всі, NULL-формат пасує будь-якому). instance_tariffs -- джерело істини
    для продажу; подальші зміни шаблонів існуючі проведення не чіпають.

    Args:
        instance: CourseInstance (course_id має бути виставлений; commit --
            на caller-ові, функція лише мутує сесію).
        replace: True -- спершу прибрати поточні тарифи проведення
            (кнопка "Взяти з курсу"): тарифи, на які вже посилаються
            реєстрації, деактивуються (історія показів лишиться), решта
            видаляється.

    Returns:
        Кількість скопійованих тарифів.
    """
    from app.models.instance_tariff import InstanceTariff
    from app.models.registration import EventRegistration

    # Джерело істини "скільки скопіюється" -- спільна з кнопкою "Взяти з курсу"
    # властивість (активні шаблони курсу, що пасують формату проведення).
    matching = instance.copyable_course_tariffs

    if replace:
        for tariff in list(instance.tariffs):
            referenced = (
                db.session.query(EventRegistration.id)
                .filter(EventRegistration.tariff_id == tariff.id)
                .first()
            ) is not None
            if referenced:
                tariff.is_active = False
            else:
                db.session.delete(tariff)

    for template in matching:
        db.session.add(InstanceTariff(
            instance_id=instance.id,
            name=template.name,
            description=template.description,
            price=template.price,
            # Формат тягнемо з шаблону: на гібридному проведенні саме він
            # вирішує, чи показувати учаснику підтвердження очної участі.
            event_format=template.event_format,
            sort_order=template.sort_order,
            is_active=True,
            # Переклади (ru/en) успадковуються від шаблону курсу, як і решта
            # полів; подальші правки шаблону проведення не зачіпають.
            translations=template.translations,
        ))
    return len(matching)


def populate_instance_from_form(instance, form):
    """Map CourseInstanceForm data onto a CourseInstance model instance."""
    instance.course_id = form.course_id.data
    instance.start_date = form.start_date.data
    instance.end_date = form.end_date.data
    instance.event_format = form.event_format.data
    instance.price = form.price.data
    instance.cpd_points = form.cpd_points.data
    instance.max_participants = form.max_participants.data
    instance.location = _clean_text(form.location.data)
    # 0 -- це «Місце уточнюється» з пікера; у БД воно має лягти як NULL, а не
    # як неіснуючий id міста.
    instance.city_id = form.city_id.data or None
    instance.online_link = _clean_text(form.online_link.data)
    instance.trainer_id = form.trainer_id.data or None
    # Гвард і тут, а не лише в `change_instance_status`: форма
    # редагування писала статус напряму, тобто повз ОБИДВІ перевірки.
    # Половина гварда гірша за його відсутність — вона створює
    # враження, що шлях закритий.
    ensure_status_change_allowed(instance, form.status.data)
    instance.status = form.status.data


def extract_program_blocks_from_form(form_data):
    """Розпарсити flat form-поля (block_N_id, block_N_heading, block_N_items)
    у структурований список.

    Повертає список dicts: [{'id': int|None, 'heading': str, 'items': [str, ...]}, ...]
    Блоки без heading пропускаються. Порядок збережено за індексом у формі.
    Невалідні block_N_id (не-число) трактуються як None -- блок створиться
    заново замість UPDATE, але форма не падає на 500.
    """
    blocks = []
    idx = 0
    while True:
        if f'block_{idx}_heading' not in form_data:
            break
        heading = (form_data.get(f'block_{idx}_heading') or '').strip()
        if heading:
            block_id_str = form_data.get(f'block_{idx}_id', '')
            items_text = form_data.get(f'block_{idx}_items', '')
            block_id = None
            if block_id_str:
                try:
                    block_id = int(block_id_str)
                except (ValueError, TypeError):
                    logger.warning(
                        'Invalid block_%d_id=%r -- ignoring, will create new block',
                        idx, block_id_str,
                    )
            blocks.append({
                'id': block_id,
                'heading': heading,
                'items': lines_to_list(items_text),
            })
        idx += 1
    return blocks


def _save_program_blocks(owner, blocks_data, relation):
    """Синхронізувати program_blocks сутності зі списком blocks_data.

    blocks_data: результат extract_program_blocks_from_form().
    Існуючі блоки (за id) оновлюються, нові створюються, відсутні — видаляються.

    relation -- ім'я зв'язку, яким новий блок кріпиться до власника
    ('course' або 'online_course'). Блоки поліморфні, і CHECK у БД вимагає
    рівно одного власника, тож ім'я передається явно, а не вгадується.
    """
    existing_ids = {b.id for b in owner.program_blocks}
    seen_ids = set()

    for idx, block_data in enumerate(blocks_data):
        block_id = block_data.get('id')
        heading = block_data['heading']
        items = block_data.get('items', [])

        if block_id and block_id in existing_ids:
            block = db.session.get(ProgramBlock, block_id)
            block.heading = heading
            block.items = items
            block.sort_order = idx
            seen_ids.add(block_id)
        else:
            db.session.add(ProgramBlock(
                heading=heading,
                items=items,
                sort_order=idx,
                **{relation: owner},
            ))

    for old_id in existing_ids - seen_ids:
        old_block = db.session.get(ProgramBlock, old_id)
        if old_block:
            db.session.delete(old_block)


def save_program_blocks_for_course(course, blocks_data):
    """Блоки програми офлайнового курсу."""
    _save_program_blocks(course, blocks_data, 'course')


def save_program_blocks_for_online_course(course, blocks_data):
    """Блоки програми онлайн-курсу."""
    _save_program_blocks(course, blocks_data, 'online_course')


def clone_course(source, created_by_id):
    """Створити чернетку-копію курсу з усіма блоками програми.

    Новий курс: slug + '-copy[-N]', is_active=False, title + ' (копія)'.
    Не копіює instances та requests.
    """
    base_slug = f'{source.slug}-copy'
    slug = base_slug
    counter = 2
    while Course.query.filter_by(slug=slug).first():
        slug = f'{base_slug}-{counter}'
        counter += 1

    clone = Course(
        slug=slug,
        title=f'{source.title} (копія)',
        subtitle=source.subtitle,
        short_description=source.short_description,
        description=source.description,
        event_type=source.event_type,
        hero_media_id=source.hero_media_id,
        card_media_id=source.card_media_id,
        target_audience=list(source.target_audience or []),
        tags=list(source.tags or []),
        speaker_info=source.speaker_info,
        agenda=source.agenda,
        faq=[dict(item) for item in (source.faq or [])],
        final_cta_text=source.final_cta_text,
        base_price=source.base_price,
        difficulty_level=source.difficulty_level,
        roi_hint=source.roi_hint,
        cpd_points=source.cpd_points,
        max_participants=source.max_participants,
        trainer_id=source.trainer_id,
        is_active=False,
        is_featured=False,
        created_by=created_by_id,
    )

    from app.models.course_tariff import CourseTariff
    for tariff in source.default_tariffs:
        clone.default_tariffs.append(CourseTariff(
            name=tariff.name,
            description=tariff.description,
            price=tariff.price,
            event_format=tariff.event_format,
            sort_order=tariff.sort_order,
            is_active=tariff.is_active,
        ))

    for block in source.program_blocks:
        clone.program_blocks.append(ProgramBlock(
            heading=block.heading,
            items=list(block.items or []),
            sort_order=block.sort_order,
        ))

    db.session.add(clone)
    return clone


def generate_course_slug(title, exclude_id=None):
    """Returns (slug, error) tuple. error is None if slug is unique."""
    slug = slugify(title)
    query = Course.query.filter_by(slug=slug)
    if exclude_id:
        query = query.filter(Course.id != exclude_id)
    if query.first():
        return slug, 'Курс з таким slug вже існує'
    return slug, None


def course_stats(course_ids):
    """Aggregate counts per course у ОДНОМУ запиті (замість N+1 per-property).

    Args:
        course_ids: iterable Course.id для яких обчислити статистику.

    Returns:
        dict {course_id: {'upcoming': int, 'past': int, 'total': int,
                          'pending_requests': int}}

    Порожні курси не включаються в dict -- caller має використати
    `stats.get(course_id, {'upcoming': 0, ...})`.
    """
    if not course_ids:
        return {}

    now = datetime.now(timezone.utc)

    # Один агрегат на CourseInstance + conditional COUNT для upcoming / past
    instance_rows = (
        db.session.query(
            CourseInstance.course_id,
            func.count(CourseInstance.id).label('total'),
            func.count(
                case(
                    (
                        db.and_(
                            CourseInstance.status.in_(('published', 'active')),
                            db.or_(
                                CourseInstance.start_date.is_(None),
                                CourseInstance.start_date >= now,
                            ),
                        ),
                        1,
                    )
                )
            ).label('upcoming'),
            func.count(
                case(
                    (
                        db.or_(
                            CourseInstance.status == 'completed',
                            db.and_(
                                CourseInstance.status.in_(('published', 'active')),
                                CourseInstance.start_date.isnot(None),
                                CourseInstance.start_date < now,
                            ),
                        ),
                        1,
                    )
                )
            ).label('past'),
        )
        .filter(CourseInstance.course_id.in_(course_ids))
        .group_by(CourseInstance.course_id)
        .all()
    )

    # Окремий агрегат для pending CourseRequest
    request_rows = (
        db.session.query(
            CourseRequest.course_id,
            func.count(CourseRequest.id),
        )
        .filter(
            CourseRequest.course_id.in_(course_ids),
            CourseRequest.status == 'pending',
        )
        .group_by(CourseRequest.course_id)
        .all()
    )
    pending_by_course = dict(request_rows)

    result = {}
    for course_id, total, upcoming, past in instance_rows:
        result[course_id] = {
            'total': total,
            'upcoming': upcoming,
            'past': past,
            'pending_requests': pending_by_course.get(course_id, 0),
        }
    # Курси без проведень: додаємо записи з нулями для instance-counts,
    # але з реальним pending_requests count
    for course_id, pending in pending_by_course.items():
        if course_id not in result:
            result[course_id] = {
                'total': 0, 'upcoming': 0, 'past': 0,
                'pending_requests': pending,
            }

    return result
