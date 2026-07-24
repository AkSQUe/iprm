"""TranslatableMixin: t() для рядків і JSON, фолбек, set_translation,
стійкість JSON-перекладів до зміни оригіналу."""
import pytest
from flask_babel import force_locale

from app.extensions import db
from app.i18n import apply_json_overrides
from app.models.course import Course


def _course(**kw):
    c = Course(title='Плазмотерапія', slug=kw.pop('slug', 'c-tr'), **kw)
    db.session.add(c)
    db.session.flush()
    return c


def test_t_returns_uk_by_default():
    c = _course()
    assert c.t('title') == 'Плазмотерапія'


def test_t_returns_translation_for_lang():
    c = _course()
    c.set_translation('en', 'title', 'Plasma Therapy')
    assert c.t('title', lang='en') == 'Plasma Therapy'


def test_t_falls_back_to_uk_when_missing():
    c = _course()
    c.set_translation('en', 'title', 'Plasma Therapy')
    assert c.t('title', lang='ru') == 'Плазмотерапія'
    assert c.t('subtitle', lang='en') is None


def test_t_uses_active_locale():
    c = _course()
    c.set_translation('ru', 'title', 'Плазмотерапия')
    with force_locale('ru'):
        assert c.t('title') == 'Плазмотерапия'
    with force_locale('uk'):
        assert c.t('title') == 'Плазмотерапія'


def test_set_translation_rejects_uk():
    c = _course()
    with pytest.raises(ValueError):
        c.set_translation('uk', 'title', 'x')


def test_set_translation_rejects_non_translatable_field():
    c = _course()
    with pytest.raises(ValueError):
        c.set_translation('en', 'slug', 'x')


def test_set_translation_empty_removes():
    c = _course()
    c.set_translation('en', 'title', 'Plasma')
    c.set_translation('en', 'title', '')
    assert 'title' not in (c.translations.get('en') or {})


def test_json_field_override_reconstruction():
    c = _course(faq=[{'q': 'Питання?', 'a': 'Відповідь.'}])
    c.set_translation('en', 'faq', {'0.q': 'Question?', '0.a': 'Answer.'})
    en = c.t('faq', lang='en')
    assert en == [{'q': 'Question?', 'a': 'Answer.'}]
    # оригінал не мутовано
    assert c.faq == [{'q': 'Питання?', 'a': 'Відповідь.'}]


def test_json_partial_override_falls_back_per_leaf():
    c = _course(faq=[{'q': 'Питання?', 'a': 'Відповідь.'}])
    c.set_translation('en', 'faq', {'0.q': 'Question?'})
    en = c.t('faq', lang='en')
    assert en[0]['q'] == 'Question?'
    assert en[0]['a'] == 'Відповідь.'  # неперекладений листок -> укр


def test_json_structure_change_is_resilient():
    c = _course(faq=[{'q': 'A?', 'a': 'A.'}, {'q': 'B?', 'a': 'B.'}])
    c.set_translation('en', 'faq', {'0.q': 'A-en?', '1.q': 'B-en?'})
    # оригінал змінюється: видаляємо перший блок, додаємо новий
    c.faq = [{'q': 'B?', 'a': 'B.'}, {'q': 'C?', 'a': 'C.'}]
    en = c.t('faq', lang='en')
    assert len(en) == 2  # структура за поточним uk
    # шлях '1.q' усе ще існує -> override застосовано; нові листки -> укр
    assert en[1]['q'] == 'B-en?'


def test_apply_json_overrides_skips_missing_and_nonstring_paths():
    base = [{'data': {'html': 'текст', 'level': 2}}]
    out = apply_json_overrides(base, {
        '0.data.html': 'text',
        '0.data.level': 'НЕ ПОВИННО',   # level -- int, не рядок -> пропуск
        '9.data.html': 'НЕ ІСНУЄ',       # шлях відсутній -> пропуск
    })
    assert out[0]['data']['html'] == 'text'
    assert out[0]['data']['level'] == 2


def test_translations_persist_roundtrip():
    c = _course(slug='c-persist')
    c.set_translation('ru', 'title', 'Плазмотерапия')
    db.session.commit()
    fetched = db.session.get(Course, c.id)
    assert fetched.t('title', lang='ru') == 'Плазмотерапия'
