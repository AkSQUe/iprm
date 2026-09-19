import json
import logging
from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import current_user
from app.admin import _listing, admin_bp
from app.rbac import permission_required
from app.admin.forms import TrainerForm
from app.admin.routes_translations import apply_inline_translations
from app.extensions import db
from app.models.trainer import Trainer
from app.models.media_file import MediaFile
from app.models.trainer_course_proposal import TrainerCourseProposal
from app.models.trainer_profile import TrainerProfile
from app.models.user import User
from app.services import trainer_service
from app.utils import slugify

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')


def _parse_json_list(raw):
    try:
        val = json.loads(raw or '[]')
    except (ValueError, TypeError):
        return []
    return val if isinstance(val, list) else []


def _set_photo_media(trainer, form):
    """Виставити photo_media_id з форми (лише якщо такий MediaFile існує)."""
    mid = (form.photo_media_id.data or '').strip()
    if mid.isdigit() and db.session.get(MediaFile, int(mid)):
        trainer.photo_media_id = int(mid)
    else:
        trainer.photo_media_id = None


def _remap_refs(items, mapping, keys):
    """Замінити URL у dict-елементах JSON-списку за mapping {old: new}."""
    if not isinstance(items, list) or not mapping:
        return items
    out = []
    for it in items:
        if isinstance(it, dict):
            it = dict(it)
            for k in keys:
                if it.get(k) in mapping:
                    it[k] = mapping[it[k]]
        out.append(it)
    return out


def _attach_trainer_media(trainer):
    """Прив'язати MediaFile (фото/сертифікати/патенти) до тренера після збереження.

    Виставляє entity_type/entity_id/usage_type, перейменовує файли у читабельну
    схему ({slug}-photo, {slug}-certificate-N, ...) і оновлює URL у JSON-полях.
    Відв'язані не видаляємо автоматично. Ідемпотентно."""
    from app.services import media_service

    assignments = trainer_service.collect_media_ids(trainer)
    if not assignments:
        return
    rows = {m.id: m for m in MediaFile.query.filter(MediaFile.id.in_(list(assignments))).all()}
    # 1-based індекси в межах кожного usage (для імен -certificate-N / -patent-N).
    cert_idx = {c['media_id']: i for i, c in enumerate(
        [c for c in (trainer.certificates or []) if isinstance(c, dict) and c.get('media_id')], 1)}
    pat_idx = {p['media_id']: i for i, p in enumerate(
        [p for p in (trainer.patents or []) if isinstance(p, dict) and p.get('media_id')], 1)}

    mapping = {}
    for mid, usage in assignments.items():
        m = rows.get(mid)
        if not m:
            continue
        m.entity_type = 'trainer'
        m.entity_id = trainer.id
        m.usage_type = usage
        idx = cert_idx.get(mid) if usage == 'certificate' else (
            pat_idx.get(mid) if usage == 'patent' else None)
        mapping.update(media_service.rename_for_entity(m, trainer.slug, idx))

    if mapping:
        trainer.certificates = _remap_refs(trainer.certificates, mapping, ('url', 'thumb', 'card'))
        trainer.patents = _remap_refs(trainer.patents, mapping, ('image', 'thumb', 'card'))
    try:
        db.session.commit()
    except Exception:
        logger.exception('Failed to attach media to trainer %s', trainer.id)
        db.session.rollback()


def _apply_profile_fields(trainer, form):
    """Санітизувати й перенести регалії та профільні секції з форми у модель."""
    trainer.certificates = trainer_service.sanitize_certificates(_parse_json_list(form.certificates.data))
    trainer.patents = trainer_service.sanitize_patents(_parse_json_list(form.patents.data))
    trainer.articles = trainer_service.sanitize_links(_parse_json_list(form.articles.data))
    trainer.research = trainer_service.sanitize_text_list(form.research.data)
    trainer.skills = trainer_service.sanitize_text_list(form.skills.data)
    trainer.education = trainer_service.sanitize_text_list(form.education.data)
    trainer.additional_education = trainer_service.sanitize_text_list(form.additional_education.data)
    trainer.work_experience = trainer_service.sanitize_text_list(form.work_experience.data)
    # Пари "значення | підпис" -- той самий формат, що й цифри довіри курсу.
    from app.services import course_service
    trainer.highlights = course_service.pairs_text_to_list(form.highlights_text.data)


def _load_profile_into_form(trainer, form):
    """Серіалізувати наявні регалії/профіль у поля редактора (GET)."""
    form.certificates.data = json.dumps(trainer.certificates or [], ensure_ascii=False)
    form.patents.data = json.dumps(trainer.patents or [], ensure_ascii=False)
    form.articles.data = json.dumps(trainer.articles or [], ensure_ascii=False)
    form.research.data = '\n'.join(trainer.research or [])
    form.skills.data = '\n'.join(trainer.skills or [])
    form.education.data = '\n'.join(trainer.education or [])
    form.additional_education.data = '\n'.join(trainer.additional_education or [])
    form.work_experience.data = '\n'.join(trainer.work_experience or [])
    from app.services import course_service
    form.highlights_text.data = course_service.pairs_list_to_text(trainer.highlights)


