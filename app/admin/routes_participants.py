"""Admin: ручне додавання та редагування учасника заходу + xlsx import/export.

Об'єднує User (identity) + MedicalProfile (медичні дані) + EventRegistration
(реєстрація на CourseInstance). Email не обов'язковий. Канонічна логіка
upsert-у живе в app.services.participant_service (спільна з xlsx-імпортом);
тут -- HTTP-обгортки: форма та xlsx export/import (preview -> apply).
"""
import logging
from datetime import datetime, timezone

from flask import (
    flash, redirect, render_template, request, send_file, url_for,
)
from flask_login import current_user
from sqlalchemy.orm import joinedload

from app.admin import admin_bp
from app.admin._helpers import try_commit
from app.admin.decorators import admin_required
from app.admin.forms import ParticipantForm
from app.extensions import db
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import participant_service, promo_service, xlsx_io
from app.services.participant_service import ParticipantError
from app.services.promo_service import PromoError
from app.utils import ensure_utc

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')


# ===================== helpers =====================

def _instance_label(instance):
    """Ярлик заходу для випадних списків форми (з назвою статусу)."""
    return participant_service.event_label(instance, with_status=True)


def _all_instances():
    """Заходи для випадного списку, впорядковані для зручності менеджера:
    спершу майбутні за зростанням (найближчий -- першим), потім минулі за
    спаданням (свіжіші -- першими), наприкінці -- заходи без дати."""
    instances = (
        db.session.query(CourseInstance)
        .options(joinedload(CourseInstance.course))
        .all()
    )
    now = datetime.now(timezone.utc)

    def _order_key(inst):
        sd = ensure_utc(inst.start_date)
        if sd is None:
            return (2, 0.0)            # без дати -- у кінець
        if sd >= now:
            return (0, sd.timestamp())   # майбутні: за зростанням
        return (1, -sd.timestamp())      # минулі: за спаданням

    instances.sort(key=_order_key)
    return instances


def _nearest_upcoming_id(instances):
    """ID найближчого майбутнього заходу зі впорядкованого списку, або None.

    Список від _all_instances() починається з майбутніх за зростанням, тож
    перший захід із датою у майбутньому і є найближчим."""
    now = datetime.now(timezone.utc)
    for inst in instances:
        sd = ensure_utc(inst.start_date)
        if sd is not None and sd >= now:
            return inst.id
    return None


def _form_to_data(form, instance_id):
    """WTForms -> нормалізований dict для participant_service."""
    return {
        'instance_id': instance_id,
        'last_name': form.last_name.data,
        'first_name': form.first_name.data,
        'middle_name': form.middle_name.data,
        'email': form.email.data,
        'phone': form.phone.data,
        'participant_type': form.participant_type.data or None,
        'birth_date': form.birth_date.data,
        'education': form.education.data,
        'workplace': form.workplace.data,
        'position': form.position.data,
        'specializations': list(form.specializations.data or []),
        'status': form.status.data,
        'payment_status': form.payment_status.data,
        'payment_amount': form.payment_amount.data,
        'attended': form.attended.data,
        'cpd_points_awarded': form.cpd_points_awarded.data,
        'experience_years': form.experience_years.data,
        'license_number': form.license_number.data,
        'admin_notes': form.admin_notes.data,
    }


# ===================== create (form) =====================

def _render_create(form, instance=None, instance_prices=None):
    return render_template(
        'admin/participant_edit.html',
        form=form, reg=None, instance=instance,
        fixed_instance=instance is not None,
        instance_prices=instance_prices or {},
    )


def _instance_prices(instances):
    """Map instance_id -> рядок ціни з розкладу (effective_price) для data-price.

    Порожній рядок, якщо ціни немає -- JS тоді нічого не підставляє.
    """
    return {
        i.id: ('%.2f' % i.effective_price) if i.effective_price is not None else ''
        for i in instances
    }


def _money_snapshot(reg):
    """Знімок платіжних полів реєстрації, за яку гроші вже пройшли онлайн.

    Повертає dict або None, якщо реєстрація не оплачена через LiqPay.
    payment_id -- саме той маркер, що відрізняє реальне списання від
    статусу 'paid', проставленого менеджером вручну (безкоштовна участь,
    оплата на рахунок): другий міняти можна, перший -- ні.
    """
    if not (reg.payment_id and reg.payment_status == 'paid'):
        return None
    return {
        'payment_amount': reg.payment_amount,
        'discount_amount': reg.discount_amount,
        'promo_code_id': reg.promo_code_id,
        'code': reg.promo_code.code if reg.promo_code else '',
    }


