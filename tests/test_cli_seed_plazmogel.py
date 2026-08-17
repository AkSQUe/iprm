"""Команда `flask seed-plazmogel`: разова заливка контенту з еталона.

Головне, що перевіряємо, -- ідемпотентність. Команда їде на живий прод, де
частину текстів уже могла переписати редакція, тому інваріант такий:
порожнє поле заповнюємо, заповнене лишаємо, і повторний запуск не плодить ні
блоків програми, ні тарифів, ні відгуків.
"""
from datetime import timedelta

import pytest

from app import cli
from app.extensions import db
from app.models.course import Course
from app.models.course_instance import CourseInstance
from app.models.instance_tariff import InstanceTariff
from app.models.media_file import MediaFile
from app.models.mixins import utcnow
from app.models.program_block import ProgramBlock
from app.models.review import Review
from app.models.trainer import Trainer


SLUG_PREFIX = 'seed-pg-'


@pytest.fixture(autouse=True)
def _cleanup_seeded_courses(app):
    """Прибрати за собою після кожного тесту.

    Команда комітить сама, а фікстура сесії відкочує лише незакомічене --
    тобто наші курси лишаються в БД до кінця прогону. Опубліковане
    проведення при цьому потрапляє у видачу партнерського API і збиває
    чужі тести на пагінацію розкладу, тож чистка тут обов'язкова, а не
    гігієнічна.
    """
    yield
    courses = Course.query.filter(Course.slug.like(f'{SLUG_PREFIX}%')).all()
    for course in courses:
        Review.query.filter_by(course_id=course.id).delete(synchronize_session=False)
        MediaFile.query.filter_by(
            entity_type='course', entity_id=course.id,
        ).delete(synchronize_session=False)
        # Проведення, тарифи й блоки програми йдуть каскадом за курсом.
        db.session.delete(course)
    db.session.flush()
    for trainer in Trainer.query.filter(Trainer.slug.like(f'{SLUG_PREFIX}%')).all():
        db.session.delete(trainer)
    db.session.commit()


def _fixture_course(slug, with_gallery=True, with_instance=True):
    """Порожній курс плазмогелю: тренер, проведення, фото без підписів."""
    trainer = Trainer(slug=f'{slug}-trainer', full_name='Тренер Тест')
    db.session.add(trainer)
    db.session.flush()

    course = Course(slug=slug, title='Плазмогель', is_active=True,
                    trainer_id=trainer.id)
    db.session.add(course)
    db.session.flush()

    if with_instance:
        db.session.add(CourseInstance(
            course_id=course.id, status='published',
            start_date=utcnow() + timedelta(days=30),
        ))
    if with_gallery:
        for index in range(1, 7):
            # Прив'язуємо напряму, а не через save_gallery: той перейменовує
            # файли на диску, а тут потрібні лише рядки реєстру.
            db.session.add(MediaFile(
                filename=f'{slug}-{index}.webp',
                file_path=f'2026/08/{slug}-{index}.webp',
                mime_type='image/webp', entity_type='course',
                entity_id=course.id, usage_type='gallery', sort_order=index,
            ))
    db.session.commit()
    return course


def _run(app, slug, *args):
    result = app.test_cli_runner().invoke(
        cli.seed_plazmogel, ['--slug', slug, *args],
    )
    assert result.exit_code == 0, result.output
    return result


def _blocks(course):
    return ProgramBlock.query.filter_by(course_id=course.id).all()


def _tariffs(course):
    instance = course.instances[0]
    return InstanceTariff.query.filter_by(instance_id=instance.id).all()


def _reviews(course):
    return Review.alive().filter_by(course_id=course.id).all()


# ------------------------------------------------------------ перший запуск

def test_seed_fills_empty_course(app):
    course = _fixture_course('seed-pg-empty')
    _run(app, course.slug)

    assert len(course.proof_stats) == 4
    assert len(course.benefits) == 6
    assert len(course.target_audience) == 5
    assert len(course.faq) == 5
    assert course.practice_note_title == cli.PLAZMOGEL_TEXTS['practice_note_title']
    assert course.gallery_intro
    assert course.final_cta_text


