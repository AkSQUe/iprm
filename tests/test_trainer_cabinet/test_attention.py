"""E2: блок «Потребує уваги» на /trainer/.

Повернута пропозиція, неповна анкета й відсутній договір раніше
ховались на інших сторінках: тренер бачив їх, лише якщо сам туди заходив.
"""
from app.extensions import db
from app.models.site_settings import SiteSettings
from app.models.trainer_course_proposal import TrainerCourseProposal
from app.models.trainer_profile import TrainerProfile
from app.services import trainer_cabinet as svc
from tests.test_trainer_cabinet._factories import login, make_trainer, make_user


def _proposal(trainer, *, status='draft', comment=None, title='КОС'):
    p = TrainerCourseProposal(trainer_id=trainer.id, title=title, theses=['a'],
                              status=status, curator_comment=comment)
    db.session.add(p)
    db.session.commit()
    return p


def _complete_profile(trainer):
    p = TrainerProfile(trainer_id=trainer.id, full_name='Іваненко Петро',
                       phone='+380671112233', email='tc-p@test.com',
                       registration_address='Київ')
    p.fop_iban = 'UA213223130000026007233566001'
    p.fop_rnokpp = '3123456789'
    p.tax_id = '3123456789'
    db.session.add(p)
    db.session.commit()
    return p


def _settings(with_contract):
    s = SiteSettings.get()
    s.trainer_contract_filename = 'contract.pdf' if with_contract else ''
    db.session.commit()
    return s


def _kinds(items):
    return [i['kind'] for i in items]


# --- сервіс ------------------------------------------------------------------

def test_nothing_to_show(app):
    trainer = make_trainer(make_user())
    _complete_profile(trainer)
    assert svc.attention_items(trainer, _settings(True)) == []


def test_returned_proposal_listed_with_comment(app):
    trainer = make_trainer(make_user())
    _complete_profile(trainer)
    p = _proposal(trainer, comment='Уточніть тези')
    items = svc.attention_items(trainer, _settings(True))
    assert items == [{'kind': 'returned', 'proposal_id': p.id, 'title': 'КОС',
                      'comment': 'Уточніть тези'}]


def test_plain_draft_and_other_statuses_are_not_returned(app):
    trainer = make_trainer(make_user())
    _complete_profile(trainer)
    _proposal(trainer)                                   # звичайна чернетка
    _proposal(trainer, comment='   ')                    # порожній коментар
    _proposal(trainer, status='submitted', comment='x')  # на розгляді
    _proposal(trainer, status='accepted', comment='y')   # прийнята
    assert svc.attention_items(trainer, _settings(True)) == []


def test_other_trainers_proposals_ignored(app):
    trainer = make_trainer(make_user())
    _complete_profile(trainer)
    _proposal(make_trainer(make_user()), comment='чуже')
    assert svc.attention_items(trainer, _settings(True)) == []


def test_incomplete_profile_and_missing_contract(app):
    trainer = make_trainer(make_user())
    items = svc.attention_items(trainer, _settings(False))
    assert _kinds(items) == ['profile_incomplete', 'contract_missing']


def test_service_does_not_commit(app, monkeypatch):
    """Функція викликається з GET-маршруту: коміт у ній зафіксував би все, що
    встигло змінитись у сесії, без відома маршруту."""
    trainer = make_trainer(make_user())
    settings = _settings(False)
    calls = []
    monkeypatch.setattr(db.session, 'commit', lambda: calls.append(1))
    svc.attention_items(trainer, settings)
    assert calls == []


# --- сторінка ----------------------------------------------------------------

def test_block_shows_returned_proposal_with_link(client):
    user = make_user()
    trainer = make_trainer(user)
    _complete_profile(trainer)
    p = _proposal(trainer, comment='Додайте протоколи')
    _settings(True)
    login(client, user)
    html = client.get('/trainer/').get_data(as_text=True)
    assert 'id="trainer-attention-title"' in html
    assert 'Додайте протоколи' in html
    assert f'/trainer/proposals/{p.id}' in html


def test_block_shows_profile_and_contract_items(client):
    user = make_user()
    make_trainer(user)
    _settings(False)
    login(client, user)
    html = client.get('/trainer/').get_data(as_text=True)
    block = html[html.index('id="trainer-attention-title"'):]
    block = block[:block.index('</section>')]
    assert '/trainer/profile' in block
    assert '/trainer/contract' in block
    assert 'alert--info' in block


def test_block_hidden_when_nothing_to_show(client):
    user = make_user()
    trainer = make_trainer(user)
    _complete_profile(trainer)
    _settings(True)
    login(client, user)
    html = client.get('/trainer/').get_data(as_text=True)
    assert 'trainer-attention' not in html
