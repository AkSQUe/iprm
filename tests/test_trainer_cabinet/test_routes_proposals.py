from app.extensions import db
from app.models.trainer_course_proposal import TrainerCourseProposal
from tests.test_trainer_cabinet._factories import login, make_trainer, make_user

DATA = {
    'title': 'КОС крові: діагностика',
    'theses': 'Методи визначення КОС\nФізіологічні межі рН\nБуферні системи',
    'language': 'Українська',
    'relevance': 'Лікарю важливо це знати, тому що...',
    'target_specialties': 'Анестезіологи, хірурги',
    'resources': '', 'future_topics': '', 'quiz_url': '',
}


def _setup(client):
    user = make_user()
    trainer = make_trainer(user)
    login(client, user)
    return trainer


def test_create_draft(client):
    trainer = _setup(client)
    resp = client.post('/trainer/proposals/new', data=DATA)
    assert resp.status_code == 302
    p = TrainerCourseProposal.query.filter_by(trainer_id=trainer.id).one()
    assert p.status == 'draft'
    assert p.theses == ['Методи визначення КОС', 'Фізіологічні межі рН', 'Буферні системи']


def test_title_limit_and_theses_limit(client):
    _setup(client)
    resp = client.post('/trainer/proposals/new', data={**DATA, 'title': 'x' * 51})
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'form-error' in html
    # C13: межа -- з TrainerCourseProposal.TITLE_MAX/THESES_MAX через
    # %(max)d, а не окремий рядок "50": розсинхрон між повідомленням і
    # реальним обмеженням тут неможливий за конструкцією.
    assert 'Не більше 50 символів' in html
    assert f'maxlength="{TrainerCourseProposal.TITLE_MAX}"' in html
    resp = client.post('/trainer/proposals/new',
                       data={**DATA, 'theses': '\n'.join(str(i) for i in range(11))})
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'form-error' in html and 'Не більше 10 тез' in html
    resp = client.post('/trainer/proposals/new', data={**DATA, 'theses': '  \n '})
    assert resp.status_code == 200 and 'form-error' in resp.get_data(as_text=True)


def test_submit_locks_editing(client):
    trainer = _setup(client)
    client.post('/trainer/proposals/new', data=DATA)
    p = TrainerCourseProposal.query.filter_by(trainer_id=trainer.id).one()
    view_url = f'/trainer/proposals/{p.id}'
    resp = client.post(view_url, data={**DATA, 'action': 'submit'})
    assert resp.status_code == 302
    db.session.expire_all()
    assert p.status == 'submitted'
    # Заблоковану пропозицію тренер не змінює: замість 409 (без шаблону,
    # з записом в ErrorLog) -- flash і повернення на перегляд.
    resp = client.post(view_url, data={**DATA, 'title': 'Інше'})
    assert resp.status_code == 302 and resp.headers['Location'].endswith(view_url)
    resp = client.post(f'/trainer/proposals/{p.id}/delete')
    assert resp.status_code == 302 and resp.headers['Location'].endswith(view_url)
    # Повторна спроба надіслати вже надіслану пропозицію -- теж заблокована.
    resp = client.post(view_url, data={**DATA, 'action': 'submit'})
    assert resp.status_code == 302 and resp.headers['Location'].endswith(view_url)
    db.session.expire_all()
    assert p.title == 'КОС крові: діагностика' and p.status == 'submitted'
    assert db.session.get(TrainerCourseProposal, p.id) is not None
    view = client.get(f'/trainer/proposals/{p.id}').get_data(as_text=True)
    assert 'КОС крові: діагностика' in view and 'name="title"' not in view


def test_title_whitespace_is_normalized(client):
    """CR/LF і подвійні пробіли в назві -- заголовок листа куратору
    будується з неї підстановкою в один рядок; необроблений перенос рядка
    там був би початком нового заголовка листа (header injection)."""
    trainer = _setup(client)
    resp = client.post('/trainer/proposals/new',
                       data={**DATA, 'title': 'КОС  крові:\r\n діагностика'})
    assert resp.status_code == 302
    p = TrainerCourseProposal.query.filter_by(trainer_id=trainer.id).one()
    assert p.title == 'КОС крові: діагностика'


def test_theses_field_carries_max_for_js(client):
    """trainer-theses.js читає ліміт з data-max, а не з константи 10,
    зашитої в самому скрипті окремо від моделі."""
    _setup(client)
    html = client.get('/trainer/proposals/new').get_data(as_text=True)
    assert f'data-max="{TrainerCourseProposal.THESES_MAX}"' in html


def test_delete_draft(client):
    trainer = _setup(client)
    client.post('/trainer/proposals/new', data=DATA)
    p = TrainerCourseProposal.query.filter_by(trainer_id=trainer.id).one()
    assert client.post(f'/trainer/proposals/{p.id}/delete').status_code == 302
    assert TrainerCourseProposal.query.filter_by(trainer_id=trainer.id).count() == 0


