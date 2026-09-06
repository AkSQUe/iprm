"""Діагностичні реєстри адмінки: технічне значення веде у ЦЕЙ ЖЕ реєстр,
звужений цим значенням -- без успадкування поточних фільтрів сторінки.

Журнал помилок: тип помилки, шлях і код -- кожен окремим посиланням.
Журнал листів: адресат (`q`) і тригер (`trigger`, саме поле моделі, а не
`trigger_label`). Meta-ліди: кампанія і форма, лише коли є відповідний id.
"""
from tests.support.rbac import grant_role
import re
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from flask import url_for

from app.extensions import db
from app.models.error_log import ErrorLog
from app.models.email_log import EmailLog
from app.models.meta_lead import MetaLead
from app.models.user import User


def _uid():
    return uuid4().hex[:8]


@pytest.fixture
def admin(app):
    u = User.create_with_password(
        f'dl-{_uid()}@test.com', 'password123',
        first_name='D', last_name='L', email_confirmed=True,
    )
    grant_role(u, 'super_admin')
    db.session.commit()
    yield u
    db.session.rollback()
    db.session.delete(db.session.merge(u))
    db.session.commit()


def _login(client, user):
    with client.session_transaction() as s:
        s['_user_id'] = str(user.id)


def test_error_type_links_to_error_logs_by_q(client, admin, app):
    """`days=0` у href -- журнал за замовчуванням показує лише 7 днів, а
    сторінка відкрита з «За весь час»: без цього параметра клік повертав би
    у вікно, де щойно натиснутого рядка вже нема."""
    error_type = f'DlTestError{_uid()}'
    log = ErrorLog(
        error_code=500, error_type=error_type, error_message='боум',
        url='https://iprm.space/kudys',
    )
    db.session.add(log)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/error-logs?q={error_type}&days=0').get_data(as_text=True)
        with app.test_request_context():
            href = url_for('admin.error_logs', q=error_type, days=0)
        # Jinja екранує '&' у href в '&amp;' -- порівнюємо з тим, що реально
        # потрапляє в HTML.
        href_in_html = href.replace('&', '&amp;')
        assert re.search(
            rf'<a href="{re.escape(href_in_html)}">\s*<code[^>]*>\s*{re.escape(error_type)}',
            html,
        )
    finally:
        db.session.delete(db.session.merge(log))
        db.session.commit()


def test_url_path_links_to_error_logs_by_q(client, admin, app):
    path = f'/dl-{_uid()}/kudys'
    log = ErrorLog(
        error_code=404, error_type='NotFound', error_message='немає',
        url=f'https://iprm.space{path}',
    )
    db.session.add(log)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/error-logs?q={path}&days=0').get_data(as_text=True)
        with app.test_request_context():
            href = url_for('admin.error_logs', q=path, days=0)
        href_in_html = href.replace('&', '&amp;')
        assert re.search(rf'<a href="{re.escape(href_in_html)}">\s*<span[^>]*>\s*{re.escape(path)}', html)
    finally:
        db.session.delete(db.session.merge(log))
        db.session.commit()


def test_error_code_links_to_error_logs_by_error_code(client, admin, app):
    error_type = f'DlCodeError{_uid()}'
    log = ErrorLog(
        error_code=404, error_type=error_type, error_message='немає',
        url='https://iprm.space/x',
    )
    db.session.add(log)
    db.session.commit()
    _login(client, admin)
    try:
        # Фільтруємо по q (унікальний error_type), щоб на сторінці був лише
        # наш рядок, а перевіряємо -- посилання коду з error_code, окремого
        # фільтра, який не успадковує q поточного зрізу.
        html = client.get(f'/admin/error-logs?q={error_type}&days=0').get_data(as_text=True)
        with app.test_request_context():
            href = url_for('admin.error_logs', error_code=404, days=0)
        href_in_html = href.replace('&', '&amp;')
        assert re.search(rf'<a href="{re.escape(href_in_html)}">\s*<span[^>]*>\s*404', html)
    finally:
        db.session.delete(db.session.merge(log))
        db.session.commit()


def test_notification_recipient_links_to_notifications_log_by_q(client, admin):
    email = f'dl-{_uid()}@test.com'
    log = EmailLog(
        to_email=email, subject='Тема', template_name='test.html',
        status='sent', trigger='test',
    )
    db.session.add(log)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/notifications/log?q={email}').get_data(as_text=True)
        href = f'/admin/notifications/log?q={email}'
        assert re.search(rf'<a href="{re.escape(href)}">\s*<span[^>]*>\s*{re.escape(email)}', html)
    finally:
        db.session.delete(db.session.merge(log))
        db.session.commit()


def test_notification_trigger_links_by_trigger_field_not_label(client, admin):
    """`trigger=test` у href, а не текст лейбла `Тест` -- фільтр приймає код
    моделі, і посилання, зібране з `trigger_label`, тихо повернуло б усе."""
    email = f'dl-{_uid()}@test.com'
    log = EmailLog(
        to_email=email, subject='Тема', template_name='test.html',
        status='sent', trigger='test',
    )
    db.session.add(log)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/notifications/log?q={email}').get_data(as_text=True)
        href = '/admin/notifications/log?trigger=test'
        assert re.search(rf'<a href="{re.escape(href)}">\s*<span[^>]*>\s*Тест', html)
    finally:
        db.session.delete(db.session.merge(log))
        db.session.commit()


def test_meta_lead_campaign_and_form_link_to_own_filters(client, admin, app):
    """`test='with'` у href -- заявки тестові за замовчуванням сховані, і
    без цього параметра клік із «Лише тестові» приземлявся б у зрізі, звідки
    щойно натиснутий лід сам же й відфільтрований."""
    campaign_id = f'dlc{_uid()}'
    form_id = f'dlf{_uid()}'
    lead = MetaLead(
        leadgen_id=f'dl-{_uid()}', created_time=datetime.now(timezone.utc),
        campaign_id=campaign_id, campaign_name='Кампанія DL',
        form_id=form_id, form_name='Форма DL',
        first_name='Лід', last_name=_uid(),
    )
    db.session.add(lead)
    db.session.commit()
    _login(client, admin)
    try:
        html = client.get(f'/admin/meta-leads?campaign_id={campaign_id}').get_data(as_text=True)
        with app.test_request_context():
            campaign_href = url_for('admin.meta_leads_list', campaign_id=campaign_id, test='with')
            form_href = url_for('admin.meta_leads_list', form_id=form_id, test='with')
        campaign_href = campaign_href.replace('&', '&amp;')
        form_href = form_href.replace('&', '&amp;')
        assert re.search(rf'<a href="{re.escape(campaign_href)}">\s*Кампанія DL', html)
        assert re.search(rf'<a href="{re.escape(form_href)}">\s*Форма DL', html)
    finally:
        db.session.delete(db.session.merge(lead))
        db.session.commit()
