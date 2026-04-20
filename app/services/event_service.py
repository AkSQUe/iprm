"""Event CRUD business logic service."""
import logging

from flask import request

from app.extensions import db
from app.models.event import Event
from app.models.program_block import ProgramBlock
from app.utils import slugify

logger = logging.getLogger(__name__)


class InvalidStatusTransition(ValueError):
    """Невалідний перехід між статусами заходу."""


def change_status(event, new_status):
    """Змінити статус заходу з валідацією переходу.

    Повертає tuple (old_status, new_status). Кидає InvalidStatusTransition
    якщо перехід заборонений або статус невідомий. Коміт — відповідальність caller.
    """
    valid = dict(Event.STATUSES)
    if new_status not in valid:
        raise InvalidStatusTransition(f'Невідомий статус: {new_status}')

    old_status = event.status
    if old_status == new_status:
        return old_status, new_status

    if not event.can_transition_to(new_status):
        raise InvalidStatusTransition(
            f'Перехід {old_status} -> {new_status} заборонений'
        )

    event.status = new_status
    return old_status, new_status


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


def populate_event_from_form(event, form):
    """Map form data onto an Event model instance."""
    event.title = form.title.data.strip()
    event.subtitle = form.subtitle.data
    event.short_description = form.short_description.data
    event.description = form.description.data
    event.event_type = form.event_type.data
    event.event_format = form.event_format.data
    event.status = form.status.data
    event.start_date = form.start_date.data
    event.end_date = form.end_date.data
    event.max_participants = form.max_participants.data
    event.price = form.price.data or 0
    event.location = form.location.data
    event.online_link = form.online_link.data
    event.hero_image = form.hero_image.data
    event.card_image = form.card_image.data
    event.cpd_points = form.cpd_points.data
    event.trainer_id = form.trainer_id.data or None
    event.target_audience = lines_to_list(form.target_audience_text.data)
    event.tags = lines_to_list(form.tags_text.data)
    event.speaker_info = form.speaker_info.data
    event.agenda = form.agenda.data
    event.faq = faq_text_to_list(form.faq_text.data)
    event.is_featured = form.is_featured.data


def save_program_blocks(event):
    """Sync program blocks from form data (block_N_heading, block_N_items)."""
    existing_ids = {b.id for b in event.program_blocks}
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
                    event=event,
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


def generate_slug(title, exclude_id=None):
    """Generate a unique slug for an event.

    Returns (slug, error_message) tuple. error_message is None if slug is unique.
    """
    slug = slugify(title)
    query = Event.query.filter_by(slug=slug)
    if exclude_id:
        query = query.filter(Event.id != exclude_id)
    if query.first():
        return slug, 'Захід з таким slug вже існує'
    return slug, None
