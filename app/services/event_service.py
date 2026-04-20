"""Shared text/list helpers.

Після переходу на Course+CourseInstance модель Event керує лише legacy-
даними (read-only через /admin/events/legacy та XLSX-експорт). Функції
`populate_event_from_form`, `save_program_blocks`, `change_status`,
`InvalidStatusTransition` видалено -- їх замінили course_service.*

Залишені helpers (`lines_to_list`, `list_to_lines`, `faq_text_to_list`,
`faq_list_to_text`) використовуються і course_service'ом, і Excel-
сервісом, тому лишаються у цьому модулі.
"""
import logging

from app.models.event import Event
from app.utils import slugify

logger = logging.getLogger(__name__)


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


def generate_slug(title, exclude_id=None):
    """Generate a unique slug for an Event (legacy -- XLSX-імпорт).

    Returns (slug, error_message) tuple. error_message is None if slug is unique.
    """
    slug = slugify(title)
    query = Event.query.filter_by(slug=slug)
    if exclude_id:
        query = query.filter(Event.id != exclude_id)
    if query.first():
        return slug, 'Захід з таким slug вже існує'
    return slug, None