def test_foreign_proposal_is_404(client):
    owner = make_trainer(make_user(), name='Власник')
    p = TrainerCourseProposal(trainer_id=owner.id, title='Чуже', theses=['a'])
    db.session.add(p)
    db.session.commit()
    _setup(client)
    assert client.get(f'/trainer/proposals/{p.id}').status_code == 404
    assert client.post(f'/trainer/proposals/{p.id}', data=DATA).status_code == 404
    assert client.post(f'/trainer/proposals/{p.id}/delete').status_code == 404


def test_profile_page_lists_proposals(client):
    _setup(client)
    client.post('/trainer/proposals/new', data=DATA)
    html = client.get('/trainer/profile').get_data(as_text=True)
    assert 'КОС крові: діагностика' in html


def test_locked_post_flashes_message(client):
    trainer = _setup(client)
    p = TrainerCourseProposal(trainer_id=trainer.id, title='КОС', theses=['a'],
                              status='submitted')
    db.session.add(p)
    db.session.commit()
    client.post(f'/trainer/proposals/{p.id}', data=DATA)
    # Тост рендериться JSON-ом з \u-екрануванням, тож дивимось у сесію.
    with client.session_transaction() as sess:
        messages = [m for _cat, m in sess.get('_flashes', [])]
    assert any('вже надіслано' in m for m in messages)


def test_edit_and_submit_in_one_post(client):
    """"Надіслати куратору" -- кнопка основної форми: незбережені правки
    зберігаються і надсилаються тим самим запитом, а не губляться."""
    trainer = _setup(client)
    client.post('/trainer/proposals/new', data=DATA)
    p = TrainerCourseProposal.query.filter_by(trainer_id=trainer.id).one()
    resp = client.post(f'/trainer/proposals/{p.id}',
                       data={**DATA, 'title': 'Нова назва', 'theses': 'Перша\nДруга',
                             'action': 'submit'})
    assert resp.status_code == 302 and resp.headers['Location'].endswith('/trainer/profile')
    db.session.expire_all()
    assert p.title == 'Нова назва'
    assert p.theses == ['Перша', 'Друга']
    assert p.status == 'submitted' and p.submitted_at is not None


def test_submit_via_query_string(client):
    """Кнопка надсилання несе action і в formaction (?action=submit):
    form-single-submit.js вимикає кнопки на submit, і name/value вимкненої
    кнопки браузер у дані форми не кладе."""
    trainer = _setup(client)
    client.post('/trainer/proposals/new', data=DATA)
    p = TrainerCourseProposal.query.filter_by(trainer_id=trainer.id).one()
    resp = client.post(f'/trainer/proposals/{p.id}?action=submit', data=DATA)
    assert resp.status_code == 302
    db.session.expire_all()
    assert p.status == 'submitted'


def test_invalid_content_with_submit_is_not_submitted(client):
    trainer = _setup(client)
    client.post('/trainer/proposals/new', data=DATA)
    p = TrainerCourseProposal.query.filter_by(trainer_id=trainer.id).one()
    resp = client.post(f'/trainer/proposals/{p.id}',
                       data={**DATA, 'title': 'x' * 51, 'action': 'submit'})
    assert resp.status_code == 200 and 'form-error' in resp.get_data(as_text=True)
    db.session.expire_all()
    assert p.status == 'draft' and p.title == 'КОС крові: діагностика'


def test_new_proposal_submitted_directly(client):
    trainer = _setup(client)
    resp = client.post('/trainer/proposals/new', data={**DATA, 'action': 'submit'})
    assert resp.status_code == 302 and resp.headers['Location'].endswith('/trainer/profile')
    p = TrainerCourseProposal.query.filter_by(trainer_id=trainer.id).one()
    assert p.status == 'submitted'


def test_new_proposal_invalid_with_submit_creates_nothing(client):
    trainer = _setup(client)
    resp = client.post('/trainer/proposals/new',
                       data={**DATA, 'theses': '', 'action': 'submit'})
    assert resp.status_code == 200
    assert TrainerCourseProposal.query.filter_by(trainer_id=trainer.id).count() == 0


def test_edit_page_has_submit_inside_main_form(client):
    trainer = _setup(client)
    client.post('/trainer/proposals/new', data=DATA)
    p = TrainerCourseProposal.query.filter_by(trainer_id=trainer.id).one()
    html = client.get(f'/trainer/proposals/{p.id}').get_data(as_text=True)
    main_form = html[html.index('name="title"'):]
    main_form = main_form[:main_form.index('</form>')]
    assert 'name="action" value="submit"' in main_form
    assert f'/trainer/proposals/{p.id}/submit' not in html


def test_view_text_depends_on_status(client):
    trainer = _setup(client)
    submitted = TrainerCourseProposal(trainer_id=trainer.id, title='Надіслана',
                                      theses=['a'], status='submitted')
    accepted = TrainerCourseProposal(trainer_id=trainer.id, title='Прийнята',
                                     theses=['a'], status='accepted')
    db.session.add_all([submitted, accepted])
    db.session.commit()
    html = client.get(f'/trainer/proposals/{submitted.id}').get_data(as_text=True)
    assert 'на розгляді куратора' in html
    html = client.get(f'/trainer/proposals/{accepted.id}').get_data(as_text=True)
    assert 'на розгляді куратора' not in html
    assert 'прийняв' in html
