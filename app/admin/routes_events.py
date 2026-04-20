"""Legacy admin routes для таблиці events.

Всі CRUD-операції перенесено в /admin/courses (нова модель Course).
Тут залишено:
  * /admin/events -- 301 redirect на /admin/courses (bookmark-сумісність)
  * /admin/events/legacy -- read-only перегляд legacy-даних для аудиту
"""
import logging

from flask import render_template, redirect, url_for
from sqlalchemy.orm import joinedload

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.models.event import Event


logger = logging.getLogger(__name__)


@admin_bp.route('/events')
@admin_required
def events_list():
    """Legacy redirect -- усі заходи керуються через /admin/courses."""
    return redirect(url_for('admin.courses_list'), code=301)


@admin_bp.route('/events/legacy')
@admin_required
def events_list_legacy():
    """Read-only перегляд legacy-даних таблиці events.

    Використовується для аудиту / порівняння з мігрованими даними
    в courses+course_instances. Не дозволяє редагувати.
    """
    reg_count = Event.with_registration_count()
    rows = db.session.query(Event, reg_count).options(
        joinedload(Event.trainer),
    ).order_by(Event.created_at.desc()).all()

    events = []
    for event, count in rows:
        event._cached_reg_count = count
        events.append(event)

    return render_template('admin/events_legacy.html', events=events)
