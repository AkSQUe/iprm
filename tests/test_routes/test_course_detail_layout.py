"""Сторінка курсу: порядок блоків і фінальний CTA.

Порядок еталонний (WS-A, docs/plan-landing-etalon-migration.md, 17.08.2026):
hero -> цифри довіри -> результат -> про курс -> окупність -> для кого ->
галерея -> програма -> тренер -> відгуки -> формат участі -> FAQ -> заявка,
далі одним шматком наше додаткове (дати -> історія -> сертифікат ->
наступний крок -> рефералка -> фінальний CTA).

Замінив порядок, узгоджений 30.07.2026 (про курс -> програма -> тренер ->
формат -> окупність -> дати -> FAQ -> заявка -> CTA).

Тест сторожує саме послідовність, бо вона -- продуктове рішення, а не
випадковий побічний ефект верстки.
"""
import re

from app.extensions import db
from app.models.course import Course
from app.models.program_block import ProgramBlock
from app.models.trainer import Trainer


def _make_course(suffix=''):
    trainer = Trainer(slug=f'layout-trainer{suffix}', full_name='Тренер Тест', role='Лікар')
    db.session.add(trainer)
    db.session.flush()
    course = Course(
        slug=f'layout-course{suffix}',
        title='Курс для перевірки верстки',
        is_active=True,
        description='<p>Опис</p>',
        short_description='Короткий опис',
        target_audience=['Лікарі'],
        cpd_points=12,
        base_price=6000,
        trainer_id=trainer.id,
        faq=[{'question': 'Питання 1?', 'answer': 'Відповідь 1'},
             {'question': 'Питання 2?', 'answer': 'Відповідь 2'}],
    )
    db.session.add(course)
    db.session.flush()
    db.session.add(ProgramBlock(course_id=course.id, heading='Теорія',
                                items=['Пункт А', 'Пункт Б'], sort_order=0))
    db.session.commit()
    return course


# Маркери секцій у порядку, в якому вони мають зустрічатися в HTML.
SECTION_MARKERS = [
    ('про курс', 'id="about"'),
    ('окупність', 'id="roi-title"'),
    ('для кого', 'id="audience-title"'),
    ('програма', 'id="program-title"'),
    ('тренер', 'id="trainer-title"'),
    ('FAQ', 'id="faq-title"'),
    ('форма заявки', 'id="request-title"'),
    # Далі -- «наше додаткове», якого в еталоні немає.
    ('найближчі дати', 'id="schedule-title"'),
    ('фінальний CTA', 'iprm-final-cta__text'),
]


def test_section_order(client):
    course = _make_course()
    resp = client.get(f'/courses/{course.slug}')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    found = []
    for name, marker in SECTION_MARKERS:
        index = html.find(marker)
        assert index != -1, f'секцію "{name}" не знайдено ({marker})'
        found.append((name, index))

    assert found == sorted(found, key=lambda pair: pair[1]), (
        'порядок блоків порушено: '
        + ' -> '.join(n for n, _ in sorted(found, key=lambda pair: pair[1]))
    )


def test_faq_renders_one_details_per_question(client):
    course = _make_course('-faq')
    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    faq_html = html[html.find('id="faq-title"'):html.find('id="request-title"')]
    assert len(re.findall(r'<details class="iprm-faq__item">', faq_html)) == 2


def test_final_cta_falls_back_to_default_sentence(client):
    course = _make_course('-default')
    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    assert 'Готові опанувати метод' in html
    # Дат немає -> кнопка веде на форму запиту.
    tail = html[html.find('iprm-final-cta'):]
    assert 'href="#request"' in tail


def test_final_cta_uses_admin_text(client):
    course = _make_course('-custom')
    course.final_cta_text = 'Одне речення від адміністратора.'
    db.session.commit()
    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    assert 'Одне речення від адміністратора.' in html
    assert 'Готові опанувати метод' not in html