_TRAINER_STATES = {'active': 'Активні', 'inactive': 'Приховані'}


def _apply_account_link(trainer, email):
    """Прив'язати/відв'язати акаунт. Повертає текст помилки або None."""
    email = (email or '').strip().lower()
    if not email:
        trainer.user_id = None
        return None
    user = User.query.filter(db.func.lower(User.email) == email).first()
    if user is None:
        return 'Користувача з таким email не знайдено'
    taken = Trainer.query.filter(Trainer.user_id == user.id, Trainer.id != trainer.id).first()
    if taken is not None:
        return f'Цей акаунт вже прив\'язано до тренера «{taken.full_name}»'
    trainer.user_id = user.id
    return None


@admin_bp.route('/trainers')
@permission_required('trainers.view')
def trainers_list():
    filters = {
        'q': _listing.text_arg('q'),
        'state': _listing.choice_arg('state', _TRAINER_STATES),
    }
    query = _listing.apply_search(Trainer.query, filters['q'], [
        Trainer.full_name, Trainer.slug, Trainer.email, Trainer.role,
    ])
    if filters['state']:
        query = query.filter(Trainer.is_active.is_(filters['state'] == 'active'))
    trainers = query.order_by(Trainer.full_name).all()
    # Індикатори рахуються агрегатами по всій сторінці одразу -- N+1 по
    # тренерах тут був би найгіршим випадком реєстру (десятки рядків).
    ids = [t.id for t in trainers]
    new_proposals = dict(
        db.session.query(TrainerCourseProposal.trainer_id, db.func.count(TrainerCourseProposal.id))
        .filter(TrainerCourseProposal.trainer_id.in_(ids),
                TrainerCourseProposal.status == TrainerCourseProposal.SUBMITTED)
        .group_by(TrainerCourseProposal.trainer_id).all()
    ) if ids else {}
    complete_profiles = {
        p.trainer_id for p in TrainerProfile.query.filter(TrainerProfile.trainer_id.in_(ids)).all()
        if p.is_complete
    } if ids else set()
    return render_template(
        'admin/trainers.html',
        trainers=trainers,
        filters=filters,
        filter_args=_listing.filter_args(filters),
        state_options=list(_TRAINER_STATES.items()),
        new_proposals=new_proposals,
        complete_profiles=complete_profiles,
    )


@admin_bp.route('/trainers/new', methods=['GET', 'POST'])
@permission_required('trainers.manage')
def trainer_create():
    form = TrainerForm()

    if form.validate_on_submit():
        slug = form.slug.data.strip() or slugify(form.full_name.data)
        if Trainer.query.filter_by(slug=slug).first():
            flash('Тренер з таким slug вже існує', 'error')
            return render_template('admin/trainer_edit.html', form=form, trainer=None)

        trainer = Trainer(
            full_name=form.full_name.data.strip(),
            full_name_dative=(form.full_name_dative.data or '').strip() or None,
            slug=slug,
            role=form.role.data,
            bio=form.bio.data,
            signature=(form.signature.data or '').strip() or None,
            experience_years=form.experience_years.data,
            email=(form.email.data or '').strip().lower() or None,
            is_active=form.is_active.data,
        )
        _set_photo_media(trainer, form)
        _apply_profile_fields(trainer, form)
        link_error = _apply_account_link(trainer, form.account_email.data)
        if link_error:
            form.account_email.errors.append(link_error)
            return render_template('admin/trainer_edit.html', form=form, trainer=None)
        db.session.add(trainer)
        apply_inline_translations(trainer)

        try:
            db.session.commit()
            _attach_trainer_media(trainer)
            audit_logger.info('Admin %s created trainer %s (%s)', current_user.email, trainer.id, trainer.full_name)
            flash('Тренера додано', 'success')
            return redirect(url_for('admin.dashboard'))
        except Exception:
            logger.exception('Failed to create trainer')
            db.session.rollback()
            flash('Помилка при збереженні', 'error')

    return render_template('admin/trainer_edit.html', form=form, trainer=None)


