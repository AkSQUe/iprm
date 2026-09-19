"""Адмінка кабінету тренера: анкета, пропозиції курсу, налаштування «Для тренерів»."""
import logging
from datetime import datetime, timezone

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.admin import admin_bp
from app.admin.forms import ProposalReturnForm, TrainerSettingsForm
from app.extensions import db
from app.models.site_settings import SiteSettings
from app.models.trainer import Trainer
from app.models.trainer_course_proposal import TrainerCourseProposal
from app.models.trainer_profile import TrainerProfile
from app.rbac import permission_required
from app.rbac.access import has_permission
from app.services import trainer_cabinet as svc
from app.utils import truncate_filename

audit_logger = logging.getLogger('audit')

CONTRACT_MAX_BYTES = 10 * 1024 * 1024


@admin_bp.route('/trainers/<int:trainer_id>/questionnaire')
@permission_required('trainers.view')
def trainer_questionnaire(trainer_id):
    trainer = db.session.get(Trainer, trainer_id) or abort(404)
    profile = trainer.profile
    # Реквізити (IBAN, РНОКПП, номер картки, ідентифікаційний код), дата
    # народження, адреса реєстрації й ЄДРПОУ -- лише з trainers.finance.
    # trainers.manage (курування пропозицій) їх НЕ відкриває: це право має
    # редактор контенту. Без finance секрети маскуються, а персональні поля
    # приховуються (None -> шаблон пише «приховано»). Контакти видно всім,
    # хто має trainers.view: куратору вони потрібні для роботи.
    can_finance = has_permission(current_user, 'trainers.finance')
    finance = {}
    if profile is not None:
        for name in TrainerProfile.SENSITIVE_FIELDS:
            value = getattr(profile, name)
            finance[name] = value if can_finance else TrainerProfile.mask(value)
        for name in TrainerProfile.PRIVATE_FIELDS:
            finance[name] = getattr(profile, name) if can_finance else None
    proposals = trainer.proposals.all()
    # Один ProposalReturnForm на ВСІ картки давав однакові name/id textarea
    # на сторінці (невалідний HTML, submit будь-якої форми ніс те саме
    # поле) -- префікс за id пропозиції робить кожен екземпляр окремим.
    return_forms = {
        pr.id: ProposalReturnForm(prefix=f'p{pr.id}')
        for pr in proposals if pr.status == TrainerCourseProposal.SUBMITTED
    }
    return render_template(
        'admin/trainer_questionnaire.html', trainer=trainer, profile=profile,
        finance=finance, can_finance=can_finance,
        can_manage=has_permission(current_user, 'trainers.manage'),
        proposals=proposals, return_forms=return_forms,
    )


def _proposal_or_404(proposal_id):
    return db.session.get(TrainerCourseProposal, proposal_id) or abort(404)


@admin_bp.route('/trainers/proposals/<int:proposal_id>/accept', methods=['POST'])
@permission_required('trainers.manage')
def trainer_proposal_accept(proposal_id):
    proposal = _proposal_or_404(proposal_id)
    try:
        svc.accept_proposal(proposal)
        db.session.commit()
        audit_logger.info('Admin %s accepted trainer proposal %s', current_user.email, proposal.id)
        flash('Пропозицію прийнято', 'success')
    except svc.ProposalTransitionError:
        flash('Неможливо прийняти: пропозиція не на розгляді', 'error')
    return redirect(url_for('admin.trainer_questionnaire', trainer_id=proposal.trainer_id))


@admin_bp.route('/trainers/proposals/<int:proposal_id>/unaccept', methods=['POST'])
@permission_required('trainers.manage')
def trainer_proposal_unaccept(proposal_id):
    """Виправити помилкове «Прийнято»: пропозиція знову на розгляді."""
    proposal = _proposal_or_404(proposal_id)
    try:
        svc.unaccept_proposal(proposal)
        db.session.commit()
        audit_logger.info('Admin %s unaccepted trainer proposal %s', current_user.email, proposal.id)
        flash('Прийняття скасовано: пропозиція знову на розгляді', 'success')
    except svc.ProposalTransitionError:
        flash('Неможливо скасувати: пропозицію не прийнято', 'error')
    return redirect(url_for('admin.trainer_questionnaire', trainer_id=proposal.trainer_id))


