"""E3: реферальне посилання й баланс у кабінеті тренера.

Розмітка блоку -- спільний партіал з /auth/account: перші тести фіксують,
що кабінет учасника після винесення рендерить те саме.
"""
from app.extensions import db
from app.models.site_settings import SiteSettings
from app.models.trainer import Trainer
from tests.test_trainer_cabinet._factories import login, make_trainer, make_user


def _referral(enabled):
    s = SiteSettings.get()
    s.referral_enabled = enabled
    db.session.commit()


def _section(html, title_id='referral-title'):
    start = html.index(f'id="{title_id}"')
    return html[start:html.index('</section>', start)]


# --- /auth/account: той самий блок після винесення в партіал ----------------

def test_account_referral_block_when_enabled(client):
    _referral(True)
    user = make_user()
    login(client, user)
    html = client.get('/auth/account').get_data(as_text=True)
    db.session.expire_all()
    code = db.session.get(type(user), user.id).referral_code
    assert code
    block = _section(html)
    assert 'class="referral-share__input"' in block and code in block
    assert 'referral-share__balance-value">0<' in block
    assert 'data-copy=' in block and 'referral-tools' in block
    assert 'css/referral-share.css' in html
    assert 'js/copy-to-clipboard.js' in html and 'js/referral-share-tools.js' in html


def test_account_no_referral_block_when_disabled(client):
    _referral(False)
    login(client, make_user())
    html = client.get('/auth/account').get_data(as_text=True)
    assert 'id="referral-title"' not in html
    assert 'css/referral-share.css' not in html


# --- /trainer/ -----------------------------------------------------------------

def test_trainer_block_shows_link_and_balance(client):
    _referral(True)
    user = make_user()
    trainer = make_trainer(user)
    trainer.referral_balance = 120
    db.session.commit()
    login(client, user)
    html = client.get('/trainer/').get_data(as_text=True)
    db.session.expire_all()
    code = db.session.get(Trainer, trainer.id).referral_code
    # Код згенеровано ліниво й ЗБЕРЕЖЕНО: наступний запит дасть те саме посилання.
    assert code and code.startswith('t')
    block = _section(html)
    assert code in block
    assert 'referral-share__balance-value">120<' in block
    assert 'css/referral-share.css' in html
    assert 'js/copy-to-clipboard.js' in html and 'js/referral-share-tools.js' in html
    # Блок з'являється через apple-reveal: без скрипта він лишився б невидимим.
    assert 'js/apple-reveal.js' in html


def test_trainer_link_is_stable_between_requests(client):
    _referral(True)
    user = make_user()
    trainer = make_trainer(user)
    login(client, user)
    client.get('/trainer/')
    db.session.expire_all()
    first = db.session.get(Trainer, trainer.id).referral_code
    assert first
    client.get('/trainer/')
    db.session.expire_all()
    assert db.session.get(Trainer, trainer.id).referral_code == first


def test_trainer_no_block_and_no_code_when_disabled(client):
    _referral(False)
    user = make_user()
    trainer = make_trainer(user)
    login(client, user)
    html = client.get('/trainer/').get_data(as_text=True)
    assert 'id="referral-title"' not in html
    assert 'css/referral-share.css' not in html
    db.session.expire_all()
    assert db.session.get(Trainer, trainer.id).referral_code is None