@admin_bp.route('/trainers/<int:trainer_id>/edit', methods=['GET', 'POST'])
@permission_required('trainers.manage')
def trainer_edit(trainer_id):
    trainer = db.session.get(Trainer, trainer_id)
    if not trainer:
        flash('Тренера не знайдено', 'error')
        return redirect(url_for('admin.dashboard'))

    # Реферальне посилання тренера (показуємо адміну, бо тренери не мають
    # власного кабінету). Код генерується лениво при першому відкритті.
    from app.models.site_settings import SiteSettings
    from app.services import referral_service
    referral_link = None
    referral_balance = 0
    referral_dashboard_url = None
    if SiteSettings.get().referral_enabled:
        had_code = bool(trainer.referral_code)
        referral_link = referral_service.trainer_referral_link(trainer)
        if not had_code:  # код щойно згенеровано -> зберегти
            db.session.commit()
        referral_balance = referral_service.get_balance('trainer', trainer.id)
        token = referral_service.make_referrer_token('trainer', trainer.id)
        referral_dashboard_url = url_for('main.referrer_dashboard', token=token, _external=True)

    form = TrainerForm(obj=trainer)
    if request.method == 'GET':
        _load_profile_into_form(trainer, form)
        form.account_email.data = trainer.user.email if trainer.user else ''

    if form.validate_on_submit():
        slug = form.slug.data.strip()
        existing = Trainer.query.filter(Trainer.slug == slug, Trainer.id != trainer_id).first()
        if existing:
            flash('Тренер з таким slug вже існує', 'error')
            return render_template('admin/trainer_edit.html', form=form, trainer=trainer, referral_link=referral_link, referral_balance=referral_balance, referral_dashboard_url=referral_dashboard_url)

        trainer.full_name = form.full_name.data.strip()
        trainer.full_name_dative = (form.full_name_dative.data or '').strip() or None
        trainer.slug = slug
        trainer.role = form.role.data
        trainer.bio = form.bio.data
        trainer.signature = (form.signature.data or '').strip() or None
        trainer.experience_years = form.experience_years.data
        trainer.email = (form.email.data or '').strip().lower() or None
        trainer.is_active = form.is_active.data
        _set_photo_media(trainer, form)
        _apply_profile_fields(trainer, form)
        link_error = _apply_account_link(trainer, form.account_email.data)
        if link_error:
            form.account_email.errors.append(link_error)
            db.session.rollback()
            return render_template('admin/trainer_edit.html', form=form, trainer=trainer, referral_link=referral_link, referral_balance=referral_balance, referral_dashboard_url=referral_dashboard_url)
        apply_inline_translations(trainer)

        try:
            db.session.commit()
            _attach_trainer_media(trainer)
            audit_logger.info('Admin %s updated trainer %s (%s)', current_user.email, trainer_id, trainer.full_name)
            flash('Тренера оновлено', 'success')
            return redirect(url_for('admin.dashboard'))
        except Exception:
            logger.exception('Failed to update trainer %d', trainer_id)
            db.session.rollback()
            flash('Помилка при збереженні', 'error')

    return render_template('admin/trainer_edit.html', form=form, trainer=trainer, referral_link=referral_link, referral_balance=referral_balance, referral_dashboard_url=referral_dashboard_url)


@admin_bp.route('/trainers/<int:trainer_id>/delete', methods=['POST'])
@permission_required('trainers.delete')
def trainer_delete(trainer_id):
    trainer = db.session.get(Trainer, trainer_id)
    if trainer:
        name = trainer.full_name
        db.session.delete(trainer)
        try:
            db.session.commit()
            audit_logger.info('Admin %s deleted trainer %s (%s)', current_user.email, trainer_id, name)
            flash('Тренера видалено', 'success')
        except Exception:
            logger.exception('Failed to delete trainer %d', trainer_id)
            db.session.rollback()
            flash('Помилка при видаленні', 'error')
    return redirect(url_for('admin.dashboard'))


@admin_bp.route('/trainers/<int:trainer_id>/card.json')
@permission_required('trainers.view')
def trainer_card_json(trainer_id):
    """Картка тренера для прев'ю блоку спікерів у формі заходу.

    Окремий ендпоінт, а не JSON усіх тренерів у data-атрибуті: тренерів
    десятки, у кожного bio -- абзац, і вбудований масив зробив би форму
    заходу помітно важчою заради даних, з яких знадобиться два-три записи.
    """
    trainer = db.session.get(Trainer, trainer_id)
    if trainer is None:
        return jsonify({'error': 'not_found'}), 404

    # «Заповнена картка» = те, що рендерить публічний блок спікерів.
    missing = []
    if not (trainer.bio or '').strip():
        missing.append('bio')
    if not (trainer.role or '').strip():
        missing.append('role')
    if not trainer.photo_thumb:
        missing.append('photo')

    return jsonify({
        'id': trainer.id,
        'full_name': trainer.full_name,
        'role': (trainer.role or '').strip(),
        'bio': (trainer.bio or '').strip(),
        'photo': trainer.photo_thumb or '',
        'missing': missing,
        'edit_url': url_for('admin.trainer_edit', trainer_id=trainer.id),
    })
