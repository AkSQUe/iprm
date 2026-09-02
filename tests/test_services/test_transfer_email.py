"""Лист-пропозиція при перенесенні.

Головне, що тут перевіряється: порожні причина й примітка не дають ані
заголовка, ані порожнього блоку. Це прямий пункт технічного завдання.
"""
from datetime import timedelta

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.email_log import EmailLog
from app.models.mixins import utcnow
from app.models.registration import EventRegistration
from app.models.user import User
from app.services import transfer_service
from tests.refund_fixtures import purge

PREFIX = 'rte-'


@pytest.fixture
def world(app):
    user = User(email=f'{PREFIX}one@example.com', first_name='Тест',
                last_name='Переносний', is_active=True)
    course = Course(title='Курс переносу', slug=f'{PREFIX}course')
    db.session.add_all([user, course])
    # flush ПЕРЕД set_password: воно вимагає persisted user (user.id), інакше
    # RuntimeError -- див. відому пастку з Task 1.
    db.session.flush()
    user.set_password('x' * 12)
    now = utcnow()
    src = CourseInstance(course_id=course.id, status='published',
                         start_date=now + timedelta(days=10), price=1000)
    dst = CourseInstance(course_id=course.id, status='published',
                         start_date=now + timedelta(days=20), price=1000)
    db.session.add_all([src, dst])
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=src.id, phone='+380000000000',
        specialty='Лікар', workplace='Клініка', status='confirmed',
        payment_status='paid', payment_amount=1000,
    )
    db.session.add(reg)
    db.session.commit()
    yield reg, dst
    purge(PREFIX, slug_prefix=PREFIX)


def test_transfer_trigger_is_allowed():
    """Інваріант TRIGGERS <-> ck_email_logs_trigger стереже
    test_all_code_triggers_are_allowed / test_check_constraint_matches_allowed_triggers
    (tests/test_services/test_email_service.py); тут перевіряємо саме новий код."""
    assert EmailLog.is_valid_trigger('transfer')


def test_offer_renders_reason_and_note(world, app):
    reg, dst = world
    transfer = transfer_service.execute(
        reg, target_instance=dst, initiator='organizer',
        tariff_decision='keep', reason='Тренер захворів',
        note='Місце проведення те саме', announced=False,
    )
    html = _render(app, transfer)
    assert 'Тренер захворів' in html
    assert 'Місце проведення те саме' in html


def test_offer_omits_empty_reason_and_note(world, app):
    """Порожні поля не мають лишати ані заголовка, ані порожнього блоку."""
    reg, dst = world
    transfer = transfer_service.execute(
        reg, target_instance=dst, initiator='organizer',
        tariff_decision='keep', announced=False,
    )
    html = _render(app, transfer)
    assert 'Причина перенесення' not in html
    assert 'Примітка' not in html


def test_offer_contains_both_choices(world, app):
    reg, dst = world
    transfer = transfer_service.execute(
        reg, target_instance=dst, initiator='organizer',
        tariff_decision='keep', announced=False,
    )
    transfer.issue_consent_token()
    db.session.commit()
    html = _render(app, transfer)
    assert f'/registration/transfer/{transfer.consent_token}' in html


def test_offer_escapes_html_in_note(world, app):
    """`note` -- вільний текст адміна. Без екранування <b>/& потрапили б
    учаснику в пошту як розмітка, а не як символи, які він набрав."""
    reg, dst = world
    transfer = transfer_service.execute(
        reg, target_instance=dst, initiator='organizer',
        tariff_decision='keep',
        note='Увага <b>важливо</b> & дякуємо за розуміння',
        announced=False,
    )
    html = _render(app, transfer)
    assert '<b>важливо</b>' not in html
    assert '&lt;b&gt;важливо&lt;/b&gt;' in html
    assert '&amp;' in html


def test_offer_surcharge_branch_explains_participation_stays_valid(app):
    """Рішення власника фічі: участь дійсна одразу після згоди, доплата --
    окрема дія, що на місце не впливає. Лист має сказати це прямо, інакше
    мовчання читається як протилежне (наче без оплати місця не буде)."""
    reg, dst = _build_scenario('surcharge', 'course-surcharge', dst_price=1500)
    try:
        transfer = transfer_service.execute(
            reg, target_instance=dst, initiator='participant',
            tariff_decision='surcharge', announced=False,
        )
        transfer.issue_consent_token()
        db.session.commit()
        surcharge_url = (f'https://example.com/registration/transfer/'
                         f'{transfer.consent_token}/surcharge')
        html = _render(app, transfer, surcharge_url=surcharge_url)
        assert 'не впливає на ваше місце' in html
        assert 'Доплатити 500' in html
    finally:
        purge(PREFIX, slug_prefix=PREFIX)


def test_offer_refund_diff_branch_renders(app):
    reg, dst = _build_scenario('refund', 'course-refund', dst_price=700)
    try:
        transfer = transfer_service.execute(
            reg, target_instance=dst, initiator='organizer',
            tariff_decision='refund_diff', announced=False,
        )
        transfer.issue_consent_token()
        db.session.commit()
        html = _render(app, transfer)
        assert 'Різницю повернемо' in html
        assert '300' in html
    finally:
        purge(PREFIX, slug_prefix=PREFIX)


def test_offer_without_consent_token_falls_back_to_reply(world, app):
    """Без токена (наприклад, лист шлеться до issue_consent_token) шаблон
    не має друкувати биту адресу з 'None' -- лише запасний текст."""
    reg, dst = world
    transfer = transfer_service.execute(
        reg, target_instance=dst, initiator='organizer',
        tariff_decision='keep', announced=False,
    )
    html = _render(app, transfer)
    assert 'None' not in html
    assert 'Дайте відповідь на цей лист' in html


def _build_scenario(email_suffix, slug_suffix, dst_price):
    """Реєстрація + два проведення з РІЗНИМИ цінами -- `world` навмисно
    тримає однакову ціну (гілка 'keep' без різниці); гілки surcharge/
    refund_diff потребують окремого сетапу."""
    user = User(email=f'{PREFIX}{email_suffix}@example.com', first_name='Тест',
                last_name='Переносний', is_active=True)
    course = Course(title='Курс переносу', slug=f'{PREFIX}{slug_suffix}')
    db.session.add_all([user, course])
    db.session.flush()
    user.set_password('x' * 12)
    now = utcnow()
    src = CourseInstance(course_id=course.id, status='published',
                         start_date=now + timedelta(days=10), price=1000)
    dst = CourseInstance(course_id=course.id, status='published',
                         start_date=now + timedelta(days=20), price=dst_price)
    db.session.add_all([src, dst])
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=src.id, phone='+380000000000',
        specialty='Лікар', workplace='Клініка', status='confirmed',
        payment_status='paid', payment_amount=1000,
    )
    db.session.add(reg)
    db.session.commit()
    return reg, dst


def _render(app, transfer, surcharge_url=None):
    from flask import render_template
    with app.test_request_context():
        from app.models.site_settings import SiteSettings
        # Той самий запобіжник, що й у send_transfer_offer: без токена
        # consent_url -- None, а не рядок із буквальним 'None' у ньому.
        consent_url = (f'https://example.com/registration/transfer/{transfer.consent_token}'
                       if transfer.consent_token else None)
        return render_template(
            'emails/transfer_offer.html',
            user=transfer.registration.user,
            transfer=transfer,
            registration=transfer.registration,
            consent_url=consent_url,
            surcharge_url=surcharge_url,
            site_settings=SiteSettings.get(),
        )
