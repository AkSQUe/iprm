"""Нижня липка кнопка «Реєстрація» на сторінці курсу.

Раніше вона вела на якір #schedule -- людина, що вже дочитала до низу й
натиснула «Реєстрація», стрибала назад угору до переліку дат і мусила
обирати вдруге. Тепер кнопка робить вибір за неї: одна відкрита дата --
одразу на форму реєстрації цього проведення; кілька -- модалка з тими
самими картками дат, що й у колонці розкладу; жодної -- запит на
проведення, як і було.
"""
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance


def _course():
    course = Course(
        title=f'Курс {uuid4().hex[:4]}', slug=f'cta-{uuid4().hex[:6]}',
        is_active=True, event_type='course', base_price=5000,
    )
    db.session.add(course)
    db.session.flush()
    return course


def _instance(course, days_ahead):
    inst = CourseInstance(
        course_id=course.id, status='published', event_format='offline',
        location='Київ', price=course.base_price, max_participants=10,
        start_date=datetime.now(timezone.utc) + timedelta(days=days_ahead),
    )
    db.session.add(inst)
    db.session.flush()
    return inst


def _sticky(html):
    """Блок кнопок липкої панелі: усередині лише <a>/<button>, тож перший
    </div> і є його кінець."""
    block = re.search(r'<div class="iprm-sticky-cta__actions">.*?</div>', html, re.S)
    assert block, 'на сторінці немає липкої панелі'
    return block.group(0)


def _page(client, course):
    db.session.commit()
    resp = client.get(f'/courses/{course.slug}')
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def test_single_open_date_links_straight_to_registration(client):
    course = _course()
    inst = _instance(course, 30)
    html = _page(client, course)
    sticky = _sticky(html)
    assert f'/registration/instance/{inst.id}/register' in sticky
    assert 'data-modal-open' not in sticky
    assert 'id="course-date-modal"' not in html
    assert 'js/modal.js' not in html


def test_several_open_dates_open_choice_modal(client):
    course = _course()
    first = _instance(course, 30)
    second = _instance(course, 60)
    html = _page(client, course)
    sticky = _sticky(html)
    assert 'data-modal-open="course-date-modal"' in sticky
    assert '/registration/instance/' not in sticky

    modal = re.search(r'<div class="modal[^"]*" id="course-date-modal".*?</div>\s*</div>\s*</div>',
                      html, re.S)
    assert modal, 'модалки вибору дати немає'
    for inst in (first, second):
        assert f'/registration/instance/{inst.id}/register' in modal.group(0)
    assert 'css/modal.css' in html
    assert 'js/modal.js' in html


def test_no_open_dates_keeps_request_anchor(client):
    course = _course()
    html = _page(client, course)
    sticky = _sticky(html)
    assert 'href="#request"' in sticky
    assert 'data-modal-open' not in sticky
    assert 'id="course-date-modal"' not in html
