"""Тести Фази 2 реферальної програми: захоплення атрибуції та резолв."""
from app.extensions import db
from app.models.user import User
from app.models.trainer import Trainer
from app.models.site_settings import SiteSettings
from app.services import referral_service as rs


def _mk_user(email):
    u = User(email=email, first_name='Тест', last_name='Юзер')
    db.session.add(u)
    db.session.flush()
    return u


def test_is_valid_code():
    assert rs.is_valid_code('u1234abcd')
    assert rs.is_valid_code('tabcdef01')
    assert not rs.is_valid_code('x1234abcd')  # невідомий префікс
    assert not rs.is_valid_code('u123')       # закоротко
    assert not rs.is_valid_code('u1234ABCD')  # верхній регістр не hex
    assert not rs.is_valid_code(None)
    assert not rs.is_valid_code('')


def test_resolve_referrer_user_and_trainer(db_session):
    u = _mk_user('resolve-u@example.com')
    ucode = rs.ensure_referral_code(u, prefix='u')
    t = Trainer(full_name='Оксана Тренер', slug='oksana-ref')
    db.session.add(t)
    db.session.flush()
    tcode = rs.ensure_referral_code(t, prefix='t')

    ru = rs.resolve_referrer(ucode)
    assert ru['kind'] == 'user' and ru['id'] == u.id
    rt = rs.resolve_referrer(tcode)
    assert rt['kind'] == 'trainer' and rt['id'] == t.id
    # Неіснуючий код валідної форми -> None
    assert rs.resolve_referrer('u00000000') is None


def test_resolve_bulk(db_session):
    u = _mk_user('bulk-u@example.com')
    ucode = rs.ensure_referral_code(u, prefix='u')
    t = Trainer(full_name='Петро Тренер', slug='petro-ref')
    db.session.add(t)
    db.session.flush()
    tcode = rs.ensure_referral_code(t, prefix='t')

    m = rs.resolve_referrers_bulk([ucode, tcode, 'u00000000', None, 'bad'])
    assert set(m.keys()) == {ucode, tcode}
    assert m[ucode]['kind'] == 'user'
    assert m[tcode]['kind'] == 'trainer'


def test_capture_ref_cookie_sets_when_enabled(app, db_session):
    settings = SiteSettings.get()
    settings.referral_enabled = True
    db.session.flush()

    with app.test_request_context('/courses/prp?ref=u1234abcd'):
        from flask import request, Response
        resp = Response('ok')
        from app.services import referral_service
        out = referral_service.capture_ref_cookie(request, resp)
        cookies = out.headers.getlist('Set-Cookie')
        assert any(referral_service.REF_COOKIE + '=u1234abcd' in c for c in cookies)


def test_capture_ref_cookie_skips_when_disabled(app, db_session):
    settings = SiteSettings.get()
    settings.referral_enabled = False
    db.session.flush()

    with app.test_request_context('/?ref=u1234abcd'):
        from flask import request, Response
        resp = Response('ok')
        from app.services import referral_service
        out = referral_service.capture_ref_cookie(request, resp)
        assert not out.headers.getlist('Set-Cookie')


def test_capture_ref_cookie_ignores_invalid_code(app, db_session):
    settings = SiteSettings.get()
    settings.referral_enabled = True
    db.session.flush()

    with app.test_request_context('/?ref=not-a-code'):
        from flask import request, Response
        resp = Response('ok')
        from app.services import referral_service
        out = referral_service.capture_ref_cookie(request, resp)
        assert not out.headers.getlist('Set-Cookie')


def test_persist_and_read_pending_for_user(app, db_session):
    settings = SiteSettings.get()
    settings.referral_enabled = True
    settings.referral_attribution = 'last'
    db.session.flush()
    u = _mk_user('pending@example.com')

    with app.test_request_context('/courses/x?ref=u1234abcd'):
        from flask import request
        rs.persist_pending_for_user(request, u)
    assert u.pending_referral_code == 'u1234abcd'

    # read_pending_ref віддає перевагу серверному коду над cookie.
    with app.test_request_context('/', headers={'Cookie': f'{rs.REF_COOKIE}=t99887766'}):
        from flask import request
        assert rs.read_pending_ref(request, u) == 'u1234abcd'


