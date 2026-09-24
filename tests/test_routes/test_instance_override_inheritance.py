"""Блок «Override default-значень курсу»: форма мусить називати успадковане.

Порожнє поле в цьому блоці -- не «нічого», а рішення «як у курсу». Доти,
доки форма не каже, ЩО саме буде взято, це рішення ухвалюють наосліп: у
полях балів раніше стояли зразки («7,5», «9»), схожі на справжні значення,
а прев'ю тренерів запевняло, що без вибору захід лишиться без спікерів --
хоча насправді він успадковує склад курсу.

Тести тримають саме цю властивість: підказка = поточне значення курсу.
"""
from decimal import Decimal
from uuid import uuid4

import pytest

from tests.support.rbac import grant_role

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.trainer import Trainer
from app.models.user import User
from app.services import trainer_links


@pytest.fixture
def admin():
    user = User.create_with_password(
        f'ovr-{uuid4().hex[:6]}@test.com', 'password123',
        first_name='O', last_name='V', email_confirmed=True,
    )
    grant_role(user, 'super_admin')
    db.session.commit()
    yield user
    # Прибираємо за собою: інакше валиться test_api_v1_clients.
    db.session.delete(user)
    db.session.commit()


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)


def _course(**kwargs):
    course = Course(title=f'Курс {uuid4().hex[:4]}', slug=uuid4().hex[:8], **kwargs)
    db.session.add(course)
    db.session.commit()
    return course


def _instance(course, **kwargs):
    kwargs.setdefault('status', 'draft')
    kwargs.setdefault('event_format', 'offline')
    inst = CourseInstance(course_id=course.id, **kwargs)
    db.session.add(inst)
    db.session.commit()
    return inst


def _trainer(name):
    trainer = Trainer(full_name=name, slug=uuid4().hex[:8], is_active=True)
    db.session.add(trainer)
    db.session.commit()
    return trainer


def _form(client, instance):
    response = client.get(f'/admin/instances/{instance.id}/edit')
    assert response.status_code == 200
    return response.get_data(as_text=True)


class TestNumbersNameTheInheritedValue:
    def test_points_placeholders_are_the_courses_own_numbers(self, client, admin):
        course = _course(cpd_points_online=Decimal('4.5'),
                         cpd_points_offline=Decimal('7'))
        instance = _instance(course)
        _login(client, admin)

        html = _form(client, instance)

        assert 'placeholder="4,5"' in html
        assert 'placeholder="7"' in html

    def test_no_placeholder_when_the_course_has_no_value(self, client, admin):
        """Порожньо в курсі -- порожньо й у підказці.

        Зразок на кшталт «7,5» тут гірший за відсутність підказки: він
        виглядає як успадковане значення, якого насправді немає.
        """
        instance = _instance(_course())
        _login(client, admin)

        html = _form(client, instance)

        assert 'placeholder="7,5"' not in html
        assert 'placeholder="9"' not in html

    def test_price_and_capacity_also_name_the_course(self, client, admin):
        course = _course(base_price=Decimal('3200'), max_participants=12)
        instance = _instance(course)
        _login(client, admin)

        html = _form(client, instance)

        assert 'placeholder="12"' in html
        assert 'id="max_participants"' in html


class TestTrainersPreviewTellsTheTruth:
    def test_empty_field_offers_the_courses_lineup(self, client, admin):
        """Порожній перелік проведення -- це успадкування, і прев'ю мусить
        назвати саме тих, кого буде успадковано."""
        course = _course()
        first, second = _trainer('Андрієнко А.'), _trainer('Богданенко Б.')
        trainer_links.set_trainers(course, [first.id, second.id])
        db.session.commit()
        instance = _instance(course)
        _login(client, admin)

        html = _form(client, instance)

        assert f"data-speakers-inherited='[{first.id}, {second.id}]'" in html
        assert 'Скопіювати тренерів з курсу' in html

    def test_lineup_order_survives_into_the_preview(self, client, admin):
        """Порядок = ролі: перший успадкований і є головним лектором."""
        course = _course()
        first, second = _trainer('Яценко Я.'), _trainer('Андрієнко А.')
        trainer_links.set_trainers(course, [first.id, second.id])
        db.session.commit()
        instance = _instance(course)
        _login(client, admin)

        html = _form(client, instance)

        assert f"data-speakers-inherited='[{first.id}, {second.id}]'" in html

    def test_no_copy_button_when_there_is_nothing_to_copy(self, client, admin):
        instance = _instance(_course())
        _login(client, admin)

        html = _form(client, instance)

        assert "data-speakers-inherited='[]'" in html
        assert 'Скопіювати тренерів з курсу' not in html

    def test_the_old_lie_about_the_speakers_block_is_gone(self, client, admin):
        """Текст був скопійований із форми КУРСУ, де він правдивий.

        У проведенні він хибний двічі: порожнє поле означає успадкування, а
        сам блок спікерів збирається на сторінці курсу з course.trainers і
        від переліку проведення не залежить узагалі.
        """
        instance = _instance(_course())
        _login(client, admin)

        html = _form(client, instance)

        assert 'блок спікерів на сторінці заходу не зʼявиться' not in html

    def test_card_url_comes_from_the_router(self, client, admin):
        """Шлях до card.json не має жити в шаблоні окремим рядком."""
        instance = _instance(_course())
        _login(client, admin)

        html = _form(client, instance)

        assert '/admin/trainers/__ID__/card.json' in html


class TestDeactivatedTrainerIsMarked:
    def test_linked_but_inactive_trainer_says_so_and_leaves_the_dropdown(
        self, client, admin,
    ):
        course = _course()
        instance = _instance(course)
        trainer = _trainer('Зниклий З.')
        trainer_links.set_trainers(instance, [trainer.id])
        trainer.is_active = False
        db.session.commit()
        _login(client, admin)

        html = _form(client, instance)

        assert 'Зниклий З. — неактивний' in html
        assert 'data-inactive' in html
