"""Крос-сел "Наступний крок": підбір і рендер блоку рекомендацій.

Блок показується на сторінці курсу і на екранах після оплати, тому тести
сторожать саме продуктові правила підбору: не пропонувати вже куплене,
піднімати курси з доступними датами, показувати дату/місця/ціну на картці.

Важливо: фікстура db_session у conftest не ізолює коміти, тож у БД лишаються
курси попередніх тестів. Через це підбір тут прив'язується до унікального
тега (спільний тег ставить потрібний курс над рештою каталогу), а тести
сервісу беруть свідомо великий limit замість дефолтної трійки.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from flask import g, render_template

from app.extensions import db
from app.i18n import source_key
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.instance_tariff import InstanceTariff
from app.models.registration import EventRegistration
from app.models.user import User
from app.services.course_recommend import recommend_courses

# Досить великий, щоб чужі курси в БД не витіснили потрібні з вибірки.
ALL = 500


def _uid():
    return uuid4().hex[:8]


def _course(title, tags=None, price=6000, cpd=12, sort_order=0):
    course = Course(
        slug=f'rec-{_uid()}',
        title=title,
        is_active=True,
        event_type='course',
        short_description='Короткий опис курсу для картки.',
        base_price=price,
        cpd_points=cpd,
        tags=tags or [],
        sort_order=sort_order,
    )
    db.session.add(course)
    db.session.flush()
    return course


def _instance(course, days_ahead=30, seats=10, location='Київ'):
    inst = CourseInstance(
        course_id=course.id,
        status='published',
        event_format='offline',
        location=location,
        price=course.base_price,
        max_participants=seats,
        start_date=datetime.now(timezone.utc) + timedelta(days=days_ahead),
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _tariff(instance, price, name='Базовий'):
    tariff = InstanceTariff(
        instance_id=instance.id, name=name, price=price, is_active=True,
    )
    db.session.add(tariff)
    db.session.flush()
    return tariff


def _render_card(app, course, instance=None, seats=None, lang=None):
    """Партіал картки з мінімальним контекстом (без роутів)."""
    upcoming = {course.id: [instance]} if instance is not None else {}
    seats_map = {} if instance is None or seats is None else {instance.id: seats}
    open_ids = {i for i, left in seats_map.items() if left is None or left > 0}
    with app.test_request_context('/'):
        if lang:
            g.lang_code = lang
        return render_template(
            'partials/_course_recommend_card.html',
            course=course, rec_upcoming=upcoming,
            rec_seats=seats_map, rec_open_ids=open_ids,
        )


def _paid_registration(user, instance):
    reg = EventRegistration(
        user_id=user.id, instance_id=instance.id,
        phone='+380000000000', specialty='Test', workplace='Test',
        status='confirmed', payment_status='paid', payment_amount=6000,
    )
    db.session.add(reg)
    db.session.flush()
    return reg


@pytest.fixture
def user(app):
    u = User.create_with_password(
        f'rec-{_uid()}@test.com', 'password123', first_name='Test', last_name='User',
    )
    db.session.flush()
    return u


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)


def _block(html):
    """HTML самої секції рекомендацій (без решти сторінки).

    Межа -- перший </section> після заголовка: інакше у фрагмент потрапляє
    sticky-CTA з назвою поточного курсу і перевірки на виключення брешуть.
    """
    for marker in ('id="related-title"', 'id="recommend-title"'):
        index = html.find(marker)
        if index != -1:
            end = html.find('</section>', index)
            return html[index:end] if end != -1 else html[index:]
    return ''


class TestSelection:
    def test_excludes_base_course(self, app):
        base = _course('Базовий курс')
        _course('Інший курс')
        db.session.commit()
        courses, *_ = recommend_courses(base_course=base, limit=ALL)
        assert base.id not in {c.id for c in courses}

    def test_courses_with_open_dates_rank_first(self, app):
        # Без дат, але з повним збігом тегів -- має програти курсу з датою.
        tag = f'tag-{_uid()}'
        base = _course('База', tags=[tag])
        dateless = _course('Без дат', tags=[tag], sort_order=1)
        dated = _course('З датами', tags=['інше'], sort_order=2)
        _instance(dated)
        db.session.commit()

        ids = [c.id for c in recommend_courses(base_course=base, limit=ALL)[0]]
        assert ids.index(dated.id) < ids.index(dateless.id)

    def test_shared_tags_rank_first_within_available(self, app):
        tag = f'tag-{_uid()}'
        base = _course('База', tags=[tag, 'ортопедія'])
        unrelated = _course('Без спільних тегів', tags=['інше'], sort_order=1)
        related = _course('Зі спільними тегами', tags=[tag], sort_order=2)
        _instance(unrelated)
        _instance(related)
        db.session.commit()

        ids = [c.id for c in recommend_courses(base_course=base, limit=ALL)[0]]
        assert ids.index(related.id) < ids.index(unrelated.id)

    def test_excludes_courses_user_already_registered_for(self, app, user):
        base = _course('База')
        bought = _course('Вже куплений')
        _paid_registration(user, _instance(bought))
        db.session.commit()

        courses, *_ = recommend_courses(base_course=base, user=user, limit=ALL)
        assert bought.id not in {c.id for c in courses}

    def test_cancelled_registration_does_not_exclude(self, app, user):
        base = _course('База')
        dropped = _course('Скасована реєстрація')
        inst = _instance(dropped)
        db.session.add(EventRegistration(
            user_id=user.id, instance_id=inst.id,
            phone='+380000000000', specialty='Test', workplace='Test',
            status='cancelled', payment_status='unpaid', payment_amount=6000,
        ))
        db.session.commit()

        courses, *_ = recommend_courses(base_course=base, user=user, limit=ALL)
        assert dropped.id in {c.id for c in courses}

    def test_limit_is_respected(self, app):
        base = _course('База')
        for i in range(5):
            _instance(_course(f'Курс {i}', sort_order=i))
        db.session.commit()

        courses, *_ = recommend_courses(base_course=base, limit=3)
        assert len(courses) == 3


class TestCourseDetailBlock:
    def test_card_shows_date_seats_and_price(self, client):
        tag = f'tag-{_uid()}'
        base = _course('База', tags=[tag])
        other = _course('Рекомендований курс', tags=[tag], price=7500)
        _instance(other, days_ahead=45, seats=8)
        db.session.commit()

        block = _block(client.get(f'/courses/{base.slug}').get_data(as_text=True))
        assert 'Рекомендований курс' in block
        assert 'Найближча дата' in block
        assert 'Вільні місця' in block
        assert '8 місць' in block
        assert '7500' in block
        assert 'Короткий опис курсу для картки.' in block

    def test_css_is_linked_when_block_renders(self, client):
        base = _course('База')
        _instance(_course('Рекомендований'))
        db.session.commit()
        html = client.get(f'/courses/{base.slug}').get_data(as_text=True)
        assert 'css/course-recommend.css' in html

    def test_base_course_is_not_recommended_to_itself(self, client):
        base = _course('Унікальна назва курсу ' + _uid())
        _instance(base)
        _instance(_course('Сусідній курс'))
        db.session.commit()

        block = _block(client.get(f'/courses/{base.slug}').get_data(as_text=True))
        assert block
        assert base.title not in block


class TestRecommendCard:
    """Партіал картки окремо -- гілки, які через підбір не відтворити."""

    def test_dateless_course_shows_placeholder(self, app):
        course = _course('Без дат')
        db.session.commit()
        html = _render_card(app, course)
        assert 'Уточнюються' in html
        assert 'Дізнатись більше' in html
        assert '#formats' not in html

    def test_available_course_links_to_formats_section(self, app):
        course = _course('З датами')
        inst = _instance(course)
        _tariff(inst, 6000)
        db.session.commit()
        html = _render_card(app, course, inst, seats=4)
        assert '#formats' in html
        assert 'Обрати дату' in html
        assert '4 місця' in html

    def test_no_formats_anchor_without_active_tariffs(self, app):
        # Секція #formats на сторінці курсу існує лише за наявності активних
        # тарифів -- інакше якір веде в нікуди.
        course = _course('Без тарифів')
        inst = _instance(course)
        db.session.commit()
        html = _render_card(app, course, inst, seats=4)
        assert '#formats' not in html
        assert 'Обрати дату' in html

    def test_free_instance_is_not_shown_with_course_base_price(self, app):
        course = _course('Безкоштовний вебінар', price=4000)
        inst = _instance(course)
        _tariff(inst, 0)
        db.session.commit()
        html = _render_card(app, course, inst, seats=4)
        assert 'Безкоштовно' in html
        assert '4000' not in html

    def test_mixed_free_and_paid_tariffs_are_not_called_free(self, app):
        course = _course('Онлайн безкоштовно, практикум платно', price=4000)
        inst = _instance(course)
        _tariff(inst, 0, name='Онлайн')
        _tariff(inst, 9000, name='Практикум')
        db.session.commit()
        html = _render_card(app, course, inst, seats=4)
        assert 'Безкоштовно' not in html
        assert 'від' in html

    def test_price_is_hidden_when_course_has_no_price_data(self, app):
        course = _course('Без цін', price=0)
        db.session.commit()
        html = _render_card(app, course)
        assert 'iprm-course-card__price' not in html

    def test_tags_use_translated_values(self, app):
        course = _course('З тегами', tags=['плазмотерапія'])
        course.set_translation(
            'ru', 'tags', {source_key('плазмотерапія'): 'плазмотерапия'},
        )
        db.session.commit()
        html = _render_card(app, course, lang='ru')
        assert 'плазмотерапия' in html
        assert 'плазмотерапія' not in html


class TestPaymentSuccessBlock:
    def test_block_renders_after_payment(self, client, user):
        tag = f'tag-{_uid()}'
        bought = _course('Куплений курс', tags=[tag])
        reg = _paid_registration(user, _instance(bought))
        _instance(_course('Наступний курс', tags=[tag], sort_order=1))
        db.session.commit()

        _login(client, user)
        html = client.get(
            f'/payments/success?order_id=REG-{reg.id}',
        ).get_data(as_text=True)
        block = _block(html)
        assert 'Наступний курс' in block
        assert 'css/course-recommend.css' in html
        # Щойно оплачений курс не пропонуємо вдруге.
        assert 'Куплений курс' not in block


class TestRegistrationConfirmationBlock:
    def test_no_cross_sell_while_payment_pending(self, client, user):
        tag = f'tag-{_uid()}'
        target = _course('Курс з оплатою', tags=[tag])
        inst = _instance(target)
        _instance(_course('Сусідній курс', tags=[tag], sort_order=1))
        reg = EventRegistration(
            user_id=user.id, instance_id=inst.id,
            phone='+380000000000', specialty='Test', workplace='Test',
            status='pending', payment_status='unpaid', payment_amount=6000,
        )
        db.session.add(reg)
        db.session.commit()

        _login(client, user)
        html = client.get(f'/registration/{reg.id}').get_data(as_text=True)
        assert 'Сусідній курс' not in html
        assert 'css/course-recommend.css' not in html

    def test_cross_sell_after_payment(self, client, user):
        tag = f'tag-{_uid()}'
        target = _course('Оплачений курс', tags=[tag])
        reg = _paid_registration(user, _instance(target))
        _instance(_course('Сусідній курс', tags=[tag], sort_order=1))
        db.session.commit()

        _login(client, user)
        html = client.get(f'/registration/{reg.id}').get_data(as_text=True)
        assert 'Сусідній курс' in _block(html)
        assert 'css/course-recommend.css' in html
