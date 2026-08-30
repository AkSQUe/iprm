"""Тести підписів питань і варіантів відповіді Meta-форми.

Дефект, з якого це почалося: на картці заявки менеджер бачив
`ваша_спеціальність?` і `ортопедія_/_травматологія` замість тексту, який
бачила людина у формі. Причина не в нашій обробці -- Graph API кладе у
`field_data` заявки внутрішній КЛЮЧ обраного варіанта, а підпис віддає
лише у схемі самої форми.

Тому майже кожен тест тут закінчується твердженням про КОНКРЕТНИЙ рядок,
який побачить менеджер, а не про кількість збережених схем.
"""
import pytest

from app.extensions import db
from app.models.meta_lead import MetaLeadForm
from app.services import meta_form_schema as schema
from tests.support.fake_meta_graph import (
    FakeMetaGraphClient,
    make_form,
    make_question,
)


FORM_ID = '9988776655'


@pytest.fixture
def saved_form(app):
    """Схема дефолтної форми фейка, вже збережена в базі."""
    form = schema.save_form(make_form(FORM_ID), page_id='555000111')
    db.session.commit()
    return form


# --- розбір схеми ---------------------------------------------------------

def test_parse_questions_keeps_option_key_as_the_key(app):
    """Ключ -> підпис, а не навпаки: у заявці лежить саме ключ."""
    payload = make_form(questions=[make_question(
        'ваша_спеціальність?', 'Ваша спеціальність?',
        [('ортопедія_/_травматологія', 'Ортопедія / травматологія')],
    )])

    parsed = schema.parse_questions(payload)

    assert parsed['ваша_спеціальність?']['label'] == 'Ваша спеціальність?'
    assert parsed['ваша_спеціальність?']['options'] == {
        'ортопедія_/_травматологія': 'Ортопедія / травматологія',
    }


def test_parse_questions_skips_entries_without_key(app):
    """Питання без ключа нема до чого прикласти -- воно не має потрапити в схему."""
    payload = {'questions': [
        {'label': 'Питання без ключа'},
        'не dict узагалі',
        make_question('справжнє', 'Справжнє'),
    ]}

    assert list(schema.parse_questions(payload)) == ['справжнє']


def test_save_form_is_idempotent_by_form_id(app):
    """Повторний прогін оновлює схему, а не заводить другу."""
    schema.save_form(make_form(FORM_ID, name='Стара назва'))
    db.session.commit()
    schema.save_form(make_form(FORM_ID, name='Нова назва'))
    db.session.commit()

    forms = MetaLeadForm.query.filter_by(form_id=FORM_ID).all()
    assert len(forms) == 1
    assert forms[0].name == 'Нова назва'


def test_save_form_without_id_saves_nothing(app):
    """Схема без form_id не прив'яжеться до жодного ліда -- не зберігаємо."""
    assert schema.save_form({'name': 'Форма без id'}) is None
    assert MetaLeadForm.query.count() == 0


# --- підстановка на показі ------------------------------------------------

def test_answers_show_what_the_person_saw(app, saved_form):
    """Головний критерій: у картці -- текст форми, а не ключі Meta."""
    field_data = {
        'ваша_спеціальність?': 'ортопедія_/_травматологія',
        'чи_працюєте_ви_з_пацієнтами_після_бойових_ушкоджень?': 'так,_іноді',
    }

    answers = schema.answers_for(field_data, FORM_ID)

    assert answers == [
        ('Ваша спеціальність?', 'Ортопедія / травматологія'),
        ('Чи працюєте ви з пацієнтами після бойових ушкоджень?', 'Так, іноді'),
    ]


def test_free_text_answer_is_untouched(app, saved_form):
    """Вільний текст приходить як його ввела людина -- чіпати його не можна."""
    field_data = {"напишіть_ваше_ім'я_та_прізвище": 'Касімов Олександр'}

    answers = schema.answers_for(field_data, FORM_ID)

    assert answers == [("Напишіть ваше ім'я та прізвище", 'Касімов Олександр')]


def test_multi_select_maps_every_chosen_option(app):
    """Кілька обраних варіантів `flatten_field_data` склеює комою.

    Розібрати їх назад можна однозначно: у ключі Meta пробіл після коми теж
    став би підкресленням, тож «кома з пробілом» роздiляє саме варіанти.
    """
    schema.save_form(make_form(FORM_ID, questions=[make_question(
        'типи', 'Типи PRP',
        [('p-prp', 'P-PRP'), ('l-prp', 'L-PRP'), ('t-prp', 'T-PRP')],
    )]))
    db.session.commit()

    answers = schema.answers_for({'типи': 'p-prp, t-prp'}, FORM_ID)

    assert answers == [('Типи PRP', 'P-PRP, T-PRP')]


def test_text_with_comma_is_not_cut_into_options(app):
    """Частковий збіг не приймаємо: це текст із комою, а не кілька варіантів."""
    schema.save_form(make_form(FORM_ID, questions=[make_question(
        'коментар', 'Коментар', [('p-prp', 'P-PRP')],
    )]))
    db.session.commit()

    answers = schema.answers_for({'коментар': 'p-prp, хочу дізнатись більше'},
                                 FORM_ID)

    assert answers == [('Коментар', 'p-prp, хочу дізнатись більше')]


