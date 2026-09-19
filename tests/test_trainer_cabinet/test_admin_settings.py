import io

from app.data.trainer_faq import DEFAULT_TRAINER_FAQ_HTML
from app.extensions import db
from app.models.site_settings import SiteSettings
from tests.support.rbac import make_super_admin
from tests.test_trainer_cabinet._factories import login


def _admin(client):
    admin = make_super_admin(email='tc-sadmin@test.com')
    db.session.commit()
    login(client, admin)


def test_form_prefilled_with_default_faq(client):
    _admin(client)
    SiteSettings.get().trainer_faq_html = ''
    db.session.commit()
    html = client.get('/admin/settings/trainers').get_data(as_text=True)
    assert 'Вітаємо із приєднанням' in html


def test_save_faq_email_and_pdf(client):
    _admin(client)
    resp = client.post('/admin/settings/trainers', data={
        'faq_html': '<p>Новий текст {email}</p>',
        'contract_email': 'curator@test.com',
        'contract_pdf': (io.BytesIO(b'%PDF-1.4 new'), 'dogovir.pdf'),
    }, content_type='multipart/form-data')
    assert resp.status_code == 302
    s = SiteSettings.get()
    db.session.refresh(s)
    assert s.trainer_faq_html == '<p>Новий текст {email}</p>'
    assert s.trainer_contract_email == 'curator@test.com'
    assert s.trainer_contract_pdf == b'%PDF-1.4 new'
    assert s.trainer_contract_filename == 'dogovir.pdf'


def test_long_filename_with_path_is_truncated(client):
    """Ім'я файлу з поля <input type=file> -- рядок від клієнта, не наше:
    старий Internet Explorer і деякі android-браузери досі шлють повний
    шлях (C:\\fakepath\\...), а довжина обмежена лише тим, що дозволить
    зберегти файлова система відправника. Колонка -- String(255)."""
    _admin(client)
    long_name = 'C:\\fakepath\\' + ('a' * 300) + '.pdf'
    resp = client.post('/admin/settings/trainers', data={
        'faq_html': '', 'contract_email': '',
        'contract_pdf': (io.BytesIO(b'%PDF-1.4 x'), long_name),
    }, content_type='multipart/form-data')
    assert resp.status_code == 302
    s = SiteSettings.get()
    db.session.refresh(s)
    assert len(s.trainer_contract_filename) <= 255
    assert s.trainer_contract_filename.endswith('.pdf')
    assert '\\' not in s.trainer_contract_filename and '/' not in s.trainer_contract_filename


def test_reject_non_pdf(client):
    _admin(client)
    resp = client.post('/admin/settings/trainers', data={
        'faq_html': '', 'contract_email': '',
        'contract_pdf': (io.BytesIO(b'MZ not a pdf'), 'evil.pdf'),
    }, content_type='multipart/form-data')
    assert resp.status_code == 200
    assert 'PDF' in resp.get_data(as_text=True)


def test_remove_contract(client):
    _admin(client)
    s = SiteSettings.get()
    s.trainer_contract_pdf = b'%PDF-1.4 x'
    s.trainer_contract_filename = 'x.pdf'
    db.session.commit()
    client.post('/admin/settings/trainers', data={
        'faq_html': '', 'contract_email': '', 'remove_contract': 'y'})
    db.session.refresh(s)
    assert not s.has_trainer_contract and s.trainer_contract_pdf is None


def test_default_faq_with_crlf_saves_as_empty(client):
    """Браузер нормалізує переноси рядків textarea у \\r\\n -- порівняння з
    дефолтом (де \\n) не мусить через це ламатись і зберігати повний текст
    замість ''."""
    _admin(client)
    client.post('/admin/settings/trainers', data={
        'faq_html': DEFAULT_TRAINER_FAQ_HTML.replace('\n', '\r\n'),
        'contract_email': '',
    })
    s = SiteSettings.get()
    db.session.refresh(s)
    assert s.trainer_faq_html == ''


def test_requires_settings_permission(client):
    from tests.support.rbac import make_user_with_role
    viewer = make_user_with_role('viewer', email='tc-sviewer@test.com')
    db.session.commit()
    login(client, viewer)
    assert client.get('/admin/settings/trainers').status_code == 403


# --- B9: немає жодної адреси для договорів ---------------------------------------

def test_warning_when_no_contract_address(client):
    _admin(client)
    s = SiteSettings.get()
    s.trainer_contract_email = ''
    s.email = ''
    db.session.commit()
    html = client.get('/admin/settings/trainers').get_data(as_text=True)
    assert 'data-contract-email-missing' in html


def test_no_warning_when_site_email_is_fallback(client):
    _admin(client)
    s = SiteSettings.get()
    s.trainer_contract_email = ''
    s.email = 'office@test.com'
    db.session.commit()
    html = client.get('/admin/settings/trainers').get_data(as_text=True)
    assert 'data-contract-email-missing' not in html
