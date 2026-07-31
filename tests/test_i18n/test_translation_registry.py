"""Реєстр перекладних одиниць: розбір сутності на одиниці, запис, покриття."""
from uuid import uuid4

from app.extensions import db
from app.i18n import source_key
from app.models.course import Course
from app.services import translation_registry as registry


def _course(**kw):
    c = Course(title='Курс', slug=f'c-{uuid4().hex[:6]}', **kw)
    db.session.add(c)
    db.session.flush()
    return c


def test_scalar_and_json_units():
    c = _course(subtitle='Підзаголовок',
                faq=[{'question': 'Питання?', 'answer': 'Відповідь.'}])
    units = {u.uid: u for u in registry.units(c)}

    assert 'title' in units
    assert units['title'].source == 'Курс'
    assert units['title'].src_key is None

    q_uid = f'faq:{source_key("Питання?")}'
    assert q_uid in units
    assert units[q_uid].is_json_leaf
    assert units[q_uid].label == 'FAQ'


def test_duplicate_sources_collapse_into_one_unit():
    """Однаковий текст у двох місцях -- одна одиниця: ключ у них спільний."""
    c = _course(faq=[{'question': 'Те саме?', 'answer': 'A'},
                     {'question': 'Те саме?', 'answer': 'B'}])
    faq_units = [u for u in registry.units(c) if u.field == 'faq']
    assert sum(1 for u in faq_units if u.source == 'Те саме?') == 1


def test_apply_units_writes_scalar_and_json():
    c = _course(faq=[{'question': 'Питання?', 'answer': 'Відповідь.'}])
    key = source_key('Питання?')
    registry.apply_units(c, 'ru', {
        'title': 'Курс-РУ',
        f'faq:{key}': 'Вопрос?',
    })
    assert c.translations['ru']['title'] == 'Курс-РУ'
    assert c.translations['ru']['faq'] == {key: 'Вопрос?'}
    assert c.t('faq', lang='ru')[0]['question'] == 'Вопрос?'


def test_apply_units_leaves_absent_fields_untouched():
    c = _course(subtitle='Підзаголовок')
    registry.apply_units(c, 'ru', {'title': 'Курс-РУ'})
    registry.apply_units(c, 'ru', {'subtitle': 'Подзаголовок'})
    assert c.translations['ru']['title'] == 'Курс-РУ'
    assert c.translations['ru']['subtitle'] == 'Подзаголовок'


def test_apply_units_empty_value_removes_translation():
    c = _course()
    registry.apply_units(c, 'ru', {'title': 'Курс-РУ'})
    registry.apply_units(c, 'ru', {'title': ''})
    assert 'title' not in (c.translations.get('ru') or {})


def test_apply_units_skips_translation_equal_to_source():
    """Переклад, дослівно рівний оригіналу, не зберігаємо -- фолбек дасть те саме."""
    c = _course(faq=[{'question': 'PRP?', 'answer': 'Так.'}])
    registry.apply_units(c, 'ru', {f'faq:{source_key("PRP?")}': 'PRP?'})
    assert (c.translations.get('ru') or {}).get('faq') is None


def test_coverage_counts_units_not_fields():
    c = _course(faq=[{'question': 'Q1?', 'answer': 'A1'},
                     {'question': 'Q2?', 'answer': 'A2'}])
    total_units = len(registry.units(c))
    registry.apply_units(c, 'ru', {f'faq:{source_key("Q1?")}': 'В1?'})

    done, total = registry.coverage(c)['ru']
    assert total == total_units
    # Раніше поле faq цілком рахувалось виконаним після одного перекладу.
    assert done == 1
    assert registry.coverage(c)['en'] == (0, total_units)


def test_coverage_label_format():
    c = _course()
    label = registry.coverage_label(c)
    assert label.startswith('ru 0/') and 'en 0/' in label
