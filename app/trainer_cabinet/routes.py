import io
import logging

from flask import (
    abort, flash, g, jsonify, redirect, render_template, request, send_file,
    url_for,
)
from flask_babel import gettext as _
from flask_login import current_user

from app.extensions import db, limiter
from app.models.course_instance import CourseInstance
from app.models.mixins import utcnow
from app.models.site_settings import SiteSettings
from app.models.trainer_course_proposal import TrainerCourseProposal
from app.services import lecturer_certificates as lc_svc
from app.services import material_request_service as mrq
from app.services import trainer_cabinet as svc
from app.trainer_cabinet import trainer_cabinet_bp
from app.trainer_cabinet.decorators import trainer_required
from app.trainer_cabinet.forms import MaterialRequestForm, ProposalForm, TrainerProfileForm

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')

PROPOSAL_FIELDS = (
    'title', 'language', 'relevance', 'target_specialties', 'resources',
    'future_topics', 'quiz_url',
)


def _referral_context(trainer, settings):
    """Реферальний блок кабінету: посилання, QR, баланс, історія.

    Лише коли програма увімкнена. Код генерується ліниво (як в адмінці
    тренера й кабінеті учасника) і мусить бути закомічений одразу, інакше
    наступний запит видав би тренеру інше посилання. Це єдиний коміт у
    GET: він фіксує лише щойно згенерований код, бо до нього маршрут у
    сесії нічого не змінює.
    """
    if not settings.referral_enabled:
        return {}
    from app.services import referral_service
    had_code = bool(trainer.referral_code)
    link = referral_service.trainer_referral_link(trainer)
    if not had_code:
        db.session.commit()
    return {
        'referral_link': link,
        'referral_qr': referral_service.qr_svg(link),
        'referral_balance': referral_service.get_balance('trainer', trainer.id),
        'referral_pending': referral_service.get_pending_balance('trainer', trainer.id),
        'referral_rewards': referral_service.list_referrer_rewards('trainer', trainer.id),
    }


