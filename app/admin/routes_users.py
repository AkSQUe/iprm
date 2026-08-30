"""Адмінський список користувачів: фільтри, пошук, xlsx-звіт, адмін-права."""
import logging

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy.orm import joinedload

from app.admin import _listing, admin_bp
from app.admin.decorators import admin_required
from app.extensions import db
from app.services import xlsx_reports
from app.models.medical_profile import MedicalProfile
from app.models.registration import EventRegistration
from app.models.user import User

audit_logger = logging.getLogger('audit')


_USER_ROLES = {'admin': 'Адміністратори', 'user': 'Без адмін-прав'}
_USER_STATES = {'active': 'Активні', 'inactive': 'Неактивні'}
_USER_CONFIRMED = {'yes': 'Email підтверджено', 'no': 'Email не підтверджено'}
_USER_REGS = {'with': 'З реєстраціями', 'without': 'Без реєстрацій'}


def _user_filters():
    """Фільтри списку користувачів -- спільні для сторінки й xlsx-експорту."""
    return {
        'q': _listing.text_arg('q'),
        'role': _listing.choice_arg('role', _USER_ROLES),
        'state': _listing.choice_arg('state', _USER_STATES),
        'confirmed': _listing.choice_arg('confirmed', _USER_CONFIRMED),
        'regs': _listing.choice_arg('regs', _USER_REGS),
        'date_from': _listing.date_arg('date_from'),
        'date_to': _listing.date_arg('date_to'),
        'per_page': _listing.choice_arg('per_page', _listing.PER_PAGE_CHOICES),
    }


def _users_query(filters):
    """Запит користувачів під фільтри: (rows, reg_count-колонка).

    Кількість реєстрацій -- корельований підзапит (`with_registration_count`),
    тож фільтр «з реєстраціями / без» не тягне окремих SELECT-ів на рядок.
    """

    reg_count = User.with_registration_count()
    query = (
        db.session.query(User, reg_count)
        .options(joinedload(User.medical_profile))
        # Пошук ходить і по телефону з анкети, тож профіль джойнимо явно
        # (outer -- користувач без анкети не має зникати зі списку).
        .outerjoin(MedicalProfile, MedicalProfile.user_id == User.id)
    )
    query = _listing.apply_search(query, filters['q'], [
        User.email, User.first_name, User.last_name, MedicalProfile.phone,
    ])
    if filters['role']:
        query = query.filter(User.is_admin.is_(filters['role'] == 'admin'))
    if filters['state']:
        # is_active має NULL у старих рядках -- 'Неактивні' мусить їх ловити.
        if filters['state'] == 'active':
            query = query.filter(User.is_active.is_(True))
        else:
            query = query.filter(db.or_(
                User.is_active.is_(False), User.is_active.is_(None),
            ))
    if filters['confirmed']:
        query = query.filter(User.email_confirmed.is_(filters['confirmed'] == 'yes'))
    if filters['regs']:
        query = query.filter(
            reg_count > 0 if filters['regs'] == 'with' else reg_count == 0
        )
    query = _listing.apply_date_range(
        query, User.created_at, filters['date_from'], filters['date_to'],
    )
    return query.order_by(User.created_at.desc())


def _users_with_counts(rows):
    """(User, count) -> список User із проставленим `_cached_reg_count`.

    Кеш потрібен, щоб шаблон не смикав `registration_count` по одному запиту
    на рядок.
    """
    users = []
    for user, count in rows:
        user._cached_reg_count = count
        users.append(user)
    return users


@admin_bp.route('/users')
@admin_required
def users():
    filters = _user_filters()
    # Базу вже переросли тисячу акаунтів -- сторінками. Експорт лишається по
    # всьому зрізу.
    pagination = _users_query(filters).paginate(
        page=_listing.page_arg(),
        per_page=_listing.per_page_arg(), error_out=False,
    )
    return render_template(
        'admin/users.html',
        per_page_options=_listing.PER_PAGE_OPTIONS,
        users=_users_with_counts(pagination.items),
        pagination=pagination,
        total_found=pagination.total,
        filters=filters,
        filter_args=_listing.filter_args(filters),
        role_options=list(_USER_ROLES.items()),
        state_options=list(_USER_STATES.items()),
        confirmed_options=list(_USER_CONFIRMED.items()),
        regs_options=list(_USER_REGS.items()),
    )