def test_seed_creates_program_blocks_and_captions(app):
    course = _fixture_course('seed-pg-program')
    _run(app, course.slug)

    blocks = sorted(_blocks(course), key=lambda b: b.sort_order)
    assert [b.heading for b in blocks] == ['Теоретичний блок', 'Практичний блок']
    assert all(len(b.items) == 6 for b in blocks)
    assert [m.caption for m in course.gallery] == cli.PLAZMOGEL_GALLERY_CAPTIONS


def test_seed_creates_two_tariffs_with_one_flag(app):
    course = _fixture_course('seed-pg-tariffs')
    _run(app, course.slug)

    tariffs = sorted(_tariffs(course), key=lambda t: t.sort_order)
    assert [str(t.price) for t in tariffs] == ['10000.00', '15000.00']
    assert [t.badge for t in tariffs] == [None, 'З підтримкою після курсу']
    assert [t.is_featured for t in tariffs] == [False, True]
    # Пункти-переваги менторського тарифу читаються з "+" на початку рядка.
    assert sum(1 for e in tariffs[1].description_entries if e['is_plus']) == 4


def test_seed_fills_trainer_highlights_and_draft_reviews(app):
    course = _fixture_course('seed-pg-extras')
    _run(app, course.slug)

    assert len(course.trainer.highlights) == 3
    reviews = _reviews(course)
    assert len(reviews) == 3
    # Чернетки: в еталоні плитки без автора й без оцінки, публікує людина.
    assert all(r.is_published is False for r in reviews)


# ------------------------------------------------------- повторний запуск

def test_second_run_adds_nothing(app):
    course = _fixture_course('seed-pg-twice')
    _run(app, course.slug)
    _run(app, course.slug)

    assert len(_blocks(course)) == 2
    assert len(_tariffs(course)) == 2
    assert len(_reviews(course)) == 3
    assert len(course.proof_stats) == 4


def test_human_edit_survives_second_run(app):
    course = _fixture_course('seed-pg-human')
    _run(app, course.slug)

    course.gallery_intro = 'Наш власний лід'
    course.faq = [{'question': 'Своє питання?', 'answer': 'Своя відповідь.'}]
    db.session.commit()

    _run(app, course.slug)
    assert course.gallery_intro == 'Наш власний лід'
    assert len(course.faq) == 1


def test_force_overwrites_edited_fields(app):
    course = _fixture_course('seed-pg-force')
    _run(app, course.slug)

    course.gallery_intro = 'Наш власний лід'
    db.session.commit()

    _run(app, course.slug, '--force')
    assert course.gallery_intro == cli.PLAZMOGEL_TEXTS['gallery_intro']
    # --force не плодить дублікатів: програма лишається двома блоками.
    assert len(_blocks(course)) == 2


# -------------------------------------------------------------- крайні випадки

def test_dry_run_saves_nothing(app):
    course = _fixture_course('seed-pg-dry')
    result = _run(app, course.slug, '--dry-run')

    assert 'DRY RUN' in result.output
    assert not course.proof_stats
    assert _blocks(course) == []


def test_missing_instance_and_gallery_only_skip(app):
    """Тариф належить проведенню, підпис -- фото. Немає носія -- немає й запису.

    Тексти самого курсу при цьому мусять залитись: неповна підготовка курсу
    не повинна блокувати решту контенту.
    """
    course = _fixture_course('seed-pg-noinst', with_gallery=False,
                             with_instance=False)
    result = _run(app, course.slug)

    assert 'немає жодного проведення' in result.output
    assert 'не прив\'язано жодного фото' in result.output
    assert len(course.benefits) == 6


def test_unknown_slug_fails_loudly(app):
    result = app.test_cli_runner().invoke(
        cli.seed_plazmogel, ['--slug', 'no-such-course'],
    )
    assert result.exit_code == 1
    assert 'не знайдено' in result.output
