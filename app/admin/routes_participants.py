"""Admin: ручне додавання та редагування учасника заходу.

Об'єднує User (identity) + MedicalProfile (медичні дані) + EventRegistration
(реєстрація на CourseInstance) в одній формі. Email не обов'язковий -- якщо
менеджер його не вказав, користувачу присвоюється placeholder-email
(<цифри-телефону>@noemail.invalid), а реальний email додається пізніше через
редагування. Логіка дзеркалить публічний реєстраційний флоу та скрипт імпорту.
"""
import logging
import re
from datetime import datetime, timezone

from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user
from sqlalchemy.orm import joinedload

from app.admin import admin_bp
from app.admin._helpers import try_commit
from app.admin.decorators import admin_required
from app.admin.forms import ParticipantForm
from app.extensions import db
from app.models.course_instance import CourseInstance
from app.models.medical_profile import MedicalProfile
from app.models.registration import EventRegistration
from app.models.specializations import labels_for_codes
from app.models.user import User
from app.services import registration_service

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')

# Домени placeholder-email: користувач без реального email. '.invalid' --
# RFC 2606 зарезервований TLD, гарантовано недоставлюваний. 'xlsx.temp' --
# спадок скрипта імпорту, теж вважаємо placeholder-ом при редагуванні.
PLACEHOLDER_EMAIL_DOMAIN = 'noemail.invalid'
_PLACEHOLDER_DOMAINS = {PLACEHOLDER_EMAIL_DOMAIN, 'xlsx.temp'}


# ===================== helpers =====================

def _strip_or_none(value):
    s = (value or '').strip()
    return s or None


def _set_if(obj, attr, value):
    """Записати value у obj.attr лише якщо воно непорожнє.

    Не затираємо наявні дані порожнім вводом -- важливо при прив'язці до
    наявного користувача та при редагуванні (форма не призначена для
    очищення полів)."""
    if value not in (None, ''):
        setattr(obj, attr, value)


def _is_placeholder_email(email):
    """True, якщо email -- згенерований placeholder, а не реальна адреса."""
    if not email or '@' not in email:
        return False
    return email.rsplit('@', 1)[-1].lower() in _PLACEHOLDER_DOMAINS


def _placeholder_email(phone):
    """Унікальний placeholder-email з цифр телефону (або 'manual')."""
    base = re.sub(r'\D', '', phone or '') or 'manual'
    candidate = f'{base}@{PLACEHOLDER_EMAIL_DOMAIN}'
    n = 1
    while User.query.filter_by(email=candidate).first() is not None:
        n += 1
        candidate = f'{base}-{n}@{PLACEHOLDER_EMAIL_DOMAIN}'
    return candidate


def _instance_label(instance):
    title = instance.course.title if instance.course else f'Захід #{instance.id}'
    date = instance.start_date.strftime('%d.%m.%Y') if instance.start_date else 'без дати'
    status = dict(CourseInstance.STATUSES).get(instance.status, instance.status)
    return f'{title} -- {date} ({status})'


def _all_instances():
    return (
        db.session.query(CourseInstance)
        .options(joinedload(CourseInstance.course))
        .order_by(CourseInstance.start_date.desc().nullslast())
        .all()
    )


def _resolve_user(form):
    """Знайти користувача за email або створити нового.

    Повертає (user, is_new). Якщо email вказано й знайдено наявного -- reuse;
    якщо вказано й не знайдено -- новий з цим email; якщо не вказано --
    новий з placeholder-email. Може зробити flush для призначення id."""
    email = (form.email.data or '').strip().lower()
    if email:
        existing = User.query.filter_by(email=email).first()
        if existing is not None:
            return existing, False
    else:
        email = _placeholder_email(form.phone.data)

    user = User(email=email, email_confirmed=False)
    db.session.add(user)
    db.session.flush()
    return user, True


