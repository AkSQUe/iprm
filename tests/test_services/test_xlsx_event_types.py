"""Нормалізація виду заходу при xlsx-імпорті.

Файл може прийти і з внутрішнім кодом ('seminar'), і з українською
назвою з drop-down ('Семінар'). Старі вигрузки несуть застарілі типи --
вони мусять заходити далі, інакше архівні файли перестануть імпортуватись.
"""
import pytest

from app.services import xlsx_io


def test_accepts_internal_code(app):
    assert xlsx_io.normalize_event_type('seminar') == 'seminar'


def test_accepts_ukrainian_label(app):
    assert xlsx_io.normalize_event_type('Наукова конференція') == 'scientific_conference'


def test_accepts_label_with_padding(app):
    assert xlsx_io.normalize_event_type('  Тренінг  ') == 'training'


def test_accepts_deactivated_legacy_type(app):
    assert xlsx_io.normalize_event_type('Курс') == 'course'
    assert xlsx_io.normalize_event_type('webinar') == 'webinar'


def test_rejects_unknown_type_with_helpful_message(app):
    with pytest.raises(ValueError) as err:
        xlsx_io.normalize_event_type('Вечірка')
    assert 'Вечірка' in str(err.value)


def test_dropdown_offers_only_active_types(app):
    options = xlsx_io.event_type_dropdown_options()
    assert 'Наукова конференція' in options
    assert 'Вебінар' not in options, 'застарілий тип не пропонується у новому файлі'
