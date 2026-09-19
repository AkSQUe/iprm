import io
import logging

from flask import abort, flash, g, redirect, render_template, request, send_file, url_for
from flask_babel import gettext as _
from flask_login import current_user

from app.extensions import db
from app.models.site_settings import SiteSettings
from app.models.trainer_course_proposal import TrainerCourseProposal
from app.services import trainer_cabinet as svc
from app.trainer_cabinet import trainer_cabinet_bp
from app.trainer_cabinet.decorators import trainer_required
from app.trainer_cabinet.forms import ProposalForm, TrainerProfileForm

logger = logging.getLogger(__name__)

PROPOSAL_FIELDS = (
    'title', 'language', 'relevance', 'target_specialties', 'resources',
    'future_topics', 'quiz_url',
)


@trainer_cabinet_bp.route('/')
@trainer_required
def index():
    trainer = g.trainer
    upcoming = svc.upcoming_instances(trainer)
    return render_template(
        'trainer_cabinet/index.html',
        trainer=trainer,
        upcoming=upcoming,
        counts=svc.registration_counts([i.id for i in upcoming]),
        courses=svc.trainer_courses(trainer),
        profile_complete=bool(trainer.profile and trainer.profile.is_complete),
    )


def _save_photo(form, profile):
    """Завантажене фото -> MediaFile анкети. Повертає текст помилки або None."""
    file = form.photo.data
    if not file or not getattr(file, 'filename', ''):
        return None
    from app.services import media_service
    media, error = media_service.create_from_upload(
        file, entity_type='trainer_profile', entity_id=profile.id,
        usage_type='photo', uploader_id=current_user.id,
    )
    if error:
        return error
    profile.photo_media_id = media.id
    return None


@trainer_cabinet_bp.route('/profile', methods=['GET', 'POST'])
@trainer_required
def profile():
    trainer = g.trainer
    record = trainer.profile
    form = TrainerProfileForm()
    if request.method == 'GET' and record is not None:
        for name in TrainerProfileForm.MODEL_FIELDS:
            getattr(form, name).data = getattr(record, name)

    if form.validate_on_submit():
        record = svc.get_or_create_profile(trainer)
        for name in TrainerProfileForm.MODEL_FIELDS:
            value = getattr(form, name).data
            setattr(record, name, value.strip() if isinstance(value, str) else value)
        photo_error = _save_photo(form, record)
        if photo_error:
            db.session.rollback()
            form.photo.errors.append(photo_error)
        else:
            try:
                db.session.commit()
                flash(_('Анкету збережено'), 'success')
                return redirect(url_for('trainer_cabinet.profile'))
            except Exception:
                logger.exception('Failed to save trainer profile %s', trainer.id)
                db.session.rollback()
                flash(_('Помилка при збереженні'), 'error')

    return render_template(
        'trainer_cabinet/profile.html', trainer=trainer, form=form,
        record=trainer.profile, proposals=trainer.proposals.all(),
    )


@trainer_cabinet_bp.route('/contract')
@trainer_required
def contract():
    settings = SiteSettings.get()
    return render_template(
        'trainer_cabinet/contract.html', trainer=g.trainer,
        has_contract=settings.has_trainer_contract,
        contract_email=svc.contract_email(settings),
    )


@trainer_cabinet_bp.route('/contract/download')
@trainer_required
def contract_download():
    settings = SiteSettings.get()
    data = settings.trainer_contract_pdf if settings.has_trainer_contract else None
    if not data:
        abort(404)
    return send_file(
        io.BytesIO(data), mimetype='application/pdf', as_attachment=True,
        download_name=settings.trainer_contract_filename or 'contract.pdf',
    )


@trainer_cabinet_bp.route('/faq')
@trainer_required
def faq():
    return render_template(
        'trainer_cabinet/faq.html', trainer=g.trainer,
        faq_html=svc.faq_html(SiteSettings.get()),
    )


def _own_proposal(proposal_id):
    proposal = TrainerCourseProposal.query.filter_by(
        id=proposal_id, trainer_id=g.trainer.id).first()
    if proposal is None:
        abort(404)
    return proposal


def _apply_proposal(form, proposal):
    for name in PROPOSAL_FIELDS:
        value = getattr(form, name).data
        setattr(proposal, name, (value or '').strip() or None)
    proposal.title = form.title.data.strip()
    proposal.theses = form.theses_list()


@trainer_cabinet_bp.route('/proposals/new', methods=['GET', 'POST'])
@trainer_required
def proposal_new():
    form = ProposalForm()
    if form.validate_on_submit():
        proposal = TrainerCourseProposal(trainer_id=g.trainer.id)
        _apply_proposal(form, proposal)
        db.session.add(proposal)
        db.session.commit()
        flash(_('Чернетку збережено'), 'success')
        return redirect(url_for('trainer_cabinet.proposal_edit', proposal_id=proposal.id))
    return render_template('trainer_cabinet/proposal_edit.html', form=form, proposal=None)


@trainer_cabinet_bp.route('/proposals/<int:proposal_id>', methods=['GET', 'POST'])
@trainer_required
def proposal_edit(proposal_id):
    proposal = _own_proposal(proposal_id)
    if not proposal.is_editable:
        if request.method == 'POST':
            abort(409)
        return render_template('trainer_cabinet/proposal_view.html', proposal=proposal)
    form = ProposalForm(obj=proposal) if request.method == 'GET' else ProposalForm()
    if request.method == 'GET':
        form.theses.data = '\n'.join(proposal.theses or [])
    if form.validate_on_submit():
        _apply_proposal(form, proposal)
        db.session.commit()
        flash(_('Чернетку збережено'), 'success')
        return redirect(url_for('trainer_cabinet.proposal_edit', proposal_id=proposal.id))
    return render_template('trainer_cabinet/proposal_edit.html', form=form, proposal=proposal)


def _after_submit(proposal):
    """Лист куратору. Збій пошти не скасовує надсилання -- пропозиція вже збережена."""
    from app.services.email_service import EmailService
    try:
        EmailService.send_trainer_proposal_notification(proposal)
    except Exception:
        logger.exception('Failed to notify curator about proposal %s', proposal.id)


@trainer_cabinet_bp.route('/proposals/<int:proposal_id>/submit', methods=['POST'])
@trainer_required
def proposal_submit(proposal_id):
    proposal = _own_proposal(proposal_id)
    try:
        svc.submit_proposal(proposal)
    except svc.ProposalTransitionError:
        abort(409)
    db.session.commit()
    _after_submit(proposal)
    flash(_('Пропозицію надіслано куратору'), 'success')
    return redirect(url_for('trainer_cabinet.profile'))


@trainer_cabinet_bp.route('/proposals/<int:proposal_id>/delete', methods=['POST'])
@trainer_required
def proposal_delete(proposal_id):
    proposal = _own_proposal(proposal_id)
    if not proposal.is_editable:
        abort(409)
    db.session.delete(proposal)
    db.session.commit()
    flash(_('Чернетку видалено'), 'success')
    return redirect(url_for('trainer_cabinet.profile'))