@trainer_cabinet_bp.route('/')
@trainer_required
def index():
    trainer = g.trainer
    settings = SiteSettings.get()
    referral = _referral_context(trainer, settings)
    upcoming = svc.upcoming_instances(trainer)
    return render_template(
        'trainer_cabinet/index.html',
        trainer=trainer,
        upcoming=upcoming,
        counts=svc.registration_counts([i.id for i in upcoming]),
        courses=svc.trainer_courses(trainer),
        profile_complete=bool(trainer.profile and trainer.profile.is_complete),
        attention=svc.attention_items(trainer, settings, upcoming=upcoming),
        new_certificates=lc_svc.unseen_count(trainer),
        **referral,
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


def _own_instance(instance_id):
    """Захід цього тренера або 404.

    404, а не 403: стороннього не стосується навіть факт існування заявки.
    Той самий висновок, що в `_own_proposal` вище.
    """
    instance = db.session.get(CourseInstance, instance_id)
    if instance is None:
        abort(404)
    if g.trainer.id not in {t.id for t in instance.effective_trainers}:
        abort(404)
    return instance


@trainer_cabinet_bp.route('/materials')
@trainer_required
def materials():
    # Онлайн-заходам витратні матеріали не потрібні -- у списку їм не місце.
    instances = [inst for inst in svc.upcoming_instances(g.trainer)
                 if mrq.needs_materials(inst)]
    # Доти -- окремий get_reservation на кожен захід (N+1). Окремий запит не
    # потрібен зовсім: `CourseInstance.material_reservations` -- lazy='selectin',
    # тож резервування всіх заходів списку вже підвантажені одним батчем разом
    # із заходами. Рядок один на захід (external_ref унікальний).
    reservations = {inst.id: next(iter(inst.material_reservations), None)
                    for inst in instances}
    return render_template('trainer_cabinet/materials.html',
                           trainer=g.trainer,
                           instances=instances,
                           reservations=reservations)


@trainer_cabinet_bp.route('/materials/<int:instance_id>', methods=['GET', 'POST'])
@trainer_required
def materials_request(instance_id):
    instance = _own_instance(instance_id)
    reservation = mrq.mrs.get_reservation(instance_id)
    # Минулий, скасований чи онлайн-захід відкривається за прямим URL (для
    # історії), але заявку на нього не приймаємо.
    block_reason = mrq.request_block_reason(instance)
    accepts = block_reason is None
    editable = accepts and mrq.is_editable_by_trainer(reservation)
    form = MaterialRequestForm()
    posted_rows = None

    if request.method == 'POST':
        if not editable:
            # Не «надіслано на перевірку»: сюди доходять і погоджена, і
            # відхилена заявка, і про них ця фраза збрехала б.
            if block_reason == 'online':
                flash(_('Онлайн-заходу витратні матеріали не потрібні.'), 'warning')
            elif block_reason == 'closed':
                flash(_('Заявку на цей захід уже не приймаємо: він минув або скасований.'),
                      'warning')
            else:
                flash(_('Цю заявку вже не можна редагувати.'), 'warning')
            return redirect(url_for('trainer_cabinet.materials_request',
                                    instance_id=instance_id))
        if form.validate_on_submit():
            try:
                rows = mrq.parse_form_rows(request.form.getlist('sku'),
                                           request.form.getlist('quantity'))
            except mrq.RequestTransitionError as exc:
                flash(str(exc), 'error')
                return redirect(url_for('trainer_cabinet.materials_request',
                                        instance_id=instance_id))
            reservation = mrq.get_or_create_draft(instance, current_user)
            # Назву й фото кожного рядка бере сервер (resolve_rows), а не
            # форма: їх потім бачать відповідальні, які за ними й погоджують.
            items, dropped = mrq.resolve_rows(instance, reservation, rows)
            mrq.save_items(reservation, items)
            if dropped:
                flash(_('Позиції, яких немає в каталозі складу, не збережено: %(count)s',
                        count=len(dropped)), 'warning')
            reservation.trainer_comment = (form.comment.data or '').strip() or None
            if request.form.get('action') == 'submit':
                try:
                    mrq.submit(reservation, current_user)
                except mrq.RequestTransitionError as exc:
                    db.session.commit()
                    flash(str(exc), 'error')
                    return redirect(url_for('trainer_cabinet.materials_request',
                                            instance_id=instance_id))
                _notify_material_request(reservation, instance)
                flash(_('Заявку надіслано на перевірку.'), 'success')
            else:
                db.session.commit()
                flash(_('Чернетку збережено.'), 'success')
            return redirect(url_for('trainer_cabinet.materials_request',
                                    instance_id=instance_id))

        # Форма не пройшла (прострочений CSRF, задовгий коментар). Доти
        # сторінка мовчки показувала ЗБЕРЕЖЕНІ рядки -- правки тренера
        # зникали без жодного слова. Тепер: причина + його ж рядки на екрані.
        flash(str(form.comment.errors[0]) if form.comment.errors else
              _('Заявку не збережено: сторінка застаріла. Перевірте перелік і надішліть ще раз.'),
              'error')
        posted_rows = _rows_from_post(instance, reservation)

    if request.method == 'GET':
        form.comment.data = reservation.trainer_comment if reservation else None
    # Каталог тут НЕ тягнемо: шаблону він не потрібен, а живий виклик MM Medic
    # (з ретраями) на холодному кеші вішав би сторінку. Про недоступний
    # каталог скаже пошук, коли тренер ним скористається (trainer-materials.js).
    return render_template(
        'trainer_cabinet/materials_request.html',
        form=form,
        instance=instance,
        reservation=reservation,
        editable=editable,
        accepts=accepts,
        block_reason=block_reason,
        participants=mrq.offline_participants(instance),
        rows=(posted_rows if posted_rows is not None
              else mrq.rows_for_form(instance, reservation)),
        max_quantity=mrq.MAX_QUANTITY,
        comment_max=MaterialRequestForm.COMMENT_MAX,
    )


def _rows_from_post(instance, reservation):
    """Рядки з відхиленого POST у вигляді для форми, або None, якщо їх не
    розібрати. Назви -- так само від сервера (resolve_rows), не з форми."""
    try:
        rows = mrq.parse_form_rows(request.form.getlist('sku'),
                                   request.form.getlist('quantity'))
    except mrq.RequestTransitionError:
        return None
    items, _dropped = mrq.resolve_rows(instance, reservation, rows)
    return items


def _notify_material_request(reservation, instance):
    """Лист відповідальним. Збій пошти не скасовує надсилання -- заявка вже
    збережена (той самий патерн, що `_after_submit` для пропозицій)."""
    from app.services.email_service import EmailService
    try:
        EmailService.send_material_request_submitted(reservation, instance)
    except Exception:
        logger.exception('Не вдалося сповістити про заявку %s',
                         reservation.external_ref)


@trainer_cabinet_bp.route('/materials/<int:instance_id>/catalog')
@trainer_required
@limiter.limit('30 per minute')
def materials_catalog(instance_id):
    """Пошук по каталогу для випадайки «додати позицію».

    Ліміт не декоративний: КОЖЕН запит із непорожнім `q` -- живий HTTP у
    MM Medic (кешується лише нефільтрований каталог, див. `get_catalog`).
    """
    _own_instance(instance_id)
    query = (request.args.get('q') or '').strip()
    items, unavailable = mrq.catalog_for_trainer(search=query or None)
    return jsonify({'items': items[:50], 'unavailable': unavailable})


@trainer_cabinet_bp.route('/certificates')
@trainer_required
def certificates():
    """Сертифікати тренера: видані за заходи (читання) і власні регалії."""
    from app.models.lecturer_certificate import LecturerCertificate

    issued = (
        LecturerCertificate.query
        .filter_by(trainer_id=g.trainer.id)
        .order_by(LecturerCertificate.issued_at.desc())
        .all()
    )
    return render_template(
        'trainer_cabinet/certificates.html', trainer=g.trainer, issued=issued,
    )


@trainer_cabinet_bp.route('/certificates', methods=['POST'])
@trainer_required
def certificates_save():
    """Зберегти власні сертифікати-зображення тренера.

    Санітизація -- тим самим trainer_service.sanitize_certificates, що й в
    адмінці: один санітизатор на обидва входи, тож тренер не може покласти в
    поле те, чого не може покласти адмін. Власника позицій адмінка не
    перевіряє (вона довірена), кабінет -- перевіряє: див.
    trainer_service.filter_owned_certificates.
    """
    import json

    from app.services import trainer_service

    # Відсутнє поле чи зламаний JSON -- не «порожній список»: так кожен
    # збій на боці браузера мовчки стирав би всі сертифікати тренера.
    # `null` -- валідний стан (поле ще ні разу не заповнювали), це порожньо.
    raw = request.form.get('certificates')
    readable = raw is not None
    items = None
    if readable:
        try:
            items = json.loads(raw)
        except ValueError:
            readable = False
    if not readable or not (items is None or isinstance(items, list)):
        flash(_('Не вдалося прочитати дані форми. Оновіть сторінку й спробуйте ще раз.'),
              'error')
        return redirect(url_for('trainer_cabinet.certificates'))
    submitted = items or []
    g.trainer.certificates = trainer_service.filter_owned_certificates(
        trainer_service.sanitize_certificates(submitted),
        g.trainer, current_user,
    )
    # Санітизатор і фільтр власності відкидають позиції мовчки -- а тренер зі
    # старою вкладкою чи з двох пристроїв інакше побачив би «збережено» і не
    # дізнався, що частини його списку в базі немає.
    dropped = len(submitted) - len(g.trainer.certificates)
    try:
        db.session.commit()
    except Exception:
        logger.exception('Failed to save trainer %s certificates', g.trainer.id)
        db.session.rollback()
        flash(_('Помилка при збереженні'), 'error')
        return redirect(url_for('trainer_cabinet.certificates'))
    # Той самий крок, що й в адмінці ПІСЛЯ commit (routes_trainers.py):
    # без нього щойно завантажені файли лишаються без entity_type/entity_id
    # і рано чи пізно фізично зникають під CLI media-prune-orphans, хоча
    # сторінка тренера й далі показує їх як наявні.
    trainer_service.attach_trainer_media(g.trainer)
    audit_logger.info('Trainer %s updated own certificates (%d items, %d dropped)',
                      g.trainer.id, len(g.trainer.certificates), dropped)
    if dropped:
        flash(_('Збережено, але частину позицій (%(count)d) пропущено: їх уже '
                'немає у вашому списку. Оновіть сторінку й перевірте список.',
                count=dropped), 'warning')
    else:
        flash(_('Сертифікати збережено'), 'success')
    return redirect(url_for('trainer_cabinet.certificates'))


@trainer_cabinet_bp.route('/certificates/upload', methods=['POST'])
@trainer_required
# Файл лягає на диск і в медіа-реєстр ще до «Зберегти»: без ліміту одна
# вкладка могла б засипати їх файлами по 25 МБ.
@limiter.limit('30 per minute')
def certificate_upload():
    """Завантажити зображення сертифіката в медіа-реєстр.

    Дзеркало admin.upload_trainer_certificate: той самий виклик і та сама
    відповідь, інша лише перевірка доступу.
    """
    from app.services import media_service

    media, error = media_service.create_from_upload(
        request.files.get('file'), entity_type=None, entity_id=None,
        usage_type='certificate', uploader_id=current_user.id,
    )
    if error:
        # Тексти media_service -- українські й не обгорнуті в _() (як і для
        # фото анкети, див. _save_photo): кабінет перекладений, тож тренер
        # бачить перекладене загальне повідомлення, а конкретна причина --
        # у лозі.
        logger.warning('Trainer %s certificate upload rejected: %s', g.trainer.id, error)
        return jsonify({'error': _('Не вдалося обробити файл. Спробуйте інший: '
                                   'JPG, PNG, WebP або HEIC.')}), 400
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception('Failed to persist trainer certificate upload')
        return jsonify({'error': 'Помилка збереження'}), 500
    audit_logger.info('Trainer %s uploaded certificate (media %s)',
                      g.trainer.id, media.id)
    return jsonify({
        'url': media.url, 'thumb': media.variant_url('thumb'),
        'card': media.variant_url('card'), 'media_id': media.id,
        'width': media.width, 'height': media.height,
    }), 200


@trainer_cabinet_bp.route('/certificates/<int:cert_id>/download')
@trainer_required
# PDF рендериться WeasyPrint на кожен клік (файл ніде не зберігається), а
# це секунда-дві процесора -- повторні кліки не мають класти воркер.
@limiter.limit('30 per minute')
def certificate_download(cert_id):
    """Завантажити власний сертифікат лектора (перевірка володіння).

    404, а не 403: чужий номер не має підтверджувати сам факт існування
    документа -- та сама межа, що й у trainer_required.
    """
    from app.models.lecturer_certificate import LecturerCertificate
    from app.services.certificate_service import render_lecturer_pdf

    cert = LecturerCertificate.query.filter_by(
        id=cert_id, trainer_id=g.trainer.id).first()
    if cert is None:
        abort(404)
    try:
        pdf = render_lecturer_pdf(cert)
    except Exception:
        logger.exception('Failed to render lecturer certificate %s', cert.number)
        flash(_('Не вдалося підготувати PDF. Спробуйте пізніше або '
                'зверніться до підтримки.'), 'error')
        return redirect(url_for('trainer_cabinet.certificates'))
    # Перше відкриття знімає позначку «нове». Лише після вдалого рендеру:
    # документ, якого тренер так і не отримав, новим і лишається. Збій
    # позначки не заважає віддати PDF.
    if cert.downloaded_at is None:
        cert.downloaded_at = utcnow()
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.exception('Failed to mark lecturer certificate %s as seen', cert.number)
    response = send_file(
        io.BytesIO(pdf), mimetype='application/pdf', as_attachment=True,
        download_name=f'lecturer-{cert.number}.pdf',
    )
    response.headers['Cache-Control'] = 'no-store, private'
    return response


@trainer_cabinet_bp.route('/certificates/<int:cert_id>/report', methods=['POST'])
@trainer_required
# Кожна скарга -- лист кураторам; п'яти за хвилину досить на будь-яку
# справжню помилку в документах.
@limiter.limit('5 per minute')
def certificate_report(cert_id):
    """Повідомити куратора про помилку у виданому сертифікаті.

    Сам документ тренер виправити не може -- це незмінний знімок із номером.
    Перевидати його вміє лише адмінка, тож єдине, що тут можна зробити, --
    донести проблему до людини, яка має таке право.
    """
    from app.models.lecturer_certificate import LecturerCertificate
    from app.services.email_service import EmailService

    cert = LecturerCertificate.query.filter_by(
        id=cert_id, trainer_id=g.trainer.id).first()
    if cert is None:
        abort(404)
    message = (request.form.get('message') or '').strip()[:2000]
    if not message:
        # Порожня скарга доходить до куратора листом без жодної зачіпки, що
        # саме виправляти, -- і відповіді на неї тренер так і не дочекається.
        flash(_('Опишіть, будь ласка, що саме не так у сертифікаті.'), 'error')
        return redirect(url_for('trainer_cabinet.certificates'))
    try:
        entries = EmailService.send_lecturer_certificate_complaint(cert, message)
    except Exception:
        logger.exception('Failed to report lecturer certificate %s', cert.number)
        flash(_('Не вдалося надіслати повідомлення. Спробуйте пізніше.'), 'error')
        return redirect(url_for('trainer_cabinet.certificates'))
    # Порожній список -- жодного отримувача (сповіщення 'certificate' ніхто не
    # отримує); None/'failed' -- лист відкинула пошта. «Надіслано» в обох
    # випадках було б неправдою: тренер чекав би відповіді, якої не буде.
    if not any(getattr(e, 'status', None) in ('pending', 'sent') for e in entries or []):
        logger.warning('Lecturer certificate complaint %s reached nobody', cert.number)
        flash(_('Повідомлення не доставлено: зараз його нікому отримати. '
                'Напишіть, будь ласка, на пошту ІПРМ.'), 'error')
        return redirect(url_for('trainer_cabinet.certificates'))
    audit_logger.info('Trainer %s reported lecturer cert %s',
                      g.trainer.id, cert.number)
    flash(_('Повідомлення надіслано куратору'), 'success')
    return redirect(url_for('trainer_cabinet.certificates'))
