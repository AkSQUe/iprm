from app.extensions import db
from app.models.site_settings import SiteSettings
from tests.test_trainer_cabinet._factories import login, make_trainer, make_user


def _trainer_login(client):
    user = make_user()
    make_trainer(user)
    login(client, user)


def _set_pdf(data, name='Договір ІПРМ.pdf'):
    s = SiteSettings.get()
    s.trainer_contract_pdf = data
    s.trainer_contract_filename = name if data else ''
    db.session.commit()


def test_contract_without_file(client):
    _set_pdf(None)
    _trainer_login(client)
    html = client.get('/trainer/contract').get_data(as_text=True)
    assert 'буде додано найближчим часом' in html
    assert client.get('/trainer/contract/download').status_code == 404


def test_contract_download(client):
    _set_pdf(b'%PDF-1.4 contract')
    _trainer_login(client)
    html = client.get('/trainer/contract').get_data(as_text=True)
    assert '/trainer/contract/download' in html
    resp = client.get('/trainer/contract/download')
    assert resp.status_code == 200
    assert resp.mimetype == 'application/pdf'
    assert resp.data == b'%PDF-1.4 contract'
    assert 'attachment' in resp.headers['Content-Disposition']


def test_download_requires_trainer(client):
    _set_pdf(b'%PDF-1.4 contract')
    login(client, make_user())
    assert client.get('/trainer/contract/download').status_code == 404


def test_contract_shows_email(client):
    s = SiteSettings.get()
    s.trainer_contract_email = 'curator@test.com'
    db.session.commit()
    _trainer_login(client)
    assert 'curator@test.com' in client.get('/trainer/contract').get_data(as_text=True)
