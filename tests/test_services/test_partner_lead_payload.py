"""Що саме ІПРМ розповідає партнеру про заявку з реклами.

Два нові ключі й одна обіцянка сумісності.

`answers` -- пари питання/відповідь із ЛЮДСЬКИМИ підписами. У `field_data`
Meta кладе внутрішні ключі варіантів (`ортопедія_/_травматологія`), і
віддавати їх менеджеру означало б показати те, чого людина у формі не
бачила.

`custom_fields` при цьому лишається ДОСЛІВНИМ. Порядок деплою -- MM Medic
першим, і кілька днів він працює саме на цьому ключі; змінити його
означало б зламати робочу інтеграцію заради косметики.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.meta_lead import MetaLead, MetaLeadForm
from app.services import meta_form_schema, partner_events
from tests.support.fake_meta_graph import make_form


def _lead(**over):
    params = {
        'leadgen_id': f'lg-{id(object())}',
        'created_time': datetime.now(timezone.utc),
        'form_id': '9988776655',
        'field_data': {'ваша_спеціальність?': 'ортопедія_/_травматологія'},
    }
    params.update(over)
    lead = MetaLead(**params)
    db.session.add(lead)
    db.session.flush()
    return lead


def test_answers_carry_human_labels(app):
    meta_form_schema.save_form(make_form('9988776655'))
    db.session.flush()

    payload = partner_events._lead_payload(_lead())

    assert payload['answers'] == [
        {'question': 'Ваша спеціальність?',
         'answer': 'Ортопедія / травматологія'},
    ]


def test_custom_fields_stay_verbatim(app):
    """Обіцянка сумісності: старий приймач не має помітити змін."""
    meta_form_schema.save_form(make_form('9988776655'))
    db.session.flush()

    payload = partner_events._lead_payload(_lead())

    assert payload['custom_fields'] == {
        'ваша_спеціальність?': 'ортопедія_/_травматологія',
    }


def test_offer_is_built_from_the_linked_event(app):
    course = Course(title='Плазмотерапія: базовий курс', slug='pl-base')
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(
        course_id=course.id, status='published', price=4500,
        start_date=datetime.now(timezone.utc) + timedelta(days=13),
        location='Харків',
    )
    db.session.add(instance)
    db.session.flush()
    form = meta_form_schema.save_form(make_form('9988776655'))
    form.course_instance_id = instance.id
    db.session.flush()

    offer = partner_events._lead_payload(_lead())['offer']

    assert offer['course_instance_id'] == instance.id
    assert offer['title'] == 'Плазмотерапія: базовий курс'
    assert offer['price'] == '4500.00'
    assert offer['url'].startswith('http')


def test_offer_is_none_without_a_link(app):
    """Форму не прив'язали -- підказки немає, решта payload ціла."""
    meta_form_schema.save_form(make_form('9988776655'))
    db.session.flush()

    payload = partner_events._lead_payload(_lead())

    assert payload['offer'] is None
    assert payload['email'] is None or 'email' in payload


def test_lead_of_an_unknown_form_still_builds(app):
    """Схеми немає взагалі -- подія мусить піти, хай і з машинними підписами."""
    payload = partner_events._lead_payload(_lead(form_id='форма-без-схеми'))

    assert payload['offer'] is None
    assert payload['answers'][0]['question'] == 'Ваша спеціальність?'


@contextmanager
def _without_request_context():
    """Прогін БЕЗ контексту запиту -- рівно те середовище, у якому подія
    й народжується на проді.

    pytest-flask autouse-фікстурою пхає request-контекст у КОЖЕН тест, де є
    фікстура `app`. Через нього `url_for(_external=True)` тут працював, а в
    планувальнику (`scheduler_service`, лише `app_context`) і в CLI
    (`@with_appcontext`) падав RuntimeError -- і посилання на захід у
    партнера завжди було порожнім. Тест, який цього не знімає, засвідчує
    середовище, якого в проді немає.
    """
    from flask.globals import _cv_request

    token = _cv_request.set(None)
    try:
        yield
    finally:
        _cv_request.reset(token)


@contextmanager
def _sql_log():
    """Журнал SQL, що пішов у базу за час блоку."""
    from sqlalchemy import event as sa_event

    statements = []

    def _record(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    sa_event.listen(db.engine, 'before_cursor_execute', _record)
    try:
        yield statements
    finally:
        sa_event.remove(db.engine, 'before_cursor_execute', _record)


def _linked_form(instance_id, form_id='9988776655'):
    form = meta_form_schema.save_form(make_form(form_id))
    form.course_instance_id = instance_id
    db.session.flush()
    return form


def _instance(city='Харків'):
    course = Course(title='Плазмотерапія: базовий курс', slug='pl-base-2')
    db.session.add(course)
    db.session.flush()
    instance = CourseInstance(
        course_id=course.id, status='published', price=4500,
        start_date=datetime.now(timezone.utc) + timedelta(days=13),
        location=city,
    )
    db.session.add(instance)
    db.session.flush()
    return instance


def test_offer_url_is_built_without_a_request_context(app):
    """Посилання будується з `website_url`, а не з `url_for(_external=True)`.

    Обидва реальні виклики -- поза запитом; зовнішній `url_for` там кидає
    RuntimeError, бо `SERVER_NAME` не заданий у жодному класі конфігу.
    """
    from flask import has_request_context

    from app.models.site_settings import SiteSettings

    settings = SiteSettings.get()
    before = settings.website_url
    settings.website_url = 'https://iprm.example'
    instance = _instance()
    _linked_form(instance.id)
    lead = _lead()
    try:
        with _without_request_context():
            assert not has_request_context()
            offer = partner_events._lead_payload(lead)['offer']
    finally:
        settings.website_url = before
        db.session.flush()

    assert offer['url'] == 'https://iprm.example/courses/pl-base-2'


def test_answers_do_not_repeat_standard_fields(app):
    """ПІБ, пошта й телефон уже їдуть окремими ключами payload.

    Друга копія персональних даних у чужій системі -- зайва видача, а не
    зручність: картка ліда відсіює ті самі поля.
    """
    meta_form_schema.save_form(make_form('9988776655'))
    db.session.flush()
    lead = _lead(field_data={
        'email': 'lead@example.com',
        'phone_number': '+380501112233',
        'full_name': 'Тест Тестенко',
        'ваша_спеціальність?': 'ортопедія_/_травматологія',
    })

    payload = partner_events._lead_payload(lead)

    questions = [answer['question'] for answer in payload['answers']]
    assert questions == ['Ваша спеціальність?']
    # Дослівний зріз Meta лишається цілим -- на ньому живе старий приймач.
    assert 'email' in payload['custom_fields']


def test_form_schema_is_read_once_per_event(app):
    """Один рядок `meta_lead_forms` -- один запит.

    Підписи питань і захід беруться з ОДНІЄЇ форми; два походи в базу
    множились на всю історію при бекфілі.
    """
    instance = _instance()
    _linked_form(instance.id)
    lead = _lead()

    with _sql_log() as statements:
        partner_events._lead_payload(lead)

    reads = [s for s in statements if 'meta_lead_forms' in s]
    assert len(reads) == 1, f'очікували один запит форми, отримали {len(reads)}'
