"""Пікінг-лист живе в тій самій оболонці, що решта адмінки.

Сторінка будувала власну (.admin-layout поверх base.html) і лишалась єдиною
з дев'яноста, де сайдбара немає: адмін, що прийшов сюди з матеріалів заходу,
втрачав навігацію й міг повернутись лише кнопкою «назад». Та сама вада, що
свого часу була на сторінці резервних копій, -- тому й сторож такий самий.
"""
from datetime import date

import pytest

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.material_reservation import (
    MaterialReservation, MaterialReservationItem,
)
from tests.support.rbac import make_super_admin


@pytest.fixture
def admin_client(client):
    user = make_super_admin()
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
    return client


@pytest.fixture
def reservation():
    course = Course(title='Базовий курс плазмотерапії', slug='course-picking-shell')
    db.session.add(course)
    db.session.flush()
    inst = CourseInstance(course_id=course.id, location='Київ',
                          start_date=date(2026, 10, 14))
    db.session.add(inst)
    db.session.flush()
    res = MaterialReservation(instance_id=inst.id,
                              external_ref='iprm-instance-picking-shell',
                              status='issued')
    res.items.append(MaterialReservationItem(sku='NDL-21G', name='Голка 21G',
                                             quantity_reserved=40))
    db.session.add(res)
    db.session.commit()
    return res


def test_picking_list_keeps_the_admin_shell(admin_client, reservation):
    html = admin_client.get(
        '/admin/instances/%d/materials/picking-list' % reservation.instance_id,
    ).get_data(as_text=True)

    assert 'admin-with-sidebar' in html
    assert 'admin-sidebar' in html


def test_controls_are_marked_as_not_for_print(admin_client, reservation):
    """Сайдбар ховає спільне правило друку, крихти й кнопку -- .picking-noprint.

    Без цього роздруківка починається смугою піктограм уздовж лівого краю
    аркуша, по якій нікуди не клацнути.
    """
    html = admin_client.get(
        '/admin/instances/%d/materials/picking-list' % reservation.instance_id,
    ).get_data(as_text=True)

    assert 'picking-noprint' in html
