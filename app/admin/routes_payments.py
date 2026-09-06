import logging
from flask import render_template, redirect, url_for, flash, request
from flask_login import current_user
from sqlalchemy.orm import joinedload
from app.admin import admin_bp
from app.rbac import permission_required
from app.admin._helpers import (
    mask_secret, rotation_status, save_integration_settings,
    validate_liqpay_credentials,
)
from app.extensions import limiter
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.services.liqpay import get_liqpay_service

audit_logger = logging.getLogger('audit')


@admin_bp.route('/payments')
@permission_required('registrations.view')
def payments():
    return redirect(url_for('admin.integrations'))


@admin_bp.route('/liqpay')
@permission_required('integrations.view')
def liqpay():
    service = get_liqpay_service()
    from app.models.site_settings import SiteSettings
    settings = SiteSettings.get()
    cfg = {
        'public_key': mask_secret(service.public_key),
        'private_key': mask_secret(service.private_key),
        'sandbox': service.sandbox,
        'is_configured': service.is_configured,
        'webhook_url': url_for('payments.liqpay_callback', _external=True),
        'rotation': rotation_status(
            settings.liqpay_private_key_set_at,
            threshold_key='liqpay_private_key',
            is_secret_present=bool(settings.liqpay_private_key),
        ),
    }

    stats = EventRegistration.payment_stats()

    recent = EventRegistration.query.options(
        joinedload(EventRegistration.instance),
        joinedload(EventRegistration.user),
    ).filter(
        EventRegistration.payment_amount > 0,
    ).order_by(EventRegistration.created_at.desc()).limit(20).all()

    return render_template(
        'admin/liqpay.html',
        cfg=cfg,
        stats=stats,
        recent=recent,
    )


@admin_bp.route('/liqpay/save-keys', methods=['POST'])
@permission_required('integrations.keys')
def liqpay_save_keys():
    public_key = request.form.get('public_key', '').strip()
    private_key = request.form.get('private_key', '').strip()
    sandbox = request.form.get('sandbox') == 'on'

    settings = SiteSettings.get()

    # Враховуємо існуючі значення -- порожні поля у формі НЕ затирають
    # вже збережені ключі (mirror Google OAuth / Apple Sign In паттерн).
    # Це дозволяє адміну поміняти лише sandbox-toggle, не вводячи ключі
    # повторно.
    final_public = public_key or settings.liqpay_public_key
    final_private = private_key or settings.liqpay_private_key
    if not final_public or not final_private:
        flash('Обидва ключі обов\'язкові (хоча б один раз треба ввести)', 'error')
        return redirect(url_for('admin.liqpay'))

    # Phase A: validate-before-save -- викликаємо check_status з новими
    # ключами. Робимо ТІЛЬКИ якщо обидва ключі задано (нові або хоча б
    # один новий + один зі збереженого), щоб уникнути тестування з
    # неконсистентною комбінацією.
    if public_key or private_key:
        final_public = public_key or settings.liqpay_public_key
        final_private = private_key or settings.liqpay_private_key
        if final_public and final_private:
            ok, msg = validate_liqpay_credentials(
                final_public, final_private, sandbox,
            )
            if not ok:
                flash(f'Валідація LiqPay ключів не пройшла: {msg}', 'error')
                return redirect(url_for('admin.liqpay'))

    updates = {'liqpay_sandbox': sandbox}
    if public_key:
        updates['liqpay_public_key'] = public_key
    if private_key:
        updates['liqpay_private_key'] = private_key

    save_integration_settings(
        provider='liqpay',
        settings=settings,
        updates=updates,
        audit_summary={
            'sandbox': sandbox,
            'public_key_set': bool(public_key),
            'private_key_set': bool(private_key),
        },
        success_msg='Ключі LiqPay збережено',
        error_msg='Помилка при збереженні ключів',
    )
    return redirect(url_for('admin.liqpay'))


@admin_bp.route('/liqpay/test', methods=['POST'])
@permission_required('integrations.manage')
@limiter.limit("5 per minute")
def liqpay_test():
    service = get_liqpay_service()
    if not service.is_configured:
        flash('Спочатку збережіть ключі LiqPay', 'error')
        return redirect(url_for('admin.liqpay'))

    result = service.check_status('TEST-0')
    if result is not None:
        lp_err = result.get('err_code', '')
        lp_status = result.get('status', '')
        if lp_err == 'payment_not_found' or lp_status:
            flash('З\'єднання з LiqPay API успішне', 'success')
        else:
            err_desc = result.get('err_description', str(result))
            flash(f'LiqPay API відповів помилкою: {err_desc}', 'error')
    else:
        flash('Не вдалося з\'єднатися з LiqPay API. Перевірте ключі.', 'error')

    audit_logger.info('Admin %s tested LiqPay connection', current_user.email)
    return redirect(url_for('admin.liqpay'))


@admin_bp.route('/liqpay/reconcile', methods=['POST'])
@permission_required('integrations.manage')
@limiter.limit('10 per minute')
def liqpay_reconcile():
    """Ручна звірка: перепитати LiqPay про платежі, що зависли в 'pending'.

    Кнопка, а не лише фонова джоба, і це не зручність. Замовлення виходить
    з `pending` тільки повторним колбеком (його шле LiqPay, і загублений
    ніхто не перезапитує) або заходом самого платника на сторінку оплати.
    Коли верифікацію магазину відновлюють, потрібен рівно один прогін --
    чекати, поки кожен платник сам зайде, означає не дізнатись про оплату
    ніколи.
    """
    from app.services.payment_ops import reconcile_pending

    report = reconcile_pending()

    if report['error']:
        flash(report['error'], 'error')
        return redirect(url_for('admin.liqpay'))

    audit_logger.info(
        'Admin %s ran LiqPay reconcile: checked=%s updated=%s unchanged=%s '
        'failed=%s', current_user.email, report['checked'], report['updated'],
        report['unchanged'], report['failed'],
    )

    if not report['checked']:
        flash('Зависли платежів немає -- звіряти нема чого', 'info')
        return redirect(url_for('admin.liqpay'))

    # Порядкові підсумки И перелік замовлень: голі числа не кажуть, ЯКЕ саме
    # замовлення лишилось незмінним, а саме це питання виникає першим.
    summary = (f"Звірено {report['checked']}: оновлено {report['updated']}, "
               f"без змін {report['unchanged']}, помилок {report['failed']}")
    flash(f"{summary}. {'; '.join(report['details'])}",
          'error' if report['failed'] else 'success')
    return redirect(url_for('admin.liqpay'))
