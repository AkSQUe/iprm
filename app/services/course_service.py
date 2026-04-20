"""Course + CourseInstance CRUD business logic."""
import logging

from flask import request

from app.extensions import db
from app.models.course import Course
from app.models.program_block import ProgramBlock
from app.utils import slugify

logger = logging.getLogger(__name__)


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
    course.title = form.title.data.strip()
    course.subtitle = form.subtitle.data
    course.short_description = form.short_description.data
    course.description = form.description.data
    course.event_type = form.event_type.data
    course.hero_image = form.hero_image.data
    course.card_image = form.card_image.data
    course.target_audience = lines_to_list(form.target_audience_text.data)
    course.tags = lines_to_list(form.tags_text.data)
    course.speaker_info = form.speaker_info.data
    course.agenda = form.agenda.data
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
    instance.location = form.location.data
    instance.online_link = form.online_link.data
    instance.trainer_id = form.trainer_id.data or None
    instance.status = form.status.data


def save_program_blocks_for_course(course):
    """Sync program blocks from form (block_N_heading, block_N_items) to a Course."""
    existing_ids = {b.id for b in course.program_blocks}
    seen_ids = set()

    idx = 0
    while True:
        heading = request.form.get(f'block_{idx}_heading', '').strip()
        if not heading and f'block_{idx}_heading' not in request.form:
            break
        if heading:
            block_id_str = request.form.get(f'block_{idx}_id', '')
            items_text = request.form.get(f'block_{idx}_items', '')
            items = lines_to_list(items_text)
            block_id = int(block_id_str) if block_id_str else None

            if block_id and block_id in existing_ids:
                block = db.session.get(ProgramBlock, block_id)
                block.heading = heading
                block.items = items
                block.sort_order = idx
                seen_ids.add(block_id)
            else:
                block = ProgramBlock(
                    course=course,
                    heading=heading,
                    items=items,
                    sort_order=idx,
                )
                db.session.add(block)
        idx += 1

    for old_id in existing_ids - seen_ids:
        old_block = db.session.get(ProgramBlock, old_id)
        if old_block:
            db.session.delete(old_block)


def generate_course_slug(title, exclude_id=None):
    """Returns (slug, error) tuple. error is None if slug is unique."""
    slug = slugify(title)
    query = Course.query.filter_by(slug=slug)
    if exclude_id:
        query = query.filter(Course.id != exclude_id)
    if query.first():
        return slug, 'Курс з таким slug вже існує'
    return slug, None