def _apply_promo_from_form(form, reg, instance, paid_snapshot=None):
    """Застосувати/зняти промокод на реєстрації за полем форми.

    payment_amount у формі трактується як сума ДО знижки, тож підсумок
    рахується від щойно збереженого значення. Порожнє поле знімає код і
    повертає використання у ліміт.

    paid_snapshot -- результат _money_snapshot(), знятий ДО upsert-у: для
    онлайн-оплаченої реєстрації суми відновлюються з нього, бо саме за
    ними LiqPay робитиме повернення коштів.

    Кидає PromoError -- caller показує його текст менеджеру.
    """
    raw = (form.promo_code.data or '').strip()

    if paid_snapshot is not None:
        if (promo_service.normalize_code(raw)
                != promo_service.normalize_code(paid_snapshot['code'])):
            raise PromoError(
                'Реєстрацію вже оплачено онлайн — промокод змінювати не можна. '
                'Спершу оформіть повернення коштів.'
            )
        # Форма показує суму ДО знижки, тож без відновлення звичайне
        # збереження підняло б payment_amount оплаченої реєстрації, і
        # повернення пішло б не на ту суму.
        reg.payment_amount = paid_snapshot['payment_amount']
        reg.discount_amount = paid_snapshot['discount_amount']
        reg.promo_code_id = paid_snapshot['promo_code_id']
        return None

    if not raw:
        # Безумовно, а не лише за наявності promo_code_id: після видалення
        # коду FK занулюється (SET NULL), а знімок знижки лишається сиротою
        # і роздував би суму при кожному збереженні форми.
        promo_service.detach(reg, reason='Промокод знято менеджером')
        return None

    if not reg.payment_amount or reg.payment_amount <= 0:
        raise PromoError(
            'Спершу вкажіть суму оплати — знижка рахується від неї'
        )

    promo, _discount, _final = promo_service.validate(
        raw, instance=instance, amount=reg.payment_amount,
    )
    # Ліміт "на людину" рахуємо без урахування цієї ж реєстрації: інакше
    # повторне збереження тієї самої форми впиралось би в саме себе.
    promo_service.assert_user_limit(
        promo, reg.user_id, ignore_registration_id=reg.id,
    )
    promo_service.apply_to_registration(promo, reg, reg.payment_amount)
    # Скасована/повернена реєстрація одразу звільняє використання коду --
    # той самий крок, що робить payment_ops після LiqPay-повернення (тут
    # він потрібен, бо статуси менеджер міняє руками).
    promo_service.sync_for_registration(reg)
    return promo