def _sync_user_and_profile(form, user):
    """Записати identity-поля у User і медичні -- у MedicalProfile.

    Порожні значення не затирають наявні (див. _set_if). Email тут НЕ
    чіпаємо -- ним керують окремо (_resolve_user на створенні, окрема
    перевірка унікальності на редагуванні). Повертає profile."""
    _set_if(user, 'last_name', _strip_or_none(form.last_name.data))
    _set_if(user, 'first_name', _strip_or_none(form.first_name.data))

    profile = user.medical_profile
    if profile is None:
        profile = MedicalProfile(user_id=user.id, source=MedicalProfile.SOURCE_IMPORTED)
        db.session.add(profile)
        user.medical_profile = profile

    _set_if(profile, 'participant_type', form.participant_type.data or None)
    _set_if(profile, 'middle_name', _strip_or_none(form.middle_name.data))
    _set_if(profile, 'phone', _strip_or_none(form.phone.data))
    if form.birth_date.data:
        profile.birth_date = form.birth_date.data
    _set_if(profile, 'education', _strip_or_none(form.education.data))
    _set_if(profile, 'workplace', _strip_or_none(form.workplace.data))
    _set_if(profile, 'position', _strip_or_none(form.position.data))
    if form.specializations.data:
        profile.specializations = list(form.specializations.data)

    if profile.is_complete and profile.completed_at is None:
        profile.completed_at = datetime.now(timezone.utc)

    return profile


def _apply_registration_fields(form, reg, profile):
    """Заповнити EventRegistration з форми. Snapshot-поля (specialty,
    workplace) деривуємо з профілю -- консистентно з публічним флоу."""
    specs = profile.specializations or []
    specialty = ', '.join(labels_for_codes(specs)) or _strip_or_none(form.position.data) or ''
    workplace = _strip_or_none(form.workplace.data) or _strip_or_none(profile.workplace) or ''

    reg.phone = (_strip_or_none(form.phone.data) or '')[:20]
    reg.specialty = specialty[:200]
    reg.workplace = workplace[:300]
    reg.experience_years = form.experience_years.data
    reg.license_number = _strip_or_none(form.license_number.data)
    reg.status = form.status.data
    reg.payment_status = form.payment_status.data
    reg.payment_amount = form.payment_amount.data
    reg.attended = bool(form.attended.data)
    reg.cpd_points_awarded = form.cpd_points_awarded.data
    reg.admin_notes = _strip_or_none(form.admin_notes.data)


def _maybe_assign_place(reg):
    """Призначити номер місця для оплачених (не скасованих) реєстрацій."""
    if reg.payment_status == 'paid' and reg.status != 'cancelled' and reg.place_number is None:
        try:
            registration_service.assign_place_number(reg)
        except Exception:
            logger.exception('Failed to assign place_number for REG-%s', reg.id)


# ===================== create =====================

def _render_create(form, instance=None):
    return render_template(
        'admin/participant_edit.html',
        form=form,
        reg=None,
        instance=instance,
        fixed_instance=instance is not None,
    )


def _process_create(form, instance):
    """Спільна обробка POST для обох create-роутів. Повертає Response при
    успіху або None (треба відрендерити форму)."""
    user, is_new = _resolve_user(form)

    existing = registration_service.find_existing(user.id, instance.id)
    if existing is not None and existing.status != 'cancelled':
        db.session.rollback()
        flash('Цей учасник уже зареєстрований на цей захід', 'error')
        return None

    profile = _sync_user_and_profile(form, user)

    reg = existing  # cancelled-реєстрацію реактивуємо
    if reg is None:
        reg = EventRegistration(user_id=user.id, instance_id=instance.id)
        db.session.add(reg)
    _apply_registration_fields(form, reg, profile)

    db.session.flush()
    _maybe_assign_place(reg)

    if try_commit(log_context=f'participant_create user={user.id} instance={instance.id}'):
        audit_logger.info(
            'Admin %s added participant user=%s (new=%s) to instance=%s reg=%s',
            current_user.email, user.id, is_new, instance.id, reg.id,
        )
        flash('Учасника додано', 'success')
        return redirect(url_for('admin.instance_registrations', instance_id=instance.id))
    return None


@admin_bp.route('/participants/new', methods=['GET', 'POST'])
@admin_required
def participant_create():
    """Окрема сторінка: додати учасника з вибором заходу у формі."""
    form = ParticipantForm()
    instances = _all_instances()
    form.instance_id.choices = [(i.id, _instance_label(i)) for i in instances]

    # Pre-select заходу через ?instance_id= (напр. перехід зі списку заходів).
    preselected = request.args.get('instance_id', type=int)
    if request.method == 'GET' and preselected:
        form.instance_id.data = preselected

    if form.validate_on_submit():
        instance = db.session.get(CourseInstance, form.instance_id.data)
        if instance is None:
            flash('Захід не знайдено', 'error')
        else:
            response = _process_create(form, instance)
            if response is not None:
                return response

    return _render_create(form)


