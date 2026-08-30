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
