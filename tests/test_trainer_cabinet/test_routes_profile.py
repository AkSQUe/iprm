from app.extensions import db
from app.models.trainer_profile import TrainerProfile
from tests.test_trainer_cabinet._factories import login, make_trainer, make_user


def _data(**over):
    data = {
        'full_name': 'Іваненко Іван Іванович', 'birth_date': '1985-03-02',
        'education': 'НМУ ім. Богомольця', 'position_titles': 'Лікар-лаборант, к.мед.н.',
        'workplace': 'Клініка, Київ', 'phone': '+380671234567', 'email': 'ivan@test.com',
        'social_links': 'https://facebook.com/ivan', 'photo_url': '',
        'fop_recipient': 'ФОП Іваненко І.І.', 'fop_iban': 'UA213052990000026003006239637',
        'fop_rnokpp': '1234567890', 'fop_payment_purpose': 'Послуги за КВЕД 85.59',
        'card_number': '4149 6090 1234 5678', 'tax_id': '1234567890',
        'registration_address': 'м. Київ, вул. Хрещатик, 1', 'edrpou': '',
    }
    data.update(over)
    return data


def test_profile_save_and_prefill(client):
    user = make_user()
    trainer = make_trainer(user)
    login(client, user)
    resp = client.post('/trainer/profile', data=_data(), follow_redirects=True)
    assert resp.status_code == 200
    profile = TrainerProfile.query.filter_by(trainer_id=trainer.id).one()
    assert profile.fop_iban == 'UA213052990000026003006239637'
    assert profile.is_complete
    html = client.get('/trainer/profile').get_data(as_text=True)
    assert 'UA213052990000026003006239637' in html
    assert 'Іваненко Іван Іванович' in html


def test_profile_invalid_email_rerenders(client):
    user = make_user()
    make_trainer(user)
    login(client, user)
    resp = client.post('/trainer/profile', data=_data(email='not-an-email'))
    assert resp.status_code == 200
    assert 'form-error' in resp.get_data(as_text=True)
    assert TrainerProfile.query.count() == 0 or not TrainerProfile.query.first().email


def test_clearing_secret_keeps_nothing(client):
    user = make_user()
    trainer = make_trainer(user)
    login(client, user)
    client.post('/trainer/profile', data=_data())
    client.post('/trainer/profile', data=_data(card_number=''))
    db.session.expire_all()
    assert TrainerProfile.query.filter_by(trainer_id=trainer.id).one().card_number == ''
