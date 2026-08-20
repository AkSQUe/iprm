"""MaterialKit / MaterialKitItem -- стандартний набір матеріалів під курс.

`course_id` навмисно nullable: NULL означає "універсальний комплект",
доступний будь-якому курсу, без окремої таблиці глобальних наборів.

`quantity` має CHECK > 0: рядок комплекту з кількістю нуль -- це позиція,
яку застосування мовчки пропустить, і різницю між "не поклали" і "поклали
нуль" ніхто не побачить.
"""
import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.course import Course
from app.models.material_kit import MaterialKit, MaterialKitItem


def test_kit_without_course_is_universal(db_session):
    """Комплект без course_id зберігається -- це універсальний набір."""
    kit = MaterialKit(name='Базовий набір', course_id=None)
    db_session.add(kit)
    db_session.flush()

    assert kit.id is not None
    assert kit.course_id is None
    assert kit.is_default is False
    assert kit.is_active is True


def test_same_sku_across_different_kits_does_not_conflict(db_session):
    """UNIQUE(kit_id, sku) діє лише в межах ОДНОГО набору."""
    course = Course(title='Плазмотерапія', slug='kit-course-1')
    db_session.add(course)
    db_session.flush()

    kit_a = MaterialKit(name='Набір A', course_id=course.id)
    kit_b = MaterialKit(name='Набір B', course_id=course.id)
    db_session.add_all([kit_a, kit_b])
    db_session.flush()

    kit_a.items.append(MaterialKitItem(sku='NDL-21', quantity=5))
    kit_b.items.append(MaterialKitItem(sku='NDL-21', quantity=3))
    db_session.flush()

    assert kit_a.items[0].id is not None
    assert kit_b.items[0].id is not None


def test_same_sku_twice_in_one_kit_violates_unique(db_session):
    """Той самий sku двічі в ОДНОМУ наборі -- порушення UNIQUE(kit_id, sku)."""
    kit = MaterialKit(name='Набір C')
    db_session.add(kit)
    db_session.flush()

    kit.items.append(MaterialKitItem(sku='NDL-21', quantity=5))
    kit.items.append(MaterialKitItem(sku='NDL-21', quantity=2))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_zero_quantity_is_rejected_by_check_constraint(db_session):
    """quantity = 0 відхиляється CHECK-обмеженням, а не проходить як 'нічого не поклали'."""
    kit = MaterialKit(name='Набір D')
    db_session.add(kit)
    db_session.flush()

    kit.items.append(MaterialKitItem(sku='NDL-21', quantity=0))

    with pytest.raises(IntegrityError):
        db_session.flush()