@admin_bp.route('/users/export')
@admin_required
def users_export():
    """Експорт користувачів у xlsx з урахуванням активних фільтрів."""

    filters = _user_filters()
    users_list = _users_with_counts(_users_query(filters).all())
    summary = _listing.export_summary(
        [
            ('Пошук', filters['q'] or '–'),
            ('Роль', _USER_ROLES.get(filters['role'], 'Усі')),
            ('Стан', _USER_STATES.get(filters['state'], 'Усі')),
            ('Email', _USER_CONFIRMED.get(filters['confirmed'], 'Усі')),
            ('Реєстрації', _USER_REGS.get(filters['regs'], 'Усі')),
            ('Дата реєстрації', _listing.date_range_label(filters)),
        ],
        len(users_list),
    )
    audit_logger.info(
        'Admin %s exported users xlsx (%d rows, filters=%s)',
        current_user.email, len(users_list), filters,
    )
    return _listing.xlsx_export(
        users_list, 'users',
        lambda: xlsx_reports.export_users_xlsx(users_list, applied_filters=summary),
        'admin.users', **_listing.filter_args(filters),
    )


@admin_bp.route('/users/<int:user_id>')
@admin_required
def user_detail(user_id):
    """Картка контакту: анкета, заявки з Meta, реєстрації, онлайн-курси.

    Кількість заявок і дата останньої рахуються ЗАПИТОМ, а не денормалізованими
    колонками в `users`: контакт -- це запис про особу, і стан обробки живе на
    заявці. Денормалізований лічильник тут довелося б синхронізувати з
    кожним видаленням і кожною повторною заявкою, а вигоди на півтори тисячі
    контактів він не дає жодної.
    """
    from app.models.meta_lead import MetaLead
    from app.models.online_enrollment import OnlineEnrollment

    user = db.session.get(User, user_id)
    if not user:
        flash('Користувача не знайдено', 'error')
        return redirect(url_for('admin.users'))

    leads = (
        MetaLead.alive()
        .filter(MetaLead.user_id == user.id)
        .order_by(MetaLead.created_time.desc())
        .all()
    )
    registrations = (
        user.registrations
        .options(joinedload(EventRegistration.instance))
        .order_by(EventRegistration.created_at.desc())
        .all()
    )
    enrollments = (
        OnlineEnrollment.query
        .options(joinedload(OnlineEnrollment.course))
        .filter(OnlineEnrollment.user_id == user.id)
        .order_by(OnlineEnrollment.created_at.desc())
        .all()
    )

    return render_template(
        'admin/user_detail.html',
        user=user,
        profile=user.medical_profile,
        leads=leads,
        registrations=registrations,
        enrollments=enrollments,
    )


@admin_bp.route('/users/<int:user_id>/toggle-admin', methods=['POST'])
@admin_required
def toggle_admin(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('Користувача не знайдено', 'error')
        return redirect(url_for('admin.users'))
    if user.id == current_user.id:
        flash('Неможливо змінити власні повноваження', 'error')
        return redirect(url_for('admin.users'))
    user.is_admin = not user.is_admin
    try:
        db.session.commit()
        status = 'надано' if user.is_admin else 'знято'
        audit_logger.info('Admin %s toggled admin for user %s (%s): %s',
                          current_user.email, user.id, user.email, status)
        flash(f'Адмін-повноваження {status}: {user.email}', 'success')
    except Exception:
        audit_logger.exception('Failed to toggle admin for user %d', user_id)
        db.session.rollback()
        flash('Помилка при оновленні', 'error')
    return redirect(url_for('admin.users'))

# Відгуки: stub замінено повноцінним CRUD -- див. app/admin/routes_reviews.py.
