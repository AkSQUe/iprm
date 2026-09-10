"""Рядок «Спеціальності:» у сертифікаті: джерело, порядок, розмір шрифту."""
import re
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.registration import EventRegistration
from app.models.site_settings import SiteSettings
from app.models.specialty import Specialty
from app.models.user import User
from app.services import certificate_service
from app.services.certificate_service import _specialties_size_class, render_certificate_html


def test_short_line_keeps_base_size():
    assert _specialties_size_class('Алергологія') == 'cert__meta-line--md'


def test_long_line_gets_smaller_class():
    line = ', '.join(['Дитяча кардіоревматологія'] * 6)
    assert _specialties_size_class(line) == 'cert__meta-line--xs'


def test_empty_line_is_md():
    assert _specialties_size_class('') == 'cert__meta-line--md'


def test_mid_length_line_gets_sm_class():
    # ~110 символів -- типовий реальний перелік із 5-6 назв довідника.
    line = ', '.join(['Дерматовенерологія', 'Ендокринологія', 'Кардіологія',
                      'Неврологія', 'Педіатрія'])
    assert _specialties_size_class(line) == 'cert__meta-line--sm'


# --- наскрізна перевірка: клас доїжджає з сервісу в розмітку -----------------
#
# Тести вище перевіряють ЧИСТУ функцію і `certificate.specialties`, але не
# те, що `render_certificate_html` справді передає `specialties_size_class`
# у шаблон і що шаблон справді ставить його в `class=` того самого `<p>`.
# Без цього тесту прибрати рядок `specialties_size_class=...` з контексту
# рендеру (app/services/certificate_service.py) можна непомітно -- решта
# тестів файлу лишиться зеленою.

def _fake_certificate(specialties):
    """Легкий об'єкт для render_certificate_html -- той самий набір полів,
    що збирає render_adhoc_pdf (SimpleNamespace, без запису в БД)."""
    return SimpleNamespace(
        number='2026-2738-1000555-000001',
        recipient_name='Тестовий Тест Тестович',
        event_title='Сучасний курс',
        event_date=None,
        cpd_points=10,
        lecturer_name=None,
        lecturer_signature=None,
        specialties=specialties,
        event_type_label='семінар',
        event_place='м. Київ',
        issued_at=datetime.now(timezone.utc),
    )


def _specialties_p_class(html):
    """Клас <p> рядка «Спеціальності:» у розмітці, або None, якщо рядка нема."""
    m = re.search(r'<p class="([^"]*)">Спеціальності:', html)
    return m.group(1) if m else None


def test_render_context_puts_md_class_on_short_specialties_paragraph(app):
    html = render_certificate_html(_fake_certificate('Алергологія'), cert_format='a4')
    assert _specialties_p_class(html) == 'cert__meta-line--md'


def test_render_context_puts_xs_class_on_long_specialties_paragraph(app):
    # 10 реальних назв довідника -- той самий перелік, яким перевірялось
    # прев'ю очима (189 символів, > порогу xs у 120).
    from app.data.specialties import SPECIALTIES
    names = [n for _, n, section, _ in SPECIALTIES if section == 'medical'][:10]
    line = ', '.join(names)
    assert len(line) > 120  # страхуємось від тихої зміни довідника

    html = render_certificate_html(_fake_certificate(line), cert_format='a4')
    assert _specialties_p_class(html) == 'cert__meta-line--xs'


def test_render_context_omits_specialties_paragraph_when_empty(app):
    # Не шукаємо просто підрядок «Спеціальності:» -- він є і в CSS-коментарі
    # над класами розміру, незалежно від даних. Перевіряємо саме відсутність
    # самого <p> рядка.
    html = render_certificate_html(_fake_certificate(None), cert_format='a4')
    assert _specialties_p_class(html) is None


# --- знімок сертифіката: джерело й незалежність від подальших правок довідника ---

@pytest.fixture
def _no_pdf(monkeypatch):
    """Не малювати PDF при видачі сертифіката -- WeasyPrint тут не тестуємо."""
    monkeypatch.setattr(certificate_service, '_write_pdf', lambda cert: '/dev/null')


def _registration_with_codes(codes):
    settings = SiteSettings.get()
    settings.bpr_provider_number = '2738'
    course = Course(
        title=f'Курс {uuid4().hex[:4]}', slug=f'cert-spec-line-{uuid4().hex[:6]}',
        is_active=True, event_type='course', bpr_event_number=str(uuid4().int)[:7],
        bpr_specialty_codes=codes,
    )
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(
        course_id=course.id, status='completed', event_format='offline',
        location='Київ', start_date=datetime.now(timezone.utc) - timedelta(days=5),
    )
    db.session.add(instance)
    user = User.create_with_password(
        f'cert-spec-line-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='Тест', last_name='Тестовий', email_confirmed=True,
    )
    db.session.flush()
    reg = EventRegistration(
        user_id=user.id, instance_id=instance.id, phone='+380501234567',
        specialty='Терапія', workplace='Клініка', status='completed',
        payment_status='paid', attended=True,
    )
    db.session.add(reg)
    db.session.commit()
    return reg


def test_snapshot_comes_from_effective_codes_in_directory_order(app, _no_pdf):
    """Знімок -- рядок довідника через кому, у порядку номенклатури, а не
    у порядку, в якому коди перелічені в bpr_specialty_codes."""
    db.session.add_all([
        Specialty(code='kardiolohiia', name='Кардіологія', section='medical',
                 sort_order=29),
        Specialty(code='alerholohiia', name='Алергологія', section='medical',
                 sort_order=2),
    ])
    db.session.commit()
    # Код "пізнішої" спеціальності навмисно першим у списку курсу.
    reg = _registration_with_codes(['kardiolohiia', 'alerholohiia'])

    cert = certificate_service.issue_certificate(reg)

    assert cert.specialties == 'Алергологія, Кардіологія'


def test_snapshot_ignores_visitor_locale(app, _no_pdf):
    """Мова знімка -- завжди українська, незалежно від локалі, з якої
    учасник спричинив видачу (наприклад, склав тест на /ru/). Офіційний
    документ БПР не можна видавати з мовно-мішаним рядком спеціальностей."""
    row = Specialty(code='alerholohiia', name='Алергологія', section='medical',
                    sort_order=2)
    db.session.add(row)
    db.session.commit()
    row.set_translation('ru', 'name', 'Аллергология')
    db.session.commit()
    reg = _registration_with_codes(['alerholohiia'])

    with app.test_request_context('/ru/'):
        from flask import g
        g.lang_code = 'ru'
        cert = certificate_service.issue_certificate(reg)

    assert cert.specialties == 'Алергологія'


def test_renaming_directory_row_after_issue_does_not_change_snapshot(app, _no_pdf):
    """Знімок -- це знімок: перейменування рядка довідника ПІСЛЯ видачі не
    повинно змінювати вже виданий сертифікат."""
    row = Specialty(code='alerholohiia', name='Алергологія', section='medical',
                    sort_order=2)
    db.session.add(row)
    db.session.commit()
    reg = _registration_with_codes(['alerholohiia'])

    cert = certificate_service.issue_certificate(reg)
    assert cert.specialties == 'Алергологія'

    row.name = 'Нова назва розділу'
    db.session.commit()

    db.session.refresh(cert)
    assert cert.specialties == 'Алергологія', (
        'знімок сертифіката не повинен стежити за подальшими правками довідника'
    )