@admin_bp.route('/trainers/proposals/<int:proposal_id>/return', methods=['POST'])
@permission_required('trainers.manage')
def trainer_proposal_return(proposal_id):
    proposal = _proposal_or_404(proposal_id)
    # Той самий префікс, яким шаблон рендерив ЦЮ картку (p{proposal_id}):
    # без нього форма читала б поле іншої пропозиції на тій самій сторінці.
    form = ProposalReturnForm(prefix=f'p{proposal_id}')
    if not form.validate_on_submit():
        # Помилка поля -- її текст; інше (прострочена форма тощо) -- загальне
        # повідомлення, а не "задовгий" на будь-який збій.
        errors = form.comment.errors
        flash(errors[0] if errors else 'Не вдалося повернути пропозицію: оновіть сторінку й спробуйте ще раз', 'error')
    else:
        try:
            svc.return_proposal(proposal, form.comment.data)
            db.session.commit()
            audit_logger.info('Admin %s returned trainer proposal %s', current_user.email, proposal.id)
            flash('Пропозицію повернуто на доопрацювання', 'success')
        except svc.ProposalTransitionError:
            flash('Неможливо повернути: пропозиція не на розгляді', 'error')
    return redirect(url_for('admin.trainer_questionnaire', trainer_id=proposal.trainer_id))


def _read_contract(file):
    """Байти PDF або (None, помилка). Перевіряємо сигнатуру, а не лише розширення."""
    data = file.read()
    if not data.startswith(b'%PDF-'):
        return None, 'Файл не є PDF'
    if len(data) > CONTRACT_MAX_BYTES:
        return None, 'PDF більший за 10 МБ'
    return data, None


@admin_bp.route('/settings/trainers', methods=['GET', 'POST'])
@permission_required('settings.manage')
def settings_trainers():
    site = SiteSettings.get()
    form = TrainerSettingsForm()
    if request.method == 'GET':
        form.faq_html.data = svc.faq_source(site)
        form.contract_email.data = site.trainer_contract_email

    if form.validate_on_submit():
        upload = form.contract_pdf.data
        if upload and getattr(upload, 'filename', ''):
            data, error = _read_contract(upload)
            if error:
                form.contract_pdf.errors.append(error)
                return render_template('admin/settings_trainers.html', form=form, site=site)
            site.trainer_contract_pdf = data
            # Ім'я -- від клієнта: старі браузери шлють повний шлях, а
            # довжина не обмежена нічим, крім файлової системи відправника;
            # колонка -- String(255).
            site.trainer_contract_filename = truncate_filename(upload.filename)
            site.trainer_contract_uploaded_at = datetime.now(timezone.utc)
        elif form.remove_contract.data:
            site.trainer_contract_pdf = None
            site.trainer_contract_filename = ''
            site.trainer_contract_uploaded_at = None

        # Якщо збережений текст дослівно збігається з дефолтом -- зберігаємо
        # порожній рядок, щоб майбутні правки дефолту в коді доходили до сайту.
        # Браузер нормалізує переноси рядків у textarea в \r\n, тоді як
        # DEFAULT_TRAINER_FAQ_HTML написаний з \n -- без нормалізації
        # порівняння ніколи не збігалось би при реальному сабміті форми.
        from app.data.trainer_faq import DEFAULT_TRAINER_FAQ_HTML
        faq = (form.faq_html.data or '').strip().replace('\r\n', '\n').replace('\r', '\n')
        site.trainer_faq_html = '' if faq == DEFAULT_TRAINER_FAQ_HTML.strip() else faq
        site.trainer_contract_email = (form.contract_email.data or '').strip().lower()
        db.session.commit()
        audit_logger.info('Admin %s updated trainer settings', current_user.email)
        flash('Налаштування для тренерів збережено', 'success')
        return redirect(url_for('admin.settings_trainers'))

    return render_template('admin/settings_trainers.html', form=form, site=site)