def test_persist_pending_first_touch_not_overwritten(app, db_session):
    settings = SiteSettings.get()
    settings.referral_enabled = True
    settings.referral_attribution = 'first'
    db.session.flush()
    u = _mk_user('firsttouch@example.com')
    u.pending_referral_code = 'u1234abcd'
    db.session.flush()

    with app.test_request_context('/?ref=t99887766'):
        from flask import request
        rs.persist_pending_for_user(request, u)
    assert u.pending_referral_code == 'u1234abcd'  # first-touch збережено


def test_record_click_aggregates(app, db_session):
    with app.app_context():
        rs.record_click('u1234abcd')
        rs.record_click('u1234abcd')
        rs.record_click('t99887766')
        m = rs.get_clicks_by_code(['u1234abcd', 't99887766', 'bad'])
        assert m['u1234abcd'] == 2
        assert m['t99887766'] == 1
    # Невалідний код ігнорується без запису.
    rs.record_click('not-a-code')
    assert rs.get_clicks_by_code(['not-a-code']) == {}


def _html_response():
    from flask import Response
    return Response('<html></html>', content_type='text/html; charset=utf-8')


def test_visit_records_click_for_human(app, db_session):
    s = SiteSettings.get()
    s.referral_enabled = True
    db.session.flush()
    with app.test_request_context('/c?ref=uaaaa0001',
                                  headers={'User-Agent': 'Mozilla/5.0'}):
        from flask import request
        rs.capture_referral_visit(request, _html_response(), None)
    assert rs.get_clicks_by_code(['uaaaa0001']) == {'uaaaa0001': 1}


def test_visit_skips_click_for_bot(app, db_session):
    s = SiteSettings.get()
    s.referral_enabled = True
    db.session.flush()
    with app.test_request_context('/c?ref=tbbbb0002',
                                  headers={'User-Agent': 'Googlebot/2.1'}):
        from flask import request
        rs.capture_referral_visit(request, _html_response(), None)
    assert rs.get_clicks_by_code(['tbbbb0002']) == {}


def test_visit_dedups_repeat_click(app, db_session):
    s = SiteSettings.get()
    s.referral_enabled = True
    db.session.flush()
    hdrs = {'User-Agent': 'Mozilla/5.0', 'Cookie': f'{rs.CLICK_COOKIE}=ucccc0003'}
    with app.test_request_context('/c?ref=ucccc0003', headers=hdrs):
        from flask import request
        rs.capture_referral_visit(request, _html_response(), None)
    assert rs.get_clicks_by_code(['ucccc0003']) == {}  # уже рахований -> дубль ігнор


def test_visit_skips_db_on_error_response(app, db_session):
    s = SiteSettings.get()
    s.referral_enabled = True
    db.session.flush()
    from flask import Response
    err = Response('<html>err</html>', status=500, content_type='text/html')
    with app.test_request_context('/c?ref=udddd0004',
                                  headers={'User-Agent': 'Mozilla/5.0'}):
        from flask import request
        rs.capture_referral_visit(request, err, None)
    assert rs.get_clicks_by_code(['udddd0004']) == {}  # на 500 клік не рахуємо


def test_inviter_hidden_for_inactive_trainer(app, db_session):
    s = SiteSettings.get()
    s.referral_enabled = True
    db.session.flush()
    t = Trainer(full_name='Неактивний Тренер', slug='inactive-inv', is_active=False)
    db.session.add(t)
    db.session.flush()
    code = rs.ensure_referral_code(t, prefix='t')
    with app.test_request_context(f'/c?ref={code}'):
        from flask import request
        assert rs.current_inviter_name(request, None) is None


def test_read_ref_cookie(app):
    with app.test_request_context('/', headers={'Cookie': f'{rs.REF_COOKIE}=t99887766'}):
        from flask import request
        assert rs.read_ref_cookie(request) == 't99887766'
    with app.test_request_context('/', headers={'Cookie': f'{rs.REF_COOKIE}=garbage'}):
        from flask import request
        assert rs.read_ref_cookie(request) is None
