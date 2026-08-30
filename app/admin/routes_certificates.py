"""Адмінський реєстр виданих сертифікатів: список, фільтри, xlsx-звіт.

Видача, відкликання й повторна відправка живуть у routes_registrations --
вони стосуються реєстрації, а не реєстру.
"""
import logging

from flask import render_template
from flask_login import current_user
from sqlalchemy import case, extract, func
from sqlalchemy.orm import joinedload

from app.admin import _listing, admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.services import xlsx_reports
from app.models.certificate import Certificate
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.user import User

audit_logger = logging.getLogger('audit')


_CERT_STATES = {'valid': 'Дійсні', 'revoked': 'Відкликані'}


def _certificate_filters():
    """Фільтри реєстру сертифікатів -- спільні для сторінки й експорту."""
    return {
        'q': _listing.text_arg('q'),
        'state': _listing.choice_arg('state', _CERT_STATES),
        'course_id': _listing.int_arg('course_id'),
        'year': _listing.int_arg('year'),
        'date_from': _listing.date_arg('date_from'),
        'date_to': _listing.date_arg('date_to'),
        'per_page': _listing.choice_arg('per_page', _listing.PER_PAGE_CHOICES),
    }


def _certificates_query(filters):
    """Сертифікати під фільтри, найновіші першими."""

    query = Certificate.query.options(
        joinedload(Certificate.user),
        joinedload(Certificate.issued_by),
    )
    if filters['q']:
        # Номер і ПІБ -- знімки на самому сертифікаті; email живе в User,
        # тож приєднуємо власника (inner join безпечний: user_id NOT NULL).
        query = query.join(User, Certificate.user_id == User.id)
        query = _listing.apply_search(query, filters['q'], [
            Certificate.number, Certificate.recipient_name,
            Certificate.event_title, User.email,
        ])
    if filters['state']:
        query = query.filter(Certificate.revoked.is_(filters['state'] == 'revoked'))
    if filters['course_id']:
        # Курс живе через реєстрацію -> проведення (на сертифікаті лишився
        # лише текстовий знімок назви заходу).
        query = query.join(
            EventRegistration, Certificate.registration_id == EventRegistration.id,
        ).join(
            CourseInstance, EventRegistration.instance_id == CourseInstance.id,
        ).filter(CourseInstance.course_id == filters['course_id'])
    if filters['year']:
        query = query.filter(extract('year', Certificate.issued_at) == filters['year'])
    query = _listing.apply_date_range(
        query, Certificate.issued_at, filters['date_from'], filters['date_to'],
    )
    return query.order_by(Certificate.issued_at.desc())


def _certificate_stats():
    """Лічильники по ВСІХ сертифікатах: шапка не має стрибати від фільтра."""

    total, revoked = db.session.query(
        func.count(Certificate.id),
        func.count(case((Certificate.revoked.is_(True), 1))),
    ).one()
    return {'total': total, 'active': total - revoked, 'revoked': revoked}


@admin_bp.route('/certificates')
@admin_required
def certificates():

    filters = _certificate_filters()
    # Роки беремо з даних: порожній рік у списку -- пастка «фільтр нічого не
    # знайшов», а не вибір.
    years = sorted({
        int(y) for (y,) in db.session.query(
            extract('year', Certificate.issued_at),
        ).distinct().all() if y is not None
    }, reverse=True)
    # Реєстр росте після кожного заходу, тож сторінками; експорт лишається
    # по всьому зрізу -- пагінація це властивість екрана, а не звіту.
    pagination = _certificates_query(filters).paginate(
        page=_listing.page_arg(),
        per_page=_listing.per_page_arg(), error_out=False,
    )
    return render_template(
        'admin/certificates.html',
        per_page_options=_listing.PER_PAGE_OPTIONS,
        certificates=pagination.items,
        pagination=pagination,
        stats=_certificate_stats(),
        filters=filters,
        filter_args=_listing.filter_args(filters),
        state_options=list(_CERT_STATES.items()),
        course_options=[
            (c.id, c.title)
            for c in db.session.query(Course).order_by(Course.title).all()
        ],
        year_options=[(y, str(y)) for y in years],
    )


@admin_bp.route('/certificates/export')
@admin_required
def certificates_export():
    """Експорт реєстру сертифікатів у xlsx з урахуванням активних фільтрів."""

    filters = _certificate_filters()
    # Стелю рядків міряємо COUNT-ом ДО вибірки: інакше зріз спершу
    # піднімався б у пам'ять цілком і лише потім отримував відмову.
    certs, refusal = _listing.export_query(
        _certificates_query(filters), 'admin.certificates', **_listing.filter_args(filters),
    )
    if refusal:
        return refusal
    course = (
        db.session.get(Course, filters['course_id'])
        if filters['course_id'] else None
    )
    summary = _listing.export_summary(
        [
            ('Пошук', filters['q'] or '–'),
            ('Стан', _CERT_STATES.get(filters['state'], 'Усі')),
            ('Курс', course.title if course else 'Усі'),
            ('Рік видачі', filters['year'] or 'Усі'),
            ('Дата видачі', _listing.date_range_label(filters)),
        ],
        len(certs),
    )
    audit_logger.info(
        'Admin %s exported certificates xlsx (%d rows, filters=%s)',
        current_user.email, len(certs), filters,
    )
    return _listing.xlsx_export(
        certs, 'certificates',
        lambda: xlsx_reports.export_certificates_xlsx(certs, applied_filters=summary),
        'admin.certificates', **_listing.filter_args(filters),
    )
