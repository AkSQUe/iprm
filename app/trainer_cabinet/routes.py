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
audit_logger = logging.getLogger('audit')

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
        attention=svc.attention_items(trainer, SiteSettings.get()),
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
        # Тексти media_service -- українські й не обгорнуті в _(): кабінет
        # перекладений, тож тренер бачить перекладене загальне повідомлення,
        # а конкретна причина йде в лог.
        logger.warning('Trainer %s photo upload rejected: %s', g.trainer.id, error)
        return _('Не вдалося обробити фото. Спробуйте інший файл: JPG, PNG, WebP або HEIC.')
    profile.photo_media_id = media.id
    return None


def _after_requisites_change(trainer, before, changed):
    """Аудит і лист куратору після ЗБЕРЕЖЕНОЇ зміни реквізитів.

    Реквізити -- куди йде гонорар: тиха заміна (помилка чи чужий доступ до
    акаунта) означала б переказ не туди. У журнал -- лише назви полів,
    ніколи значення. Перше заповнення (усе було порожнім) -- лише аудит:
    лист про «зміну» з нічого куратору не потрібен. Збій пошти не скасовує
    збереження -- анкета вже в БД.
    """
    if not changed:
        return
    audit_logger.info('Trainer %s changed requisites: %s', trainer.id, ', '.join(changed))
    if not any(before.values()):
        return
    from app.services.email_service import EmailService
    try:
        EmailService.send_trainer_requisites_notification(trainer, changed)
    except Exception:
        logger.exception('Failed to notify curator about trainer %s requisites', trainer.id)


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
        requisites_before = svc.requisites_snapshot(record)
        for name in TrainerProfileForm.MODEL_FIELDS:
            value = getattr(form, name).data
            setattr(record, name, value.strip() if isinstance(value, str) else value)
        if form.remove_photo.data:
            record.photo_media_id = None
        photo_error = _save_photo(form, record)
        if photo_error:
            db.session.rollback()
            form.photo.errors.append(photo_error)
        else:
            changed = svc.changed_requisites(requisites_before, record)
            try:
                db.session.commit()
            except Exception:
                logger.exception('Failed to save trainer profile %s', trainer.id)
                db.session.rollback()
                flash(_('Помилка при збереженні'), 'error')
            else:
                _after_requisites_change(trainer, requisites_before, changed)
                flash(_('Анкету збережено'), 'success')
                return redirect(url_for('trainer_cabinet.profile'))

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
    response = send_file(
        io.BytesIO(data), mimetype='application/pdf', as_attachment=True,
        download_name=settings.trainer_contract_filename or 'contract.pdf',
    )
    # Документ лише для тренерів: кеш-політика HTML (after_request) на PDF не
    # діє, тож забороняємо зберігати його проміжним і браузерним кешам тут.
    response.headers['Cache-Control'] = 'no-store, private'
    return response


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


def _wants_submit():
    """Натиснуто "Надіслати куратору", а не "Зберегти чернетку".

    Дивимось і в форму, і в рядок запиту: form-single-submit.js вимикає
    кнопки на submit, і name/value вимкненої кнопки браузер у дані форми не
    кладе -- тому кнопка несе action ще й у formaction (?action=submit).
    """
    return request.values.get('action') == 'submit'


def _locked(proposal):
    """Тренер намагається змінити пропозицію, яку вже не можна чіпати.

    Не 409: для нього немає шаблону помилки, а кожен такий запит писав би
    ErrorLog. Звичайна ситуація (друга вкладка, повторний клік) -- flash і
    сторінка перегляду з актуальним статусом.
    """
    flash(_('Пропозицію вже надіслано куратору -- змінити її не можна'), 'warning')
    return redirect(url_for('trainer_cabinet.proposal_edit', proposal_id=proposal.id))


def _save_proposal(form, proposal):
    """Зберігає форму; для "Надіслати куратору" -- ще й надсилає тим самим
    комітом. Раніше надсилання йшло окремою формою і брало ОСТАННЮ збережену
    версію: незбережені правки мовчки губились."""
    is_new = proposal.id is None
    _apply_proposal(form, proposal)
    db.session.add(proposal)
    wants_submit = _wants_submit()
    if wants_submit:
        svc.submit_proposal(proposal)
    try:
        db.session.commit()
    except Exception:
        logger.exception('Failed to save trainer proposal (trainer %s)', g.trainer.id)
        db.session.rollback()
        flash(_('Помилка при збереженні'), 'error')
        return render_template(
            'trainer_cabinet/proposal_edit.html',
            **_proposal_edit_context(form, None if is_new else proposal))
    if wants_submit:
        _after_submit(proposal)
        flash(_('Пропозицію надіслано куратору'), 'success')
        return redirect(url_for('trainer_cabinet.profile'))
    flash(_('Чернетку збережено'), 'success')
    return redirect(url_for('trainer_cabinet.proposal_edit', proposal_id=proposal.id))


def _proposal_edit_context(form, proposal):
    """Спільний контекст шаблону редагування: межі -- з моделі, не окремим
    числом у шаблоні/JS, щоб зміна константи доходила скрізь одразу."""
    return dict(
        form=form, proposal=proposal,
        title_max=TrainerCourseProposal.TITLE_MAX,
        theses_max=TrainerCourseProposal.THESES_MAX,
    )


@trainer_cabinet_bp.route('/proposals/new', methods=['GET', 'POST'])
@trainer_required
def proposal_new():
    form = ProposalForm()
    if form.validate_on_submit():
        # Статус явно: колонковий default підставляється лише на INSERT, а
        # "Надіслати куратору" перевіряє статус ще до flush.
        proposal = TrainerCourseProposal(
            trainer_id=g.trainer.id, status=TrainerCourseProposal.DRAFT)
        return _save_proposal(form, proposal)
    return render_template('trainer_cabinet/proposal_edit.html',
                           **_proposal_edit_context(form, None))


@trainer_cabinet_bp.route('/proposals/<int:proposal_id>', methods=['GET', 'POST'])
@trainer_required
def proposal_edit(proposal_id):
    proposal = _own_proposal(proposal_id)
    if not proposal.is_editable:
        if request.method == 'POST':
            return _locked(proposal)
        return render_template('trainer_cabinet/proposal_view.html', proposal=proposal)
    form = ProposalForm(obj=proposal) if request.method == 'GET' else ProposalForm()
    if request.method == 'GET':
        form.theses.data = '\n'.join(proposal.theses or [])
    if form.validate_on_submit():
        return _save_proposal(form, proposal)
    return render_template('trainer_cabinet/proposal_edit.html',
                           **_proposal_edit_context(form, proposal))


def _after_submit(proposal):
    """Лист куратору. Збій пошти не скасовує надсилання -- пропозиція вже збережена."""
    from app.services.email_service import EmailService
    try:
        EmailService.send_trainer_proposal_notification(proposal)
    except Exception:
        logger.exception('Failed to notify curator about proposal %s', proposal.id)


@trainer_cabinet_bp.route('/proposals/<int:proposal_id>/delete', methods=['POST'])
@trainer_required
def proposal_delete(proposal_id):
    proposal = _own_proposal(proposal_id)
    if not proposal.is_editable:
        return _locked(proposal)
    db.session.delete(proposal)
    try:
        db.session.commit()
    except Exception:
        logger.exception('Failed to delete trainer proposal %s', proposal_id)
        db.session.rollback()
        flash(_('Помилка при видаленні'), 'error')
        return redirect(url_for('trainer_cabinet.proposal_edit', proposal_id=proposal_id))
    flash(_('Чернетку видалено'), 'success')
    return redirect(url_for('trainer_cabinet.profile'))
