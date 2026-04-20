"""Course + CourseInstance CRUD business logic."""
import logging
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


# ========== Shared helpers (text <-> list/faq conversions) ==========

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


def faq_text_to_list(text):
    """Parse FAQ text into list of {question, answer} dicts.

    Format: blocks separated by empty lines, first line = question, rest = answer.
    """
    if not text:
        return []
    blocks = text.strip().split('\n\n')
    faq = []
    for block in blocks:
        lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
        if len(lines) >= 2:
            faq.append({'question': lines[0], 'answer': '\n'.join(lines[1:])})
    return faq


def faq_list_to_text(items):
    """Convert list of {question, answer} dicts to editable text."""
    if not items:
        return ''
    blocks = []
    for item in items:
        q = item.get('question', '')
        a = item.get('answer', '')
        blocks.append(f'{q}\n{a}' if a else q)
    return '\n\n'.join(blocks)


class InvalidStatusTransition(ValueError):
    """Невалідний перехід між статусами проведення."""


def change_instance_status(instance, new_status):
    """Змінити статус проведення з валідацією переходу.

    Повертає tuple (old_status, new_status). Кидає InvalidStatusTransition
    якщо перехід заборонений. Коміт — відповідальність caller.
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

    instance.status = new_status
    return old_status, new_status


def populate_course_from_form(course, form):
    """Map CourseForm data onto a Course model instance."""
    course.title = (form.title.data or '').strip()
    course.subtitle = _clean_text(form.subtitle.data)
    course.short_description = _clean_text(form.short_description.data)
    course.description = _clean_text(form.description.data)
    course.event_type = form.event_type.data
    course.hero_image = _clean_text(form.hero_image.data)
    course.card_image = _clean_text(form.card_image.data)
    course.target_audience = lines_to_list(form.target_audience_text.data)
    course.tags = lines_to_list(form.tags_text.data)
    course.speaker_info = _clean_text(form.speaker_info.data)
    course.agenda = _clean_text(form.agenda.data)
    course.faq = faq_text_to_list(form.faq_text.data)
    course.base_price = form.base_price.data or 0
    course.cpd_points = form.cpd_points.data
    course.max_participants = form.max_participants.data
    course.trainer_id = form.trainer_id.data or None
    course.is_active = form.is_active.data
    course.is_featured = form.is_featured.data


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
    instance.online_link = _clean_text(form.online_link.data)
    instance.trainer_id = form.trainer_id.data or None
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


def save_program_blocks_for_course(course, blocks_data):
    """Синхронізувати program_blocks курсу зі структурованим списком blocks_data.

    blocks_data: результат extract_program_blocks_from_form().
    Існуючі блоки (за id) оновлюються, нові створюються, відсутні — видаляються.
    """
    existing_ids = {b.id for b in course.program_blocks}
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
                course=course,
                heading=heading,
                items=items,
                sort_order=idx,
            ))

    for old_id in existing_ids - seen_ids:
        old_block = db.session.get(ProgramBlock, old_id)
        if old_block:
            db.session.delete(old_block)


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
        hero_image=source.hero_image,
        card_image=source.card_image,
        target_audience=list(source.target_audience or []),
        tags=list(source.tags or []),
        speaker_info=source.speaker_info,
        agenda=source.agenda,
        faq=[dict(item) for item in (source.faq or [])],
        base_price=source.base_price,
        cpd_points=source.cpd_points,
        max_participants=source.max_participants,
        trainer_id=source.trainer_id,
        is_active=False,
        is_featured=False,
        created_by=created_by_id,
    )

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
