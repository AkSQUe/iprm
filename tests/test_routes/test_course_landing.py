"""Продажна сторінка курсу: нові секції, галерея, поліморфні блоки.

Сторінка зібрана з партіалів, спільних для очного й онлайн-курсу, тому
перевіряємо обидві: одна регресія в партіалі ламає дві сторінки.

Головний інваріант -- умовність: курс без заповненого контенту не має
показувати порожні рамки. Саме він робить рішення "викочуємо одразу на всі
курси" безпечним.
"""
from decimal import Decimal

from app.extensions import db
from app.models.course import Course
from app.models.media_file import MediaFile
from app.models.online_course import OnlineCourse
from app.models.program_block import ProgramBlock
from app.models.review import Review
from app.models.trainer import Trainer
from app.services import course_service


LANDING_MARKERS = {
    'цифри довіри': 'iprm-trust-stats--band',
    'переваги': 'iprm-benefit-card',
    'аудиторія': 'iprm-audience-grid',
    'галерея': 'iprm-gallery',
    'плашка практики': 'iprm-practice-note',
    'тренер із цифрами': 'iprm-trainer-block--rich',
    'відгуки': 'iprm-dark-shell',
}

LANDING_CONTENT = dict(
    proof_stats=[{'value': '6+', 'label': 'проведених груп'}],
    benefits=[{'title': 'Перевага', 'text': 'Пояснення переваги.'}],
    target_audience=['Дерматологи'],
    practice_note_title='Ви робите руками',
    practice_note_text='Тренер контролює виконання.',
    gallery_intro='Як минає навчальний день',
)


def _trainer(slug, rich=True):
    """Тренер курсу. rich -- із тегами й цифрами (варіант --rich блоку).

    Для "порожнього" курсу тренер навмисно бідний: теги й цифри -- ЙОГО
    дані, а не контент курсу, тож перевірка "порожній курс не показує
    продажних секцій" не має на них спиратись.
    """
    trainer = Trainer(
        slug=slug, full_name='Тренер Тест', role='Лікар',
        skills=['Дерматологія', 'Косметологія'] if rich else [],
        highlights=[{'value': '13 років', 'label': 'у косметології'}] if rich else [],
    )
    db.session.add(trainer)
    db.session.flush()
    return trainer


def _media(index):
    media = MediaFile(
        filename=f'g{index}.webp', file_path=f'2026/08/g{index}.webp',
        mime_type='image/webp',
    )
    db.session.add(media)
    db.session.flush()
    return media


# --------------------------------------------------------------- очний курс

def _course(slug, filled=True):
    trainer = _trainer(f'{slug}-trainer', rich=filled)
    course = Course(
        slug=slug, title='Курс лендингу', is_active=True,
        description='<p>Опис</p>', trainer_id=trainer.id,
        **(LANDING_CONTENT if filled else {}),
    )
    db.session.add(course)
    db.session.flush()
    if filled:
        db.session.add(ProgramBlock(course_id=course.id, heading='Теорія',
                                    items=['Пункт'], sort_order=0))
        db.session.add(Review(author_name='Учасниця', text='Добре', rating=5,
                              is_published=True, course_id=course.id))
        course_service.save_gallery(
            course, [{'media_id': _media(1).id, 'caption': 'Практика'}],
            entity_type='course',
        )
    db.session.commit()
    return course


def test_filled_course_shows_every_landing_section(client):
    course = _course('landing-full')
    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    for name, marker in LANDING_MARKERS.items():
        assert marker in html, f'секції "{name}" немає на сторінці'


def test_empty_course_hides_landing_sections(client):
    """Курс без контенту лишається цілим, а не показує порожні рамки."""
    course = _course('landing-empty', filled=False)
    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    for name, marker in LANDING_MARKERS.items():
        assert marker not in html, f'порожня секція "{name}" протекла на сторінку'
    # Сторінка при цьому робоча: hero і форма заявки лишаються завжди.
    assert 'iprm-hero--landing' in html
    assert 'id="request"' in html


def test_page_nav_lists_only_existing_sections(client):
    empty = _course('landing-nav-empty', filled=False)
    html = client.get(f'/courses/{empty.slug}').get_data(as_text=True)
    nav = html[html.find('iprm-page-nav'):html.find('</nav>')]
    assert 'href="#benefits"' not in nav, 'якір на секцію, якої немає'
    assert 'href="#gallery"' not in nav

    full = _course('landing-nav-full')
    nav_full = client.get(f'/courses/{full.slug}').get_data(as_text=True)
    assert 'href="#benefits"' in nav_full
    assert 'href="#gallery"' in nav_full


def test_course_tags_stay_in_hero(client):
    """Теги -- редакторський контент; переверстка hero колись їх загубила."""
    course = _course('landing-tags', filled=False)
    course.tags = ['Плазмотерапія']
    db.session.commit()
    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    assert 'Плазмотерапія' in html


def test_faq_jsonld_is_emitted(client):
    course = _course('landing-faq', filled=False)
    course.faq = [{'question': 'Кому підійде?', 'answer': 'Лікарям.'}]
    db.session.commit()
    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    assert '"FAQPage"' in html
    assert '"acceptedAnswer"' in html


def test_no_faq_no_faqpage(client):
    course = _course('landing-nofaq', filled=False)
    html = client.get(f'/courses/{course.slug}').get_data(as_text=True)
    assert '"FAQPage"' not in html


# ------------------------------------------------------------ онлайн-курс

def _online(slug, filled=True):
    trainer = _trainer(f'{slug}-trainer', rich=filled)
    course = OnlineCourse(
        sintegrum_id=abs(hash(slug)) % 100000, remote_name='Remote',
        slug=slug, is_published=True, price=Decimal('2500'),
        trainer_id=trainer.id,
        **(LANDING_CONTENT if filled else {}),
    )
    db.session.add(course)
    db.session.flush()
    if filled:
        db.session.add(ProgramBlock(online_course_id=course.id, heading='Модуль',
                                    items=['Тема'], sort_order=0))
        db.session.add(Review(author_name='Учасник', text='Корисно', rating=5,
                              is_published=True, online_course_id=course.id))
        course_service.save_gallery(
            course, [{'media_id': _media(2).id, 'caption': 'Кадр'}],
            entity_type='online_course',
        )
    db.session.commit()
    return course


def test_online_course_shows_same_sections(client):
    """Партіали спільні -- онлайн-сторінка має ті самі секції."""
    course = _online('online-landing-full')
    html = client.get(f'/online-courses/{course.slug}').get_data(as_text=True)
    for name, marker in LANDING_MARKERS.items():
        assert marker in html, f'секції "{name}" немає на онлайн-сторінці'


def test_online_empty_course_hides_sections(client):
    course = _online('online-landing-empty', filled=False)
    html = client.get(f'/online-courses/{course.slug}').get_data(as_text=True)
    for name, marker in LANDING_MARKERS.items():
        assert marker not in html, f'порожня секція "{name}" протекла'
    assert 'iprm-online-buy' in html, 'блок купівлі має бути завжди'


def test_online_gallery_uses_own_media(client):
    """Галереї двох курсів не мають перетікати одна в одну."""
    online = _online('online-gallery')
    offline = _course('offline-gallery')
    assert len(online.gallery) == 1
    assert len(offline.gallery) == 1
    assert online.gallery[0].id != offline.gallery[0].id
