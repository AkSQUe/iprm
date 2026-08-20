"""Tests for MM Medic material reservation email notifications (IPRM side)."""
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from flask import render_template

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.trainer import Trainer
from app.models.email_log import EmailLog
from app.models.material_reservation import (
    MaterialReservation, MaterialReservationItem, MaterialReservationStatus,
)
from app.models.site_settings import SiteSettings


def _make_instance(trainer_email='trainer@example.com', ended=False, slug_suffix='n'):
    trainer = Trainer(full_name='Іван Тренер', slug=f'trainer-{slug_suffix}', email=trainer_email)
    db.session.add(trainer)
    course = Course(title='Плазмотерапія', slug=f'course-{slug_suffix}', trainer=trainer)
    db.session.add(course)
    db.session.flush()
    now = datetime.now(timezone.utc)
    inst = CourseInstance(
        course_id=course.id, trainer_id=trainer.id,
        start_date=now - timedelta(days=2) if ended else now + timedelta(days=2),
        end_date=now - timedelta(days=1) if ended else now + timedelta(days=3),
        location='Київ',
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _make_reservation(inst, status=MaterialReservationStatus.RESERVED, slug_suffix='n'):
    res = MaterialReservation(instance_id=inst.id, external_ref=f'iprm-instance-{inst.id}', status=status)
    db.session.add(res)
    db.session.flush()
    res.items.append(MaterialReservationItem(sku='NDL-21', name='Голка 21G', quantity_reserved=5))
    db.session.flush()
    return res


# ----------------------------- template rendering -----------------------------

def test_materials_reminder_template_renders(app):
    with app.app_context():
        item = MaterialReservationItem(sku='NDL-21', name='Голка 21G', quantity_reserved=5)
        html = render_template(
            'emails/materials_actuals_reminder.html',
            site_settings=SiteSettings.get(),
            event_title='Плазмотерапія', event_date='01.01.2026',
            items=[item], admin_url='https://plasma-regen.com/admin/instances/1/materials',
        )
        assert 'Внесіть фактичні' in html and 'instances/1/materials' in html


# ----------------------------- trigger + senders -----------------------------

def test_materials_trigger_allowed():
    assert EmailLog.is_valid_trigger('materials')


def test_actuals_reminder_is_idempotent(app, monkeypatch):
    from app.services import material_reservation_service as mrs
    from app.services.email_service import EmailService

    monkeypatch.setattr(mrs, 'get_client', lambda: object())  # avoid MMConfigError
    sent = []

    def _fake_reminder(r, i):
        sent.append(r.external_ref)
        return ['admin@example.com']  # non-empty -> recipients attempted

    monkeypatch.setattr(EmailService, 'send_materials_actuals_reminder',
                        staticmethod(_fake_reminder))

    inst = _make_instance(ended=True, slug_suffix='rem')
    res = _make_reservation(inst, slug_suffix='rem')

    n1 = mrs.send_pending_actuals_reminders()
    assert n1 == 1 and sent == [res.external_ref]
    assert res.actuals_reminder_sent_at is not None

    n2 = mrs.send_pending_actuals_reminders()
    assert n2 == 0  # flag set -> not re-sent


def test_actuals_reminder_not_marked_without_recipients(app, monkeypatch):
    from app.services import material_reservation_service as mrs
    from app.services.email_service import EmailService

    monkeypatch.setattr(mrs, 'get_client', lambda: object())
    monkeypatch.setattr(EmailService, 'send_materials_actuals_reminder',
                        staticmethod(lambda r, i: []))  # no recipients

    inst = _make_instance(ended=True, slug_suffix='norcpt')
    res = _make_reservation(inst, slug_suffix='norcpt')

    n = mrs.send_pending_actuals_reminders()
    assert n == 0
    assert res.actuals_reminder_sent_at is None  # left NULL -> retried later


# ----------------------------- reverse status webhook (MM Medic -> IPRM) -----------------------------

_MM_SECRET = 'reverse-webhook-secret'


def _enable_mm():
    site = SiteSettings.get()
    site.mm_medic_integration_enabled = True
    site.partner_webhook_secret = _MM_SECRET
    db.session.commit()


def _mm_headers(body, ts=None, bad=False):
    ts = ts or str(int(time.time()))
    sig = 'deadbeef' if bad else hmac.new(_MM_SECRET.encode(), ts.encode() + b'.' + body, hashlib.sha256).hexdigest()
    return {'X-IPRM-Signature': sig, 'X-IPRM-Timestamp': ts, 'Content-Type': 'application/json'}


def test_mm_status_webhook_marks_consumed_and_actuals(app, client):
    _enable_mm()
    inst = _make_instance(slug_suffix='mmw1')
    res = _make_reservation(inst, slug_suffix='mmw1')
    body = json.dumps({'external_ref': res.external_ref, 'status': 'consumed',
                       'items': [{'sku': 'NDL-21', 'quantity': 4}]}).encode()
    r = client.post('/api/partner/mm-medic/reservation-status', data=body, headers=_mm_headers(body))
    assert r.status_code == 200
    fresh = MaterialReservation.query.get(res.id)
    assert fresh.status == MaterialReservationStatus.CONSUMED
    assert fresh.items[0].quantity_actual == 4


def test_mm_status_webhook_marks_expired(app, client):
    _enable_mm()
    inst = _make_instance(slug_suffix='mmw2')
    res = _make_reservation(inst, slug_suffix='mmw2')
    body = json.dumps({'external_ref': res.external_ref, 'status': 'expired', 'items': []}).encode()
    r = client.post('/api/partner/mm-medic/reservation-status', data=body, headers=_mm_headers(body))
    assert r.status_code == 200
    assert MaterialReservation.query.get(res.id).status == MaterialReservationStatus.EXPIRED


def test_mm_status_webhook_rejects_bad_signature(app, client):
    _enable_mm()
    inst = _make_instance(slug_suffix='mmw3')
    res = _make_reservation(inst, slug_suffix='mmw3')
    body = json.dumps({'external_ref': res.external_ref, 'status': 'cancelled'}).encode()
    r = client.post('/api/partner/mm-medic/reservation-status', data=body, headers=_mm_headers(body, bad=True))
    assert r.status_code == 401
    assert MaterialReservation.query.get(res.id).status == MaterialReservationStatus.RESERVED


def test_mm_status_webhook_revert_to_reserved_clears_actuals(app, client):
    """MM Medic скасував помилкове списання -- дзеркало не має лишати фактику.

    Документ у резерві за визначенням нічого не спожив. Доки старі
    `quantity_actual` і `consumed_at` лишались, пікінг-лист і звіт
    «зарезервовано проти спожитого» показували витрату по документу, який її
    не робив, а все, що дивиться на `consumed_at` замість статусу, і далі
    вважало захід списаним.
    """
    _enable_mm()
    inst = _make_instance(slug_suffix='rvrt')
    res = _make_reservation(inst, status=MaterialReservationStatus.CONSUMED,
                            slug_suffix='rvrt')
    res.items[0].quantity_actual = 4
    res.consumed_at = datetime.now(timezone.utc)
    db.session.commit()

    body = json.dumps({'external_ref': res.external_ref, 'status': 'active',
                       'items': [{'sku': 'NDL-21', 'quantity': 5}]}).encode()
    r = client.post('/api/partner/mm-medic/reservation-status', data=body,
                    headers=_mm_headers(body))

    assert r.status_code == 200
    fresh = MaterialReservation.query.get(res.id)
    assert fresh.status == MaterialReservationStatus.RESERVED
    assert fresh.consumed_at is None
    assert fresh.items[0].quantity_actual is None
    assert fresh.items[0].quantity_reserved == 5


def test_mm_status_webhook_revert_to_cancelled_keeps_history(app, client):
    """Скасований документ -- інша гілка: статус міняється, а цифри лишаються
    як історія того, що колись провели."""
    _enable_mm()
    inst = _make_instance(slug_suffix='rvcn')
    res = _make_reservation(inst, status=MaterialReservationStatus.CONSUMED,
                            slug_suffix='rvcn')
    res.items[0].quantity_actual = 4
    db.session.commit()

    body = json.dumps({'external_ref': res.external_ref, 'status': 'cancelled',
                       'items': []}).encode()
    r = client.post('/api/partner/mm-medic/reservation-status', data=body,
                    headers=_mm_headers(body))

    assert r.status_code == 200
    fresh = MaterialReservation.query.get(res.id)
    assert fresh.status == MaterialReservationStatus.CANCELLED
    assert fresh.items[0].quantity_actual == 4


def test_mm_status_webhook_unknown_ref_acked(app, client):
    _enable_mm()
    body = json.dumps({'external_ref': 'iprm-instance-999999', 'status': 'consumed'}).encode()
    r = client.post('/api/partner/mm-medic/reservation-status', data=body, headers=_mm_headers(body))
    assert r.status_code == 200


# --------------- requests born on MM Medic (trainer submits there) ---------------

def _post_status(client, payload):
    body = json.dumps(payload).encode()
    return client.post('/api/partner/mm-medic/reservation-status',
                       data=body, headers=_mm_headers(body))


def test_instance_id_from_ref_roundtrip(app):
    from app.services import material_reservation_service as mrs
    assert mrs.instance_id_from_ref(mrs.external_ref_for(42)) == 42
    assert mrs.instance_id_from_ref('iprm-instance-abc') is None
    assert mrs.instance_id_from_ref('some-other-ref-7') is None
    assert mrs.instance_id_from_ref('') is None


def test_mm_status_webhook_creates_row_for_trainer_request(app, client):
    """A trainer submitted the request in MM Medic -- IPRM has never seen the ref.

    Without creation here the захід would show no materials at all, because the
    reconcile job only revisits refs it already knows.
    """
    _enable_mm()
    inst = _make_instance(slug_suffix='born')
    ref = f'iprm-instance-{inst.id}'
    assert MaterialReservation.query.filter_by(external_ref=ref).first() is None

    r = _post_status(client, {
        'external_ref': ref,
        'status': 'submitted',
        'origin': 'trainer',
        'document_number': 'ЗМ-000123',
        'items': [{'sku': 'NDL-21', 'name': 'Голка 21G', 'quantity_requested': 7}],
    })

    assert r.status_code == 200
    assert r.get_json()['status'] == 'created'
    res = MaterialReservation.query.filter_by(external_ref=ref).first()
    assert res is not None
    assert res.instance_id == inst.id
    assert res.status == MaterialReservationStatus.SUBMITTED
    assert res.origin == 'trainer'
    assert res.document_number == 'ЗМ-000123'
    assert res.items[0].sku == 'NDL-21'
    assert res.items[0].quantity_requested == 7


def test_mm_status_webhook_approved_maps_to_reserved(app, client):
    """`approved` must land on RESERVED: six `== RESERVED` gates in
    admin/routes_materials.py depend on that value meaning "hold is active"."""
    _enable_mm()
    inst = _make_instance(slug_suffix='appr')
    res = _make_reservation(inst, status=MaterialReservationStatus.SUBMITTED,
                            slug_suffix='appr')

    r = _post_status(client, {
        'external_ref': res.external_ref,
        'status': 'approved',
        'items': [{'sku': 'NDL-21', 'quantity_requested': 5, 'quantity_approved': 4}],
    })

    assert r.status_code == 200
    fresh = MaterialReservation.query.get(res.id)
    assert fresh.status == MaterialReservationStatus.RESERVED
    assert fresh.items[0].quantity_reserved == 4
    assert fresh.items[0].quantity_requested == 5


def test_mm_status_webhook_derives_consumed_from_issued_minus_returned(app, client):
    _enable_mm()
    inst = _make_instance(slug_suffix='ret')
    res = _make_reservation(inst, slug_suffix='ret')

    r = _post_status(client, {
        'external_ref': res.external_ref,
        'status': 'completed',
        'items': [{'sku': 'NDL-21', 'quantity_approved': 10,
                   'quantity_issued': 10, 'quantity_returned': 3}],
    })

    assert r.status_code == 200
    item = MaterialReservation.query.get(res.id).items[0]
    assert item.quantity_issued == 10
    assert item.quantity_returned == 3
    assert item.quantity_actual == 7  # спожито = видано - повернуто


def test_mm_status_webhook_ignores_out_of_order_push(app, client):
    """MM Medic posts status off-thread, so pushes can overtake each other.
    An older snapshot must not undo a newer one."""
    _enable_mm()
    inst = _make_instance(slug_suffix='ooo')
    ref = f'iprm-instance-{inst.id}'

    _post_status(client, {'external_ref': ref, 'status': 'submitted',
                          'updated_at': '2026-08-13T10:00:00+00:00', 'items': []})
    _post_status(client, {'external_ref': ref, 'status': 'issued',
                          'updated_at': '2026-08-13T12:00:00+00:00', 'items': []})

    late = _post_status(client, {'external_ref': ref, 'status': 'submitted',
                                 'updated_at': '2026-08-13T11:00:00+00:00', 'items': []})

    assert late.status_code == 200
    assert late.get_json()['status'] == 'stale_push'
    assert (MaterialReservation.query.filter_by(external_ref=ref).first().status
            == MaterialReservationStatus.ISSUED)


def test_mm_status_webhook_does_not_create_row_for_cancelled(app, client):
    """Nothing to file: no history to keep and no action left."""
    _enable_mm()
    inst = _make_instance(slug_suffix='canc')
    ref = f'iprm-instance-{inst.id}'

    r = _post_status(client, {'external_ref': ref, 'status': 'cancelled', 'items': []})

    assert r.status_code == 200
    assert r.get_json()['status'] == 'unknown_ref'
    assert MaterialReservation.query.filter_by(external_ref=ref).first() is None


def test_mm_status_webhook_legacy_payload_still_works(app, client):
    """An older MM Medic build sends only `quantity` -- keep honouring it until
    the new payload ships, otherwise the live integration breaks on deploy."""
    _enable_mm()
    inst = _make_instance(slug_suffix='lgcy')
    res = _make_reservation(inst, slug_suffix='lgcy')

    r = _post_status(client, {'external_ref': res.external_ref, 'status': 'consumed',
                              'items': [{'sku': 'NDL-21', 'quantity': 4}]})

    assert r.status_code == 200
    fresh = MaterialReservation.query.get(res.id)
    assert fresh.status == MaterialReservationStatus.CONSUMED
    assert fresh.items[0].quantity_actual == 4


def test_consumed_push_does_not_overwrite_reserved(app, client):
    """У термінальному штовху `quantity` означає СПОЖИТЕ, а не погоджене.

    MM Medic перезаписує кількість рядка фактично використаною
    (`submit_actuals`), тож прийняти її як погоджену -- це стерти в дзеркалі
    цифру, на якій тримаються пікінг-лист (`materials_picking.html`) і звіт
    «зарезервовано проти спожитого» (`xlsx_io`). Аналітика «скільки не
    використали» при цьому схлопується в нуль, і помітити це нічим.
    """
    _enable_mm()
    inst = _make_instance(slug_suffix='keepres')
    res = _make_reservation(inst, slug_suffix='keepres')  # quantity_reserved=5

    _post_status(client, {'external_ref': res.external_ref, 'status': 'consumed',
                          'items': [{'sku': 'NDL-21', 'quantity': 4}]})

    item = MaterialReservation.query.get(res.id).items[0]
    assert item.quantity_actual == 4
    assert item.quantity_reserved == 5, 'погоджену кількість затерто спожитою'


def test_line_absent_from_consumed_push_is_zeroed(app, client):
    """Рядок зникає з термінального payload рівно тоді, коли повернули все.

    MM Medic звільняє утримання з нульовим фактом, і лінія випадає з `items`
    (`_serialize` лишає тільки active/consumed). Лишити її «зарезервованою»
    назавжди -- показувати комірнику матеріал, який давно на складі.

    Ключове: `items` тут ПРИСУТНІЙ і порожній -- це твердження «рядків немає».
    Відсутність ключа означала б «про рядки нічого не сказано», див. наступний
    тест.
    """
    _enable_mm()
    inst = _make_instance(slug_suffix='zeroed')
    res = _make_reservation(inst, slug_suffix='zeroed')  # NDL-21, reserved=5

    _post_status(client, {'external_ref': res.external_ref, 'status': 'consumed',
                          'items': []})

    item = MaterialReservation.query.get(res.id).items[0]
    assert item.quantity_actual == 0
    assert item.quantity_returned == 5
    assert item.quantity_reserved == 5  # погоджене лишається як факт історії


def test_status_only_terminal_push_does_not_wipe_actuals(app, client):
    """Штовх БЕЗ ключа `items` не має права стирати фактику документа.

    Доти `payload.get('items') or []` зводило «ключа немає», `null` і `[]` в
    одне значення, і легкий status-only штовх обнуляв ВСІ рядки. Приймач
    фізично не може відрізнити «партнер звільнив усі утримання» від «партнер не
    поклав рядки в цей штовх» -- тому відсутність ключа означає «нічого не
    сказано», а не «все повернули».
    """
    _enable_mm()
    inst = _make_instance(slug_suffix='statusonly')
    res = _make_reservation(inst, slug_suffix='statusonly')
    res.items[0].quantity_actual = 4
    db.session.flush()

    r = _post_status(client, {'external_ref': res.external_ref,
                              'status': 'completed'})

    assert r.status_code == 200
    item = MaterialReservation.query.get(res.id).items[0]
    assert item.quantity_actual == 4, 'фактику стерто status-only штовхом'
    assert item.quantity_reserved == 5


def test_unknown_status_applies_nothing_at_all(app, client):
    """Невідомий статус не має змінювати НІЧОГО.

    Раніше застосовувалось усе, крім самого статусу: legacy `quantity` лягало в
    `quantity_reserved`, писався номер документа, просувалась мітка часу -- і та
    просунута мітка потім відсікала наступний легітимний штовх як застарілий.
    """
    _enable_mm()
    inst = _make_instance(slug_suffix='unknown')
    res = _make_reservation(inst, slug_suffix='unknown')  # reserved=5

    r = _post_status(client, {
        'external_ref': res.external_ref, 'status': 'teleported',
        'document_number': 'ЗМ-999', 'updated_at': '2026-08-14T10:00:00+00:00',
        'items': [{'sku': 'NDL-21', 'quantity': 77}],
    })

    assert r.status_code == 200
    assert r.get_json()['status'] == 'unknown_status'
    fresh = MaterialReservation.query.get(res.id)
    assert fresh.items[0].quantity_reserved == 5
    assert fresh.document_number is None
    assert fresh.remote_updated_at is None
    assert fresh.status == MaterialReservationStatus.RESERVED


def test_mm_status_webhook_rejects_overlong_identifiers(app, client):
    """Ідентифікатор обрізати не можна -- обрізаний вказує на ІНШИЙ рядок.

    SQLite мовчки пише будь-яку довжину, PostgreSQL кидає
    StringDataRightTruncation -- тобто без перевірки тест зелений, а прод
    віддає 500 і губить штовх (ретраїв у відправника немає).
    """
    _enable_mm()
    inst = _make_instance(slug_suffix='long')
    res = _make_reservation(inst, slug_suffix='long')

    r = _post_status(client, {'external_ref': 'iprm-instance-' + '9' * 80,
                              'status': 'active', 'items': []})
    assert r.status_code == 400
    assert r.get_json()['status'] == 'ref_too_long'

    r = _post_status(client, {'external_ref': res.external_ref, 'status': 'active',
                              'items': [{'sku': 'X' * 120, 'quantity': 1}]})
    assert r.status_code == 400
    assert r.get_json()['status'] == 'sku_too_long'


def test_mm_status_webhook_trims_descriptive_fields(app, client):
    """Описові поля навпаки обрізаються мовчки: зіпсована назва гірша за
    відсутню, але звʼязків не ламає."""
    _enable_mm()
    inst = _make_instance(slug_suffix='trim')
    res = _make_reservation(inst, slug_suffix='trim')

    r = _post_status(client, {
        'external_ref': res.external_ref, 'status': 'active',
        'document_number': 'D' * 90,
        'items': [{'sku': 'NDL-21', 'quantity': 3, 'name': 'Н' * 400}],
    })

    assert r.status_code == 200
    fresh = MaterialReservation.query.get(res.id)
    assert len(fresh.document_number) == 50
    assert len(fresh.items[0].name) == 255


def test_mm_status_webhook_falls_back_on_unknown_origin(app, client):
    _enable_mm()
    inst = _make_instance(slug_suffix='orig')
    ref = f'iprm-instance-{inst.id}'

    _post_status(client, {'external_ref': ref, 'status': 'submitted',
                          'origin': 'whatever-' + 'x' * 60, 'items': []})

    res = MaterialReservation.query.filter_by(external_ref=ref).first()
    assert res.origin == 'trainer'


def test_repeated_push_is_idempotent(app, client):
    """Повтор того самого штовха не плодить документів.

    Це перевірка ЗВИЧАЙНОГО повтору (той самий ref приходить двічі
    послідовно) -- саме він трапляється в житті. Справжня одночасна гонка
    двох потоків однопотоковим тестом не відтворюється: другий запит бачить
    уже закомічений рядок першого й до гілки створення не доходить. Захист
    від неї (`except IntegrityError` з перечитуванням) лишається як
    оборонний код і покритий лише читанням.
    """
    _enable_mm()
    inst = _make_instance(slug_suffix='race')
    ref = f'iprm-instance-{inst.id}'

    first = _post_status(client, {'external_ref': ref, 'status': 'submitted',
                                  'items': [{'sku': 'NDL-21', 'quantity': 2}]})
    second = _post_status(client, {'external_ref': ref, 'status': 'submitted',
                                   'items': [{'sku': 'NDL-21', 'quantity': 2}]})

    assert first.status_code == 200 and second.status_code == 200
    assert MaterialReservation.query.filter_by(external_ref=ref).count() == 1


def test_stale_push_ignored_after_a_no_op_push(app, client):
    """Мітка часу просувається навіть коли штовх нічого не змінив.

    Доки це стояло всередині `if changed`, наступний, справді старіший штовх
    проходив як «свіжий».
    """
    _enable_mm()
    inst = _make_instance(slug_suffix='noop')
    ref = f'iprm-instance-{inst.id}'

    _post_status(client, {'external_ref': ref, 'status': 'issued',
                          'updated_at': '2026-08-13T10:00:00+00:00', 'items': []})
    # Той самий стан -- нічого не змінює, але знімок свіжіший.
    _post_status(client, {'external_ref': ref, 'status': 'issued',
                          'updated_at': '2026-08-13T12:00:00+00:00', 'items': []})

    late = _post_status(client, {'external_ref': ref, 'status': 'submitted',
                                 'updated_at': '2026-08-13T11:00:00+00:00',
                                 'items': []})

    assert late.get_json()['status'] == 'stale_push'
    assert (MaterialReservation.query.filter_by(external_ref=ref).first().status
            == MaterialReservationStatus.ISSUED)


@pytest.mark.parametrize('raw', [
    '1_0',        # int() приймає підкреслення
    ' 10',        # int() приймає пробіли
    '+10',        # int() приймає знак
    '-5',
    '05',         # isdigit() пропускає провідні нулі -> той самий захід,
                  # інший external_ref -> ДВА документи на один захід
    '٥',     # isdigit() пропускає арабсько-індійські цифри
    '²',     # isdigit() істинне, а int() кидає ValueError -> 500
    '9' * 30,     # понад BIGINT -> NumericValueOutOfRange на SELECT
    '',
    'abc',
])
def test_ref_parser_rejects_lookalikes(app, raw):
    """Приймається РІВНО те, що виробляє `external_ref_for`.

    Тут по черзі побували `int()` і `isdigit()`, і кожен пропускав свій набір
    форм, які вказують на той самий захід під іншим `external_ref` --
    унікальність стоїть саме на ref, тож наслідок один: два документи на один
    захід і недетермінований вибір між ними.
    """
    from app.services import material_reservation_service as mrs

    assert mrs.instance_id_from_ref(f'iprm-instance-{raw}') is None


def test_ref_parser_accepts_what_the_generator_makes(app):
    from app.services import material_reservation_service as mrs

    for instance_id in (1, 7, 42, 1234567):
        ref = mrs.external_ref_for(instance_id)
        assert mrs.instance_id_from_ref(ref) == instance_id


@pytest.mark.parametrize('sku, expected', [
    (['A'], 'sku_not_a_string'),   # unhashable -> був неспійманий 500
    (12345, 'sku_not_a_string'),   # проходило до PostgreSQL і падало на commit
    ({'a': 1}, 'sku_not_a_string'),
    ('X' * 120, 'sku_too_long'),
])
def test_mm_status_webhook_rejects_bad_sku_type(app, client, sku, expected):
    _enable_mm()
    inst = _make_instance(slug_suffix=f'sku{abs(hash(str(sku))) % 997}')
    res = _make_reservation(inst, slug_suffix=f'sku{abs(hash(str(sku))) % 997}')

    r = _post_status(client, {'external_ref': res.external_ref,
                              'status': 'active',
                              'items': [{'sku': sku, 'quantity': 1}]})

    assert r.status_code == 400
    assert r.get_json()['status'] == expected


def test_issued_document_is_not_expired_by_reconcile(app, monkeypatch):
    """Порожній «живий» заголовок -- НОРМА для відвантаженого документа.

    Матеріали видали, утримання зняли, а legacy-заголовок MM Medic лишається
    `active`. Евристика «живий і порожній = протухло» справедлива лише для
    RESERVED; застосована до ISSUED, вона перемарковувала коректно
    відвантажений документ у EXPIRED -- необоротно, бо EXPIRED звірка більше не
    переглядає.
    """
    from app.services import material_reservation_service as mrs

    inst = _make_instance(slug_suffix='issuedkeep')
    res = _make_reservation(inst, status=MaterialReservationStatus.ISSUED,
                            slug_suffix='issuedkeep')

    class _Result:
        ok = True
        data = {'reservation': {'status': 'active', 'items': []}}

    monkeypatch.setattr(mrs, 'get_client',
                        lambda: type('C', (), {
                            'get_reservation': lambda self, ref: _Result()})())

    assert mrs.reconcile_reservation(res) is False
    assert res.status == MaterialReservationStatus.ISSUED


def test_reserved_document_still_expires(app, monkeypatch):
    """Зворотний бік: для RESERVED евристика мусить лишитись робочою."""
    from app.services import material_reservation_service as mrs

    inst = _make_instance(slug_suffix='expok')
    res = _make_reservation(inst, slug_suffix='expok')

    class _Result:
        ok = True
        data = {'reservation': {'status': 'active', 'items': []}}

    monkeypatch.setattr(mrs, 'get_client',
                        lambda: type('C', (), {
                            'get_reservation': lambda self, ref: _Result()})())

    assert mrs.reconcile_reservation(res) is True
    assert res.status == MaterialReservationStatus.EXPIRED


def test_reconcile_never_moves_status_backwards(app, monkeypatch):
    """Звірка бачить лише поточний знімок і не знає, як далеко ми пройшли.

    Партнер для відвантаженого документа й далі віддає legacy-заголовок
    `active`, який мапиться в RESERVED. Застосувати його означало б «повернути»
    документ у зарезервований стан -- знову редагований і придатний до
    повторної видачі. Штовх такого зробити не міг: він приходить на кожен крок
    уперед.
    """
    from app.services import material_reservation_service as mrs

    inst = _make_instance(slug_suffix='noback')
    res = _make_reservation(inst, status=MaterialReservationStatus.CONSUMED,
                            slug_suffix='noback')
    res.status = MaterialReservationStatus.ISSUED  # у _RECONCILABLE

    class _Result:
        ok = True
        data = {'reservation': {'status': 'active',
                                'items': [{'sku': 'NDL-21', 'quantity': 5}]}}

    monkeypatch.setattr(mrs, 'get_client',
                        lambda: type('C', (), {
                            'get_reservation': lambda self, ref: _Result()})())

    assert mrs.reconcile_reservation(res) is False
    assert res.status == MaterialReservationStatus.ISSUED


def test_reconcile_still_accepts_terminal_branches(app, monkeypatch):
    """Скасування й відмова -- легітимні завершення на будь-якому кроці."""
    from app.services import material_reservation_service as mrs

    inst = _make_instance(slug_suffix='cancelok')
    res = _make_reservation(inst, status=MaterialReservationStatus.ISSUED,
                            slug_suffix='cancelok')

    class _Result:
        ok = True
        data = {'reservation': {'status': 'cancelled', 'items': []}}

    monkeypatch.setattr(mrs, 'get_client',
                        lambda: type('C', (), {
                            'get_reservation': lambda self, ref: _Result()})())

    assert mrs.reconcile_reservation(res) is True
    assert res.status == MaterialReservationStatus.CANCELLED


def test_status_map_has_one_source(app):
    """Приймач і звірка мусять читати ОДИН обʼєкт, а не дві копії."""
    from app.api import mm_status
    from app.services import material_reservation_service as mrs

    assert mm_status._STATUS_MAP is mrs.REMOTE_TO_LOCAL


def test_reconcile_covers_stuck_submitted_rows(app, monkeypatch):
    """Штовх статусу без ретраїв можна проґавити на будь-якому кроці, тож
    звірка мусить бачити не лише RESERVED."""
    from app.services import material_reservation_service as mrs

    inst = _make_instance(slug_suffix='stuck')
    res = _make_reservation(inst, status=MaterialReservationStatus.SUBMITTED,
                            slug_suffix='stuck')

    class _Result:
        ok = True
        data = {'reservation': {'status': 'consumed', 'items': []}}

    class _Client:
        def get_reservation(self, ref):
            return _Result()

    monkeypatch.setattr(mrs, 'get_client', lambda: _Client())

    assert mrs.reconcile_reservation(res) is True
    assert res.status == MaterialReservationStatus.CONSUMED


def test_non_terminal_push_still_sets_reserved(app, client):
    """Поки резерв живий, legacy `quantity` -- це саме погоджене."""
    _enable_mm()
    inst = _make_instance(slug_suffix='alive')
    res = _make_reservation(inst, status=MaterialReservationStatus.SUBMITTED,
                            slug_suffix='alive')

    _post_status(client, {'external_ref': res.external_ref, 'status': 'active',
                          'items': [{'sku': 'NDL-21', 'quantity': 9}]})

    item = MaterialReservation.query.get(res.id).items[0]
    assert item.quantity_reserved == 9
    assert item.quantity_actual is None


# ----------------------------- trainer public view + overview export -----------------------------

def test_trainer_materials_public_view(app, client):
    from app.services import material_reservation_service as mrs
    inst = _make_instance(slug_suffix='trn')
    res = _make_reservation(inst, slug_suffix='trn')
    with app.app_context():
        token = mrs.make_trainer_token(inst.id)
    r = client.get(f'/materials/{token}')
    assert r.status_code == 200
    assert b'NDL-21' in r.data
    # tampered token -> 404
    assert client.get('/materials/not-a-real-token').status_code == 404


def test_overview_export_xlsx_bytes(app):
    from app.services import xlsx_io
    with app.app_context():
        inst = _make_instance(slug_suffix='exp')
        res = _make_reservation(inst, slug_suffix='exp')
        bio = xlsx_io.export_material_reservations_xlsx([res])
        data = bio.getvalue()
        assert data[:2] == b'PK'  # xlsx is a zip


def test_mm_status_webhook_stores_cost(app, client):
    """Гроші за видане приїжджають разом зі станом документа."""
    from decimal import Decimal
    _enable_mm()
    inst = _make_instance(slug_suffix='cost1')
    res = _make_reservation(inst, slug_suffix='cost1')

    r = _post_status(client, {
        'external_ref': res.external_ref,
        'status': 'completed',
        'items': [{'sku': 'NDL-21', 'quantity_issued': 10, 'quantity_returned': 3,
                   'cost_uah': '148.75', 'cost_complete': True}],
    })

    assert r.status_code == 200
    item = MaterialReservation.query.get(res.id).items[0]
    assert item.cost_uah == Decimal('148.75')
    assert item.cost_complete is True


def test_mm_status_webhook_null_cost_stays_null(app, client):
    """`cost_uah: null` -- це «оцінити нічим», і `cost_complete` тоді теж NULL.

    Записати сюди `false` означало б стверджувати «собівартість неповна» там,
    де її ще не рахували: до відвантаження партій у рядка немає взагалі.
    """
    from decimal import Decimal
    _enable_mm()
    inst = _make_instance(slug_suffix='cost2')
    res = _make_reservation(inst, slug_suffix='cost2')
    # Рядок ЗАСІЯНО навмисно. Свіжий рядок і так має None в обох колонках,
    # тож без цього тест проходив би навіть після повного відкату
    # функціональності -- тобто не перевіряв би нічого. Перевіряємо саме
    # повернення в None, а не його наявність.
    res.items[0].cost_uah = Decimal('50.00')
    res.items[0].cost_complete = True
    db.session.commit()

    r = _post_status(client, {
        'external_ref': res.external_ref,
        'status': 'approved',
        'items': [{'sku': 'NDL-21', 'quantity_approved': 10,
                   'cost_uah': None, 'cost_complete': False}],
    })

    assert r.status_code == 200
    item = MaterialReservation.query.get(res.id).items[0]
    assert item.cost_uah is None
    assert item.cost_complete is None


def test_mm_status_webhook_zero_cost_is_kept(app, client):
    """Нуль -- це порахована вартість, а не її відсутність."""
    from decimal import Decimal
    _enable_mm()
    inst = _make_instance(slug_suffix='cost3')
    res = _make_reservation(inst, slug_suffix='cost3')

    _post_status(client, {
        'external_ref': res.external_ref,
        'status': 'completed',
        'items': [{'sku': 'NDL-21', 'quantity_issued': 4, 'quantity_returned': 4,
                   'cost_uah': '0.00', 'cost_complete': True}],
    })

    item = MaterialReservation.query.get(res.id).items[0]
    assert item.cost_uah == Decimal('0.00')
    assert item.cost_complete is True


def test_mm_status_webhook_incomplete_cost_is_stored_as_false(app, client):
    """Справжня сума з ознакою «порахована не вся» лягає саме як `False`.

    `cost_complete=False` -- це те, чим звіт маржинальності позначає колонку
    як приблизну: частина партій рядка не мала ціни, тож сума занижена.
    Регресія, що зашила б сюди `True`, пройшла б усі тести в обох
    репозиторіях, і звіт читався б як точний.

    Наявні тести перевіряли `False` лише в парі з порожньою вартістю -- а там
    він і так примусово стає `None`, тобто гілку зі справжньою сумою не
    перевіряв ніхто.
    """
    from decimal import Decimal
    _enable_mm()
    inst = _make_instance(slug_suffix='cost5')
    res = _make_reservation(inst, slug_suffix='cost5')

    r = _post_status(client, {
        'external_ref': res.external_ref,
        'status': 'completed',
        'items': [{'sku': 'NDL-21', 'quantity_issued': 10, 'quantity_returned': 0,
                   'cost_uah': '80.00', 'cost_complete': False}],
    })

    assert r.status_code == 200
    item = MaterialReservation.query.get(res.id).items[0]
    assert item.cost_uah == Decimal('80.00')
    # Саме `False`, не `None` і не «щось хибне»: `None` означає «не рахували»,
    # а тут рахували -- просто не все.
    assert item.cost_complete is False


def test_mm_status_webhook_old_payload_keeps_existing_cost(app, client):
    """Старий MM Medic полів вартості не шле. Це не привід стирати вже відоме.

    Той самий принцип, за яким тут уже влаштовані кількості: відсутнє поле
    означає «не повідомили», а не «стало порожнім».
    """
    from decimal import Decimal
    _enable_mm()
    inst = _make_instance(slug_suffix='cost4')
    res = _make_reservation(inst, slug_suffix='cost4')
    res.items[0].cost_uah = Decimal('50.00')
    res.items[0].cost_complete = True
    db.session.commit()

    _post_status(client, {
        'external_ref': res.external_ref,
        'status': 'completed',
        'items': [{'sku': 'NDL-21', 'quantity_issued': 5, 'quantity_returned': 0}],
    })

    item = MaterialReservation.query.get(res.id).items[0]
    assert item.cost_uah == Decimal('50.00')
    assert item.cost_complete is True
