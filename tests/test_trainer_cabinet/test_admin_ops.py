"""Адмінка й експлуатація кабінету тренера: кеш, прогрів налаштувань,
повідомлення адмінки, активний пункт меню, підтвердження видалення."""
from sqlalchemy import inspect as sa_inspect

from app.extensions import db
from app.models.site_settings import SiteSettings
from app.models.trainer_course_proposal import TrainerCourseProposal
from tests.support.rbac import make_super_admin
from tests.test_trainer_cabinet._factories import login, make_trainer, make_user


def _admin(client):
    admin = make_super_admin(email='tc-ops-admin@test.com')
    db.session.commit()
    login(client, admin)
    return admin


def _flashes(client):
    with client.session_transaction() as sess:
        return [m for _cat, m in sess.get('_flashes', [])]


# --- M4: прогрів SiteSettings перед health-чеками -------------------------

def test_health_warmup_skips_deferred_contract_pdf(app):
    from app.services import integration_health
    settings = SiteSettings.get()
    db.session.expire(settings)
    integration_health._warm_settings(settings)
    unloaded = sa_inspect(settings).unloaded
    # PDF договору (до 10 МБ) не потрібен жодному чеку -- його не тягнемо.
    assert 'trainer_contract_pdf' in unloaded
    # Решта прогріта: чужий потік не піде довантажувати через спільну сесію.
    assert 'trainer_contract_filename' not in unloaded
    assert 'email' not in unloaded


# --- M6: приватні відповіді кабінету -------------------------------------

def test_cabinet_html_is_no_store_even_for_anonymous(client):
    resp = client.get('/trainer/')
    assert resp.status_code == 302
    assert 'no-store' in resp.headers['Cache-Control']


def test_contract_download_is_no_store(client):
    settings = SiteSettings.get()
    settings.trainer_contract_pdf = b'%PDF-1.4 contract'
    settings.trainer_contract_filename = 'contract.pdf'
    db.session.commit()
    user = make_user()
    make_trainer(user)
    login(client, user)
    resp = client.get('/trainer/contract/download')
    assert resp.status_code == 200
    cache = resp.headers['Cache-Control']
    assert 'no-store' in cache and 'private' in cache


# --- M7: повідомлення про невдале повернення ------------------------------

def _submitted():
    trainer = make_trainer(make_user())
    p = TrainerCourseProposal(trainer_id=trainer.id, title='КОС', theses=['a'],
                              status='submitted')
    db.session.add(p)
    db.session.commit()
    return p


def test_return_too_long_comment_shows_field_error(client):
    _admin(client)
    p = _submitted()
    client.post(f'/admin/trainers/proposals/{p.id}/return', data={'comment': 'x' * 2001})
    assert any('2000' in m for m in _flashes(client))
    db.session.expire_all()
    assert p.status == 'submitted'


def test_return_csrf_failure_never_reaches_route(client, app):
    """CSRF перевіряє глобальний CSRFProtect ще до маршруту (400), тож
    "Коментар задовгий" на CSRF-збої фактично не показувався; маршрут
    однаково розрізняє помилку поля й решту (див. тест вище)."""
    _admin(client)
    p = _submitted()
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        resp = client.post(f'/admin/trainers/proposals/{p.id}/return', data={'comment': 'Ок'})
    finally:
        app.config['WTF_CSRF_ENABLED'] = False
    assert resp.status_code == 400
    assert not any('задовгий' in m for m in _flashes(client))
    db.session.expire_all()
    assert p.status == 'submitted'


# --- M8: активний пункт бічного меню --------------------------------------

def _active_link(html, href):
    marker = f'href="{href}" class="admin-sidebar__link admin-sidebar__link--active"'
    return marker in html


def test_sidebar_trainers_active_on_questionnaire(client):
    _admin(client)
    trainer = make_trainer(make_user())
    html = client.get(f'/admin/trainers/{trainer.id}/questionnaire').get_data(as_text=True)
    assert _active_link(html, '/admin/trainers')


def test_sidebar_settings_active_on_trainer_settings(client):
    _admin(client)
    html = client.get('/admin/settings/trainers').get_data(as_text=True)
    assert _active_link(html, '/admin/settings')


# --- M9: видалення чернетки -- через спільний діалог підтвердження --------

def test_delete_draft_asks_confirmation(client):
    user = make_user()
    trainer = make_trainer(user)
    login(client, user)
    p = TrainerCourseProposal(trainer_id=trainer.id, title='КОС', theses=['a'])
    db.session.add(p)
    db.session.commit()
    html = client.get(f'/trainer/proposals/{p.id}').get_data(as_text=True)
    form = html[html.index(f'action="/trainer/proposals/{p.id}/delete"'):]
    form = form[:form.index('</form>')]
    assert 'data-confirm="' in form and 'data-confirm-danger' in form
