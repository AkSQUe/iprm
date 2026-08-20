"""Тести вхідної черги лідів Meta: воркер, звірка, токен, моніторинг.

Тут перевіряється не «чи виконався код», а чи не втратимо ми заявку:
подія мусить доїхати до картки з першого прогону, транзієнтний збій --
дочекатися повтору, протухлий токен -- НЕ палити спроби, а звірка --
дібрати те, чого не приніс вебхук (критерій приймання N7 плану).

Мережі немає: `FakeMetaGraphClient` із `tests/support/fake_meta_graph.py`
підмінюється в названий шов `meta_lead_queue._client`.

**Тести в цьому наборі не ізольовані одне від одного** (див. розділ 6
плану: фікстура `db_session` збирає options і ніколи їх не застосовує, тож
усе закомічене сервісами живе до кінця прогону). Наслідків тут два, і
обидва враховані:

* кожен тест бере власний `leadgen_id` і рахує рядки ЗА НИМ, а не загальну
  кількість у таблиці;
* чужі події перед кожним тестом паркуються (`_park_foreign_events`),
  інакше залишок з інших файлів заповнив би батч воркера і наша подія
  просто не дісталася б обробки -- падало б це лише в повному прогоні.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from flask import render_template

from app.extensions import db
from app.models.meta_lead import MAX_EVENT_ATTEMPTS, MetaLead, MetaLeadEvent
from app.models.site_settings import SiteSettings
from app.services import meta_lead_queue as queue
from app.services import partner_events
from app.services.email_service import EmailService
from app.services.meta_contracts import MetaResult
from app.services.meta_lead_intake import enqueue_event
from tests.support.fake_meta_graph import (
    FakeMetaGraphClient,
    make_field_data,
    make_lead,
    make_webhook_value,
)


# --- фікстури-помічники ---------------------------------------------------

@pytest.fixture(autouse=True)
def _park_foreign_events(app):
    """Прибрати з черги події, залишені іншими тестами.

    Воркер бере найстаріші 25 подій, а залишок від тестів вебхука старший
    за наші -- без цього прибирання він з'їдав би весь батч. Термінальний
    статус тут -- найдешевший спосіб сказати «це не наша справа», не
    видаляючи чужих рядків.
    """
    MetaLeadEvent.query.filter(
        MetaLeadEvent.status.in_([MetaLeadEvent.STATUS_PENDING,
                                  MetaLeadEvent.STATUS_RETRYING])
    ).update({'status': MetaLeadEvent.STATUS_SKIPPED}, synchronize_session=False)
    db.session.commit()
    yield


def _gid():
    """Унікальний leadgen_id на кожен тест -- див. докстрінг модуля."""
    return f'{uuid4().int % 10 ** 15:015d}'


def _iso(delta_hours=0):
    """Час у формі Graph API (зсув без двокрапки, як його віддає Meta)."""
    moment = datetime.now(timezone.utc) - timedelta(hours=delta_hours)
    return moment.strftime('%Y-%m-%dT%H:%M:%S+0000')


def _configure(**over):
    """Налаштування інтеграції у відомому стані.

    Рядок налаштувань один на весь прогін і переживає відкат фікстури, тож
    покладатися на дефолти колонок не можна: попередній тест міг лишити
    увімкнений режим тестування або дату останнього алерту.
    """
    settings = SiteSettings.get()
    settings.meta_leads_enabled = True
    settings.meta_page_id = '555000111'
    settings.meta_reconcile_interval_minutes = 30
    settings.meta_reconcile_lookback_hours = 48
    settings.meta_silence_alert_hours = 24
    settings.meta_error_alert_threshold = 5
    settings.meta_test_mode = False
    settings.meta_last_lead_at = None
    settings.meta_last_reconcile_at = None
    settings.meta_last_reconcile_status = ''
    settings.meta_last_reconcile_error = ''
    settings.meta_alert_sent_at = None
    settings.meta_token_valid = None
    settings.meta_token_error = ''
    settings.meta_page_token_set_at = None
    for key, value in over.items():
        setattr(settings, key, value)
    db.session.commit()
    return settings


def _use(monkeypatch, client):
    """Підмінити клієнт Graph API на фейк."""
    monkeypatch.setattr(queue, '_client', lambda settings: client)
    return client


def _queued(leadgen_id, **over):
    """Подія в черзі, як її кладе вебхук."""
    value = make_webhook_value(leadgen_id=leadgen_id,
                               created_time=int(datetime.now(timezone.utc).timestamp()),
                               **over)
    event = enqueue_event(value)
    assert event is not None
    return event


def _event(leadgen_id):
    return MetaLeadEvent.query.filter_by(leadgen_id=leadgen_id).one()


def _leads(leadgen_id):
    return MetaLead.query.filter_by(leadgen_id=leadgen_id).all()


# --- воркер черги ---------------------------------------------------------

def test_event_reaches_lead_in_one_pass(app, monkeypatch):
    """Критерій приймання N1 у частині черги: подія -> картка за прогін."""
    gid = _gid()
    _configure()
    _use(monkeypatch, FakeMetaGraphClient(leads=[make_lead(gid, created_time=_iso())]))
    _queued(gid)

    stats = queue.process_queue()

    assert stats['done'] == 1
    event = _event(gid)
    assert event.status == MetaLeadEvent.STATUS_DONE
    assert event.processed_at is not None
    assert event.attempts == 1

    leads = _leads(gid)
    assert len(leads) == 1
    assert event.lead_id == leads[0].id
    assert SiteSettings.get().meta_last_lead_at is not None


def test_second_pass_does_not_create_second_lead(app, monkeypatch):
    """Повтор події не заводить другу картку -- лише позначку «дубль»."""
    gid = _gid()
    _configure()
    _use(monkeypatch, FakeMetaGraphClient(leads=[make_lead(gid, created_time=_iso())]))
    _queued(gid)
    queue.process_queue()

    event = _event(gid)
    event.status = MetaLeadEvent.STATUS_PENDING
    db.session.commit()

    stats = queue.process_queue()

    assert stats['skipped'] == 1
    assert len(_leads(gid)) == 1
    assert _event(gid).status == MetaLeadEvent.STATUS_SKIPPED


def test_transient_error_schedules_retry(app, monkeypatch):
    """Тимчасовий збій Graph API -- це «пізніше», а не «ніколи»."""
    gid = _gid()
    _configure()
    client = _use(monkeypatch, FakeMetaGraphClient(
        leads=[make_lead(gid, created_time=_iso())]))
    client.fail_next(1)
    _queued(gid)

    stats = queue.process_queue()

    assert stats['retrying'] == 1 and stats['failed'] == 0
    event = _event(gid)
    assert event.status == MetaLeadEvent.STATUS_RETRYING
    assert event.next_retry_at is not None
    assert event.attempts == 1
    assert not _leads(gid)


def test_retry_runs_after_backoff_and_succeeds(app, monkeypatch):
    """Після витримки та сама подія доїжджає до картки."""
    gid = _gid()
    _configure()
    client = _use(monkeypatch, FakeMetaGraphClient(
        leads=[make_lead(gid, created_time=_iso())]))
    client.fail_next(1)
    _queued(gid)
    queue.process_queue()

    event = _event(gid)
    event.next_retry_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.session.commit()

    stats = queue.process_queue()

    assert stats['done'] == 1
    assert _event(gid).status == MetaLeadEvent.STATUS_DONE
    assert len(_leads(gid)) == 1


def test_expired_token_is_not_retried(app, monkeypatch):
    """code=190 -- діагноз, а не збій: ретраї лише сховали б його."""
    gid = _gid()
    _configure()
    client = _use(monkeypatch, FakeMetaGraphClient(
        leads=[make_lead(gid, created_time=_iso())]))
    client.fail_next(1, code=FakeMetaGraphClient.TOKEN_ERROR_CODE,
                     http_status=400, message='Error validating access token')
    _queued(gid)

    stats = queue.process_queue()

    assert stats['failed'] == 1 and stats['retrying'] == 0
    event = _event(gid)
    assert event.status == MetaLeadEvent.STATUS_FAILED
    assert event.attempts == 1
    assert event.next_retry_at is None
    assert '190' in (event.last_error or '')


def test_failed_after_max_attempts_keeps_error_text(app, monkeypatch):
    """Остання спроба лишає по собі текст помилки, а не порожній статус."""
    gid = _gid()
    _configure()
    client = _use(monkeypatch, FakeMetaGraphClient(
        leads=[make_lead(gid, created_time=_iso())]))
    client.fail_next(1, message='service temporarily unavailable')
    event = _queued(gid)
    event.attempts = MAX_EVENT_ATTEMPTS - 1
    db.session.commit()

    stats = queue.process_queue()

    assert stats['failed'] == 1
    event = _event(gid)
    assert event.status == MetaLeadEvent.STATUS_FAILED
    assert event.attempts == MAX_EVENT_ATTEMPTS
    assert 'service temporarily unavailable' in event.last_error
    assert event.next_retry_at is None


def test_unknown_lead_in_graph_is_permanent(app, monkeypatch):
    """«Такого ліда немає» не лікується повтором -- крутити чергу намарно."""
    gid = _gid()
    _configure()
    _use(monkeypatch, FakeMetaGraphClient(leads=[]))
    _queued(gid)

    stats = queue.process_queue()

    assert stats['failed'] == 1
    assert _event(gid).status == MetaLeadEvent.STATUS_FAILED


def test_disabled_integration_leaves_event_pending(app, monkeypatch):
    """Вимкнений прапорець відкладає обробку, а не втрачає заявку."""
    gid = _gid()
    _configure(meta_leads_enabled=False)
    _use(monkeypatch, FakeMetaGraphClient(leads=[make_lead(gid, created_time=_iso())]))
    _queued(gid)

    stats = queue.process_queue()

    assert stats['processed'] == 0
    assert _event(gid).status == MetaLeadEvent.STATUS_PENDING


# --- партнерська подія ----------------------------------------------------

def test_partner_event_emitted_for_real_lead(app, monkeypatch):
    """Подія партнеру йде -- і саме після коміту заявки."""
    gid = _gid()
    _configure()
    _use(monkeypatch, FakeMetaGraphClient(leads=[make_lead(gid, created_time=_iso())]))
    _queued(gid)

    emitted = []
    # Підміняємо саме `emit`, а не `emit_lead_created`: інакше фільтр
    # тестових заявок лишився б неперевіреним -- він живе всередині.
    monkeypatch.setattr(partner_events, 'emit',
                        lambda event_type, payload: emitted.append((event_type, payload)))

    queue.process_queue()

    assert len(emitted) == 1
    event_type, payload = emitted[0]
    assert event_type == partner_events.LEAD_CREATED
    assert payload['leadgen_id'] == gid


def test_partner_event_not_emitted_for_test_lead(app, monkeypatch):
    """Заявка з режиму тестування в чужу базу не потрапляє."""
    gid = _gid()
    _configure(meta_test_mode=True)
    _use(monkeypatch, FakeMetaGraphClient(leads=[make_lead(gid, created_time=_iso())]))
    _queued(gid)

    emitted = []
    monkeypatch.setattr(partner_events, 'emit',
                        lambda event_type, payload: emitted.append((event_type, payload)))

    queue.process_queue()

    assert _leads(gid)[0].is_test is True
    assert emitted == []


def test_partner_event_not_emitted_for_lead_without_contacts(app, monkeypatch):
    """Заявка без пошти й номера -- рядок у звіті, а не картка партнеру."""
    gid = _gid()
    _configure()
    _use(monkeypatch, FakeMetaGraphClient(leads=[make_lead(
        gid, created_time=_iso(), field_data=make_field_data(city='Київ'))]))
    _queued(gid)

    emitted = []
    monkeypatch.setattr(partner_events, 'emit',
                        lambda event_type, payload: emitted.append((event_type, payload)))

    queue.process_queue()

    assert len(_leads(gid)) == 1
    assert emitted == []


# --- звірка (критерій приймання N7) ---------------------------------------

def test_reconcile_pulls_unknown_lead_and_skips_known(app, monkeypatch):
    """Критерій N7: звірка добирає невідомий лід і не дублює відомий."""
    unknown, known = _gid(), _gid()
    _configure()
    _use(monkeypatch, FakeMetaGraphClient(leads=[
        make_lead(unknown, created_time=_iso(1)),
        make_lead(known, created_time=_iso(2)),
    ]))
    _queued(known)

    stats = queue.reconcile()

    assert stats['checked_forms'] == 1
    assert stats['fetched'] == 2
    assert stats['created'] == 1
    assert stats['skipped'] == 1

    new_event = _event(unknown)
    assert new_event.source == MetaLeadEvent.SOURCE_RECONCILE
    assert MetaLeadEvent.query.filter_by(leadgen_id=known).count() == 1

    # І далі звичайним шляхом: подія звірки доходить до картки так само,
    # як подія вебхука -- у цьому й сенс однієї черги на два джерела.
    queue.process_queue()
    assert len(_leads(unknown)) == 1


def test_reconcile_ignores_inactive_forms(app, monkeypatch):
    """Архівна форма не варта ані запиту, ані квоти."""
    gid = _gid()
    _configure()
    _use(monkeypatch, FakeMetaGraphClient(
        leads=[make_lead(gid, created_time=_iso())],
        forms=[{'id': '9988776655', 'name': 'Стара форма', 'status': 'ARCHIVED'}],
    ))

    stats = queue.reconcile()

    assert stats['checked_forms'] == 0
    assert stats['fetched'] == 0
    assert MetaLeadEvent.query.filter_by(leadgen_id=gid).count() == 0


def test_reconcile_respects_lookback_window(app, monkeypatch):
    """Глибина береться з налаштувань і йде в запит як since_ts."""
    old, fresh = _gid(), _gid()
    _configure(meta_reconcile_lookback_hours=6)
    client = _use(monkeypatch, FakeMetaGraphClient(leads=[
        make_lead(old, created_time=_iso(48)),
        make_lead(fresh, created_time=_iso(1)),
    ]))

    stats = queue.reconcile()

    assert stats['fetched'] == 1
    assert MetaLeadEvent.query.filter_by(leadgen_id=fresh).count() == 1
    assert MetaLeadEvent.query.filter_by(leadgen_id=old).count() == 0

    since = [c for c in client.calls if c[0] == 'list_form_leads'][0][2]
    expected = datetime.now(timezone.utc) - timedelta(hours=6)
    assert abs(since - int(expected.timestamp())) < 120


def test_reconcile_records_run_state(app, monkeypatch):
    """Підсумок прогону лягає в налаштування -- для сторінки стану."""
    _configure()
    _use(monkeypatch, FakeMetaGraphClient(leads=[]))

    queue.reconcile()

    settings = SiteSettings.get()
    assert settings.meta_last_reconcile_status == 'ok'
    assert settings.meta_last_reconcile_at is not None
    assert settings.meta_last_reconcile_error == ''


def test_reconcile_survives_one_broken_form(app, monkeypatch):
    """Збій однієї форми не має ховати решту -- прогін лише «частковий»."""
    _configure()

    class _BrokenLeads:
        """Форми віддає, ліди -- ні. Фейк такого сценарію не програмує."""

        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def list_form_leads(self, *args, **kwargs):
            return MetaResult(ok=False, http_status=400,
                              error='Meta error code=4: rate limit', retryable=True)

    _use(monkeypatch, _BrokenLeads(FakeMetaGraphClient(leads=[])))

    stats = queue.reconcile()

    assert stats['checked_forms'] == 1
    assert stats['fetched'] == 0
    settings = SiteSettings.get()
    assert settings.meta_last_reconcile_status == 'partial'
    assert 'rate limit' in settings.meta_last_reconcile_error


def test_reconcile_reports_page_failure(app, monkeypatch):
    """Не змогли навіть перелічити форми -- це помилка прогону цілком."""
    _configure()
    client = _use(monkeypatch, FakeMetaGraphClient(leads=[]))
    client.fail_next(1, message='page unavailable')

    stats = queue.reconcile()

    assert stats['checked_forms'] == 0
    settings = SiteSettings.get()
    assert settings.meta_last_reconcile_status == 'error'
    assert 'page unavailable' in settings.meta_last_reconcile_error


def test_reconcile_is_due_respects_interval(app):
    """Період прогону читається з налаштувань, а не з cron-виразу."""
    settings = _configure(meta_reconcile_interval_minutes=30)
    assert queue.reconcile_is_due() is True

    settings.meta_last_reconcile_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.session.commit()
    assert queue.reconcile_is_due() is False

    settings.meta_last_reconcile_at = datetime.now(timezone.utc) - timedelta(minutes=31)
    db.session.commit()
    assert queue.reconcile_is_due() is True

    settings.meta_leads_enabled = False
    db.session.commit()
    assert queue.reconcile_is_due() is False


# --- токен ----------------------------------------------------------------

def test_check_token_zero_expiry_means_permanent(app, monkeypatch):
    """expires_at=0 -- це БЕЗСТРОКОВИЙ, а не «протух 1970 року»."""
    _configure()
    _use(monkeypatch, FakeMetaGraphClient(token_valid=True, token_expires_at=0))

    report = queue.check_token()

    assert report['valid'] is True
    assert report['permanent'] is True
    assert report['expires_at'] is None
    settings = SiteSettings.get()
    assert settings.meta_token_valid is True
    assert settings.meta_token_expires_at is None
    assert settings.meta_token_checked_at is not None


def test_check_token_stores_expiry(app, monkeypatch):
    """Термінові токени зберігають дату -- адмін має встигнути обміняти."""
    expires = int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp())
    _configure()
    _use(monkeypatch, FakeMetaGraphClient(token_valid=True, token_expires_at=expires))

    report = queue.check_token()

    assert report['permanent'] is False
    stored = SiteSettings.get().meta_token_expires_at
    assert stored is not None
    assert abs(queue._as_utc(stored).timestamp() - expires) < 2


def test_check_token_failure_marks_invalid(app, monkeypatch):
    """Відмова Meta -- це «недійсний» з текстом, а не мовчазний None."""
    _configure()
    client = _use(monkeypatch, FakeMetaGraphClient())
    client.fail_next(1, code=FakeMetaGraphClient.TOKEN_ERROR_CODE,
                     http_status=400, message='token revoked')

    report = queue.check_token()

    assert report['valid'] is False
    settings = SiteSettings.get()
    assert settings.meta_token_valid is False
    assert 'token revoked' in settings.meta_token_error


# --- моніторинг -----------------------------------------------------------

def _catch_alerts(monkeypatch):
    sent = []
    monkeypatch.setattr(
        EmailService, 'send_meta_leads_alert',
        staticmethod(lambda reasons, stats=None: sent.append(reasons)),
    )
    return sent


def test_silence_alert_is_sent_once_per_day(app, monkeypatch):
    """Тиша при активних формах -- сигнал; але не щогодини той самий."""
    _configure(
        meta_silence_alert_hours=24,
        meta_error_alert_threshold=0,
        meta_last_lead_at=datetime.now(timezone.utc) - timedelta(hours=48),
    )
    _use(monkeypatch, FakeMetaGraphClient())
    sent = _catch_alerts(monkeypatch)

    first = queue.run_health_alerts()
    assert first['sent'] is True
    assert [r['code'] for r in first['reasons']] == ['silence']
    assert len(sent) == 1

    second = queue.run_health_alerts()
    assert second['sent'] is False
    assert second['reason'] == 'throttled'
    assert len(sent) == 1


def test_no_silence_alert_without_active_forms(app, monkeypatch):
    """Заявок немає, бо й форм немає -- це не збій приймання."""
    _configure(
        meta_silence_alert_hours=24,
        meta_error_alert_threshold=0,
        meta_last_lead_at=datetime.now(timezone.utc) - timedelta(hours=48),
    )
    _use(monkeypatch, FakeMetaGraphClient(
        forms=[{'id': '9988776655', 'name': 'Стара', 'status': 'ARCHIVED'}]))
    sent = _catch_alerts(monkeypatch)

    report = queue.run_health_alerts()

    assert report['reasons'] == []
    assert report['sent'] is False
    assert sent == []


def test_failed_events_raise_alert(app, monkeypatch):
    """Накопичені помилки черги -- другий сигнал тієї самої події."""
    _configure(meta_silence_alert_hours=0, meta_error_alert_threshold=1)
    _use(monkeypatch, FakeMetaGraphClient())
    db.session.add(MetaLeadEvent(
        leadgen_id=_gid(), raw_payload={}, status=MetaLeadEvent.STATUS_FAILED,
        received_at=datetime.now(timezone.utc), attempts=MAX_EVENT_ATTEMPTS,
        last_error='Meta error code=190',
    ))
    db.session.commit()
    sent = _catch_alerts(monkeypatch)

    report = queue.run_health_alerts()

    assert 'errors' in [r['code'] for r in report['reasons']]
    assert report['failed_events'] >= 1
    assert len(sent) == 1


def test_invalid_token_raises_alert(app, monkeypatch):
    """Мертвий токен -- третій сигнал: без нього черга стоїть уся."""
    _configure(meta_silence_alert_hours=0, meta_error_alert_threshold=0,
               meta_token_valid=False, meta_token_error='token revoked')
    _use(monkeypatch, FakeMetaGraphClient())
    sent = _catch_alerts(monkeypatch)

    report = queue.run_health_alerts()

    assert [r['code'] for r in report['reasons']] == ['token']
    assert report['sent'] is True
    assert len(sent) == 1


def test_healthy_integration_stays_quiet(app, monkeypatch):
    """Коли все гаразд, менеджер не отримує нічого."""
    _configure(meta_silence_alert_hours=0, meta_error_alert_threshold=0,
               meta_token_valid=True)
    _use(monkeypatch, FakeMetaGraphClient())
    sent = _catch_alerts(monkeypatch)

    report = queue.run_health_alerts()

    assert report['reasons'] == []
    assert report['sent'] is False
    assert sent == []
    assert SiteSettings.get().meta_alert_sent_at is None


def test_alert_template_renders(app):
    """Шаблон листа мусить збиратись і на порожньому стані інтеграції."""
    with app.app_context():
        html = render_template(
            'emails/meta_leads_alert.html',
            site_settings=SiteSettings.get(),
            reasons=[{'code': 'silence', 'title': 'Заявок немає, а форми активні',
                      'detail': 'Остання заявка прийшла 48 год тому.'}],
            stats={'failed_events': 3, 'last_lead_at': None,
                   'last_webhook_at': None, 'last_reconcile_at': None},
            admin_url='https://example.com/admin/meta-leads/settings',
        )
    assert 'Заявок немає, а форми активні' in html
    assert 'meta-leads/settings' in html


# --- остаточна чистка -----------------------------------------------------

def test_purge_removes_lead_but_keeps_event(app):
    """Заявку прибираємо назавжди, сиру подію -- ніколи.

    Саме подія тримає ідемпотентність: без неї повторна доставка того
    самого leadgen_id воскресила б те, що адмін навмисно видалив.
    """
    from app.services.soft_delete_purge import purge_expired

    gid = _gid()
    lead = MetaLead(leadgen_id=gid, created_time=datetime.now(timezone.utc),
                    field_data={}, deleted_at=datetime.now(timezone.utc) - timedelta(days=90))
    db.session.add(lead)
    db.session.flush()
    event = MetaLeadEvent(leadgen_id=gid, raw_payload={}, lead_id=lead.id,
                          received_at=datetime.now(timezone.utc),
                          status=MetaLeadEvent.STATUS_DONE)
    db.session.add(event)
    db.session.commit()
    lead_id, event_id = lead.id, event.id

    stats = purge_expired(retention_days=30)

    assert stats['meta_leads'] >= 1
    assert db.session.get(MetaLead, lead_id) is None
    survivor = db.session.get(MetaLeadEvent, event_id)
    assert survivor is not None
    assert survivor.lead_id is None