@admin_bp.route('/instances/<int:instance_id>/participants/new', methods=['GET', 'POST'])
@admin_required
def participant_create_for_instance(instance_id):
    """Додати учасника в контексті конкретного заходу (захід фіксований)."""
    instance = (
        db.session.query(CourseInstance)
        .options(joinedload(CourseInstance.course))
        .filter_by(id=instance_id)
        .first()
    )
    if instance is None:
        flash('Захід не знайдено', 'error')
        return redirect(url_for('admin.registrations_all'))

    form = ParticipantForm()
    form.instance_id.choices = [(instance.id, _instance_label(instance))]
    if request.method == 'GET':
        form.instance_id.data = instance.id

    if form.validate_on_submit():
        response = _process_create(form, instance)
        if response is not None:
            return response

    return _render_create(form, instance=instance)


# ===================== edit =====================

def _form_from_registration(reg):
    user = reg.user
    profile = user.medical_profile if user else None
    email = '' if _is_placeholder_email(user.email if user else '') else (user.email if user else '')
    return ParticipantForm(data={
        'instance_id': reg.instance_id,
        'last_name': (user.last_name if user else '') or '',
        'first_name': (user.first_name if user else '') or '',
        'middle_name': (profile.middle_name if profile else '') or '',
        'email': email,
        'phone': reg.phone or (profile.phone if profile else '') or '',
        'participant_type': (profile.participant_type if profile else '') or '',
        'birth_date': profile.birth_date if profile else None,
        'education': (profile.education if profile else '') or '',
        'workplace': (profile.workplace if profile else '') or reg.workplace or '',
        'position': (profile.position if profile else '') or '',
        'specializations': (profile.specializations if profile else []) or [],
        'status': reg.status,
        'payment_status': reg.payment_status,
        'payment_amount': reg.payment_amount,
        'attended': reg.attended,
        'cpd_points_awarded': reg.cpd_points_awarded,
        'experience_years': reg.experience_years,
        'license_number': reg.license_number,
        'admin_notes': reg.admin_notes,
    })


@admin_bp.route('/registrations/<int:reg_id>/edit', methods=['GET', 'POST'])
@admin_required
def participant_edit(reg_id):
    """Редагувати дані учасника (User + MedicalProfile + EventRegistration)."""
    reg = (
        db.session.query(EventRegistration)
        .options(
            joinedload(EventRegistration.user).joinedload(User.medical_profile),
            joinedload(EventRegistration.instance).joinedload(CourseInstance.course),
        )
        .filter_by(id=reg_id)
        .first()
    )
    if reg is None:
        flash('Реєстрацію не знайдено', 'error')
        return redirect(url_for('admin.registrations_all'))

    instance = reg.instance
    user = reg.user

    if request.method == 'POST':
        form = ParticipantForm()
    else:
        form = _form_from_registration(reg)
    # Захід фіксований -- лишаємо лише поточний у choices.
    form.instance_id.choices = [(reg.instance_id, _instance_label(instance) if instance else '—')]

    if form.validate_on_submit():
        # Email: дозволяємо додати/змінити, перевіряючи унікальність.
        new_email = (form.email.data or '').strip().lower()
        if new_email and new_email != user.email:
            clash = User.query.filter(
                User.email == new_email, User.id != user.id,
            ).first()
            if clash is not None:
                flash('Інший користувач уже має цей email', 'error')
                return render_template(
                    'admin/participant_edit.html',
                    form=form, reg=reg, instance=instance, fixed_instance=True,
                )
            user.email = new_email

        profile = _sync_user_and_profile(form, user)
        _apply_registration_fields(form, reg, profile)
        db.session.flush()
        _maybe_assign_place(reg)

        if try_commit(log_context=f'participant_edit reg={reg.id}'):
            audit_logger.info(
                'Admin %s edited participant reg=%s user=%s',
                current_user.email, reg.id, user.id,
            )
            flash('Дані учасника оновлено', 'success')
            return redirect(url_for('admin.instance_registrations', instance_id=reg.instance_id))

    return render_template(
        'admin/participant_edit.html',
        form=form, reg=reg, instance=instance, fixed_instance=True,
    )