def test_unknown_option_falls_back_to_humanize(app, saved_form):
    """Варіанта немає в схемі -- лишається та сама здогадка, що й без схеми.

    Вигадати підпис нема звідки, але й показувати ключ із підкресленнями
    сенсу немає: це рівно той випадок, заради якого `humanize` і існує.
    """
    answers = schema.answers_for(
        {'ваша_спеціальність?': 'ключ_якого_немає_в_схемі'}, FORM_ID)

    label, value = answers[0]
    assert label == 'Ваша спеціальність?'
    # Схема є, але варіанта в ній немає -- лишається лише здогадка humanize.
    assert value == 'Ключ якого немає в схемі'


def test_standard_fields_are_skipped(app, saved_form):
    """Пошта й телефон показані окремими полями -- у списку питань їх бути не має."""
    field_data = {'email': 'a@b.co', 'ваша_спеціальність?': 'дерматологія'}

    answers = schema.answers_for(field_data, FORM_ID, skip={'email'})

    assert answers == [('Ваша спеціальність?', 'Дерматологія')]


def test_answers_keep_form_order(app, saved_form):
    """Порядок питань -- як у формі, тобто як у відповіді Meta."""
    field_data = {
        'чи_працюєте_ви_з_пацієнтами_після_бойових_ушкоджень?': 'ні',
        'ваша_спеціальність?': 'дерматологія',
    }

    labels = [label for label, _ in schema.answers_for(field_data, FORM_ID)]

    assert labels == ['Чи працюєте ви з пацієнтами після бойових ушкоджень?',
                      'Ваша спеціальність?']


def test_two_questions_with_the_same_label_both_survive(app):
    """Список пар, а не dict: однаковий підпис не має ковтати відповідь."""
    schema.save_form(make_form(FORM_ID, questions=[
        make_question('коментар_1', 'Ваш коментар'),
        make_question('коментар_2', 'Ваш коментар'),
    ]))
    db.session.commit()

    answers = schema.answers_for(
        {'коментар_1': 'перший', 'коментар_2': 'другий'}, FORM_ID)

    assert answers == [('Ваш коментар', 'перший'), ('Ваш коментар', 'другий')]


# --- запасний шлях: схеми немає --------------------------------------------

def test_without_schema_keys_are_humanized(app):
    """Форму видалили в Meta -- картка все одно має читатись."""
    answers = schema.answers_for(
        {'ваша_спеціальність?': 'ортопедія_/_травматологія'}, 'форма-без-схеми')

    assert answers == [('Ваша спеціальність?', 'Ортопедія / травматологія')]


@pytest.mark.parametrize('value', [
    'kularich22@gmail.com',       # пошта у вільному питанні
    'Касімов Олександр',          # текст, який ввела людина
    '+380937568180',              # номер
    'telegram',                   # одне слово без підкреслень
])
def test_without_schema_free_text_is_not_guessed(app, value):
    """Здогадка про ключ вузька навмисно: підмінити текст людини не можна."""
    answers = schema.answers_for({'питання': value}, 'форма-без-схеми')

    assert answers[0][1] == value


def test_humanize_does_not_invent_letter_case():
    """`p-prp` лишається `p-prp`: вигадати `P-PRP` -- це вигадати дані."""
    assert schema.humanize('(p-prp,_l-prp)') == '(p-prp, l-prp)'


# --- походи в Graph API ---------------------------------------------------

def test_sync_page_forms_saves_schemas_of_all_forms(app):
    client = FakeMetaGraphClient(forms=[
        make_form('111', name='Активна'),
        make_form('222', name='Зупинена', status='PAUSED'),
    ])

    saved = schema.sync_page_forms(client, '555000111')

    assert saved == 2
    # Зупинена форма теж: заявки з неї нікуди не поділись, і їхні картки
    # мусять читатись так само.
    assert MetaLeadForm.query.filter_by(form_id='222').first() is not None


def test_sync_page_forms_tells_refusal_apart_from_empty(app):
    """None -- «не змогли спитати», 0 -- «форм немає». Це різні новини."""
    client = FakeMetaGraphClient()
    client.fail_next()

    assert schema.sync_page_forms(client, '555000111') is None
    assert MetaLeadForm.query.count() == 0


def test_ensure_form_fetches_once_and_not_again(app):
    """Опубліковану форму Meta не редагує -- другий похід був би за тим самим."""
    client = FakeMetaGraphClient(forms=[make_form(FORM_ID)])

    assert schema.ensure_form(client, FORM_ID, page_id='555') is True
    assert schema.ensure_form(client, FORM_ID, page_id='555') is False
    assert [c for c in client.calls if c[0] == 'get_form'] == [('get_form', FORM_ID)]


def test_ensure_form_survives_graph_refusal(app):
    """Відмова Graph API не має ані падати, ані лишати порожній рядок."""
    client = FakeMetaGraphClient(forms=[make_form(FORM_ID)])
    client.fail_next()

    assert schema.ensure_form(client, FORM_ID) is False
    assert MetaLeadForm.query.count() == 0
