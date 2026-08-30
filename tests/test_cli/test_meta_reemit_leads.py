"""Бекфіл заявок, уже надісланих партнеру старим payload-ом.

Без цієї команди робота не має сенсу для НАЯВНИХ заявок: вони доїхали до
партнера без `answers` і без `offer`, а самі себе не перевідправлять.

Ідемпотентність тримає ПРИЙМАЧ (унікальний `leadgen_id` на його боці), а
не ця команда. Тут -- лише відбір і `--dry-run`, щоб було видно, що саме
поїде, перш ніж воно поїде.
"""
import itertools
from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models.meta_lead import MetaLead

# Лічильник, а не id(object()): у CPython щойно звільнена адреса тимчасового
# object() детерміновано переюзається наступним викликом у тому самому
# виразі, тож два _lead() з однаковим days_ago в одному тесті інакше
# отримували б однаковий leadgen_id і падали на UNIQUE constraint.
_lead_seq = itertools.count()


def _lead(days_ago, **over):
    params = {
        'leadgen_id': f'lg-{days_ago}-{next(_lead_seq)}',
        'created_time': datetime.now(timezone.utc) - timedelta(days=days_ago),
        'form_id': '900',
        'field_data': {},
        'email': f'lead{days_ago}@test.local',
    }
    params.update(over)
    lead = MetaLead(**params)
    db.session.add(lead)
    db.session.flush()
    return lead


@pytest.fixture
def partner_on(app):
    """Увімкнена партнерська інтеграція -- умова, за якої команда щось робить.

    Без неї `enqueue_partner_event` не ставить у чергу нічого, і бекфіл
    лише мовчки перебирає історію.
    """
    from app.models.site_settings import SiteSettings

    settings = SiteSettings.get()
    before = (settings.partner_integration_enabled,
              settings.mm_medic_integration_enabled,
              settings.mm_medic_api_base_url)
    settings.partner_integration_enabled = True
    settings.mm_medic_integration_enabled = True
    settings.mm_medic_api_base_url = 'https://mm-medic.test'
    db.session.commit()

    yield settings

    (settings.partner_integration_enabled,
     settings.mm_medic_integration_enabled,
     settings.mm_medic_api_base_url) = before
    db.session.commit()


def _since():
    return (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()


def _clear_queue():
    from app.models.webhook_delivery import WebhookDelivery

    WebhookDelivery.query.filter(
        WebhookDelivery.event_type.isnot(None)).delete(
            synchronize_session=False)
    db.session.commit()


def test_only_leads_since_the_date_are_replayed(app, partner_on, monkeypatch):
    sent = []
    monkeypatch.setattr('app.services.partner_events.emit_lead_created',
                        lambda lead: sent.append(lead.leadgen_id))
    recent = _lead(2)
    _lead(90)
    db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(args=['meta-reemit-leads', '--since', _since()])

    assert result.exit_code == 0
    assert sent == [recent.leadgen_id]


def test_dry_run_sends_nothing(app, monkeypatch):
    sent = []
    monkeypatch.setattr('app.services.partner_events.emit_lead_created',
                        lambda lead: sent.append(lead.leadgen_id))
    _lead(1)
    db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(
        args=['meta-reemit-leads', '--since', _since(), '--dry-run'])

    assert result.exit_code == 0
    assert sent == []
    assert 'буде надіслано' in result.output


def test_test_and_deleted_leads_are_skipped(app, partner_on, monkeypatch):
    """Ті самі відсіювання, що й у живому шляху: чужу базу не смітимо."""
    sent = []
    monkeypatch.setattr('app.services.partner_events.emit_lead_created',
                        lambda lead: sent.append(lead.leadgen_id))
    _lead(1, is_test=True)
    _lead(1, deleted_at=datetime.now(timezone.utc))
    db.session.commit()

    runner = app.test_cli_runner()
    runner.invoke(args=['meta-reemit-leads', '--since', _since()])

    assert sent == []


def test_report_counts_rows_that_really_reached_the_queue(app, partner_on):
    """Рахуємо ПОСТАНОВКИ в чергу, а не виклики.

    `emit_lead_created` мовчки відсіює заявку без жодного контакту, а
    `enqueue_partner_event` не ставить нічого, коли слати нікуди. Лічильник
    викликів казав «2 із 2» там, де в черзі нуль -- і оператор вважав
    історію перенесеною.
    """
    from app.models.webhook_delivery import WebhookDelivery

    _clear_queue()
    _lead(1)
    _lead(1, email=None)
    db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(args=['meta-reemit-leads', '--since', _since()])

    assert result.exit_code == 0
    queued = WebhookDelivery.query.filter_by(event_type='lead.created').count()
    assert queued == 1
    assert 'Поставлено в чергу подій: 1 із 2' in result.output


def test_disabled_integration_is_said_out_loud(app, monkeypatch):
    """Вимкнена інтеграція -- окремий рядок, а не зелене число.

    Інакше прогін звітував про успіх, не поставивши в чергу жодного рядка.
    """
    from app.models.site_settings import SiteSettings
    from app.services import partner_events

    settings = SiteSettings.get()
    settings.partner_integration_enabled = False
    db.session.commit()
    sent = []
    monkeypatch.setattr(partner_events, 'emit_lead_created',
                        lambda lead: sent.append(lead.leadgen_id))
    _lead(1)
    db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(args=['meta-reemit-leads', '--since', _since()])

    assert 'вимкнен' in result.output
    assert sent == []


def test_dry_run_shows_how_many_go_without_an_offer(app, partner_on):
    """Заявку без прив'язаної форми видно ДО прогону, а не після.

    Приймач партнера відсіює дубль за `leadgen_id` першим, тож перша
    доставка -- єдина, що запише захід. Бекфіл, запущений до прив'язки
    форм, лишає ці заявки без заходу назавжди.
    """
    from app.models.course import Course
    from app.models.course_instance import CourseInstance
    from app.models.meta_lead import MetaLeadForm

    course = Course(title='Курс бекфілу', slug='backfill-course')
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(
        course_id=course.id, status='published',
        start_date=datetime.now(timezone.utc) + timedelta(days=20))
    db.session.add(instance)
    db.session.flush()
    db.session.add(MetaLeadForm(form_id='901', questions={},
                                course_instance_id=instance.id))
    db.session.flush()
    _lead(1, form_id='901')
    _lead(1, form_id='902')
    db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(
        args=['meta-reemit-leads', '--since', _since(), '--dry-run'])

    assert result.exit_code == 0
    assert 'Без заходу' in result.output
    assert '1' in result.output.split('Без заходу')[1].splitlines()[0]