def _process_create(form, instance):
    """Спільна обробка POST для обох create-роутів. Повертає Response при
    успіху або None (треба відрендерити форму)."""
    data = _form_to_data(form, instance.id)
    try:
        reg, _created = participant_service.upsert_participant(
            data, reg=None, on_duplicate='error',
        )
        _apply_promo_from_form(form, reg, instance)
    except (ParticipantError, PromoError) as exc:
        db.session.rollback()
        flash(str(exc), 'error')
        return None

    if try_commit(log_context=f'participant_create instance={instance.id}'):
        audit_logger.info(
            'Admin %s added participant reg=%s to instance=%s',
            current_user.email, reg.id, instance.id,
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
    instance_prices = _instance_prices(instances)

    # На GET за замовчуванням підставляємо найближчий майбутній захід
    # (?instance_id= з URL має пріоритет).
    preselected = request.args.get('instance_id', type=int)
    if request.method == 'GET':
        form.instance_id.data = preselected or _nearest_upcoming_id(instances)

    if form.validate_on_submit():
        instance = db.session.get(CourseInstance, form.instance_id.data)
        if instance is None:
            flash('Захід не знайдено', 'error')
        else:
            response = _process_create(form, instance)
            if response is not None:
                return response

    return _render_create(form, instance_prices=instance_prices)


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
        # Сума за замовчуванням -- з налаштувань розкладу заходу (фіксований
        # захід рендериться без <select>, тож підставляємо на сервері).
        if form.payment_amount.data is None:
            form.payment_amount.data = instance.effective_price

    if form.validate_on_submit():
        response = _process_create(form, instance)
        if response is not None:
            return response

    return _render_create(form, instance=instance)


# ===================== edit (form) =====================

def _form_from_registration(reg):
    user = reg.user
    profile = user.medical_profile if user else None
    raw_email = user.email if user else ''
    email = '' if participant_service.is_placeholder_email(raw_email) else raw_email
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
        # Показуємо суму ДО знижки: інакше повторне збереження форми
        # застосувало б відсоток удруге, вже до зменшеної суми.
        'payment_amount': reg.amount_before_discount,
        'promo_code': reg.promo_code.code if reg.promo_code else '',
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
    form = ParticipantForm() if request.method == 'POST' else _form_from_registration(reg)
    form.instance_id.choices = [(reg.instance_id, _instance_label(instance) if instance else '—')]

    if form.validate_on_submit():
        data = _form_to_data(form, reg.instance_id)
        # Знімок знімаємо ДО upsert-у: він уже перезапише payment_amount
        # значенням із форми.
        paid_snapshot = _money_snapshot(reg)
        try:
            participant_service.upsert_participant(data, reg=reg)
            _apply_promo_from_form(form, reg, instance,
                                   paid_snapshot=paid_snapshot)
        except (ParticipantError, PromoError) as exc:
            db.session.rollback()
            flash(str(exc), 'error')
            return render_template(
                'admin/participant_edit.html',
                form=form, reg=reg, instance=instance, fixed_instance=True,
            )
        if try_commit(log_context=f'participant_edit reg={reg.id}'):
            audit_logger.info(
                'Admin %s edited participant reg=%s', current_user.email, reg.id,
            )
            flash('Дані учасника оновлено', 'success')
            return redirect(url_for('admin.instance_registrations', instance_id=reg.instance_id))

    return render_template(
        'admin/participant_edit.html',
        form=form, reg=reg, instance=instance, fixed_instance=True,
    )


# ===================== xlsx export / import =====================

def _participants_back_url():
    """Куди повертатись із preview/після apply. Якщо прийшли зі сторінки
    конкретного заходу -- туди; інакше -- загальний список реєстрацій."""
    instance_id = request.args.get('instance_id', type=int)
    if instance_id:
        return url_for('admin.instance_registrations', instance_id=instance_id)
    return url_for('admin.registrations_all')


@admin_bp.route('/participants/export')
@admin_required
def participants_export():
    """Експорт учасників у xlsx. URL params:
      ?instance_id=  -- лише цей захід (форма-шаблон для його учасників)
      ?blank=1       -- порожній шаблон (лише заголовки + dropdown-и, без даних)
    """
    instance_id = request.args.get('instance_id', type=int)
    blank = request.args.get('blank', '').lower() in ('1', 'true', 'yes')
    data = xlsx_io.export_participants_xlsx(instance_id=instance_id, blank=blank)
    audit_logger.info(
        'Admin %s exported participants xlsx (instance_id=%s blank=%s)',
        current_user.email, instance_id, blank,
    )
    if blank:
        name = 'participants-template'
    else:
        name = f'participants{("-instance%d" % instance_id) if instance_id else ""}'
    return send_file(
        data,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'{name}-{datetime.now().strftime("%Y%m%d-%H%M")}.xlsx',
        max_age=0,
    )


@admin_bp.route('/participants/import', methods=['POST'])
@admin_required
def participants_import_upload():
    f = request.files.get('xlsx')
    back = _participants_back_url()
    if not f or not f.filename:
        flash('Оберіть файл .xlsx для завантаження', 'error')
        return redirect(back)
    if not f.filename.lower().endswith('.xlsx'):
        flash('Формат файлу має бути .xlsx', 'error')
        return redirect(back)

    token = xlsx_io.save_uploaded_xlsx(f)
    audit_logger.info(
        'Admin %s uploaded participants xlsx for preview (token=%s)',
        current_user.email, token,
    )
    instance_id = request.args.get('instance_id', type=int)
    return redirect(url_for(
        'admin.participants_import_preview', token=token, instance_id=instance_id,
    ))


@admin_bp.route('/participants/import/preview/<token>')
@admin_required
def participants_import_preview(token):
    path = xlsx_io.get_uploaded_path(token)
    if path is None:
        flash('Файл імпорту не знайдено або сесія застаріла', 'error')
        return redirect(_participants_back_url())

    plan = xlsx_io.parse_participants_xlsx(path)
    instance_id = request.args.get('instance_id', type=int)
    return render_template(
        'admin/xlsx_preview.html',
        entity='participants',
        token=token,
        plan=plan,
        apply_url=url_for('admin.participants_import_apply', token=token, instance_id=instance_id),
        cancel_url=url_for('admin.participants_import_cancel', token=token, instance_id=instance_id),
        back_url=_participants_back_url(),
        title='Імпорт учасників',
    )


@admin_bp.route('/participants/import/apply/<token>', methods=['POST'])
@admin_required
def participants_import_apply(token):
    path = xlsx_io.get_uploaded_path(token)
    if path is None:
        flash('Файл імпорту не знайдено або сесія застаріла', 'error')
        return redirect(_participants_back_url())

    plan = xlsx_io.parse_participants_xlsx(path)
    if not plan.is_valid:
        flash('У файлі є помилки валідації – імпорт відхилено.', 'error')
        instance_id = request.args.get('instance_id', type=int)
        return redirect(url_for(
            'admin.participants_import_preview', token=token, instance_id=instance_id,
        ))

    result = xlsx_io.apply_participants_plan(plan)
    if result.get('ok'):
        xlsx_io.cleanup_upload(token)
        audit_logger.info(
            'Admin %s applied participants xlsx: created=%s updated=%s skipped=%s',
            current_user.email, result.get('created'), result.get('updated'),
            result.get('skipped'),
        )
        msg = (
            f'Імпорт виконано: створено {result["created"]}, '
            f'оновлено {result["updated"]} учасник(ів)'
        )
        if result.get('skipped'):
            msg += f', без змін {result["skipped"]}'
        flash(msg + '.', 'success')
        return redirect(_participants_back_url())

    flash(f'Помилка при збереженні: {result.get("reason")}', 'error')
    instance_id = request.args.get('instance_id', type=int)
    return redirect(url_for(
        'admin.participants_import_preview', token=token, instance_id=instance_id,
    ))


@admin_bp.route('/participants/import/cancel/<token>', methods=['POST'])
@admin_required
def participants_import_cancel(token):
    xlsx_io.cleanup_upload(token)
    flash('Імпорт скасовано', 'info')
    return redirect(_participants_back_url())
