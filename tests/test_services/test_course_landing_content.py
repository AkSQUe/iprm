"""Парсери контенту продажної сторінки та синхронізація галереї.

Формати введення спільні для форм очного й онлайн-курсу, тому помилка тут
однаково б'є по обох редакторах.
"""
from app.extensions import db
from app.models.course import Course
from app.models.media_file import MediaFile
from app.services import course_service as cs


# ----------------------------------------------------------------- пари

def test_pairs_split_value_and_label():
    assert cs.pairs_text_to_list('6+ | проведених груп') == [
        {'value': '6+', 'label': 'проведених груп'},
    ]


def test_pairs_keep_dashes_inside_value():
    """Роздільник -- саме "|": дефіси трапляються всередині значень."""
    assert cs.pairs_text_to_list('13-15 років | у практиці')[0]['value'] == '13-15 років'


def test_pairs_line_without_separator_keeps_value():
    """Краще показати саму цифру, ніж мовчки викинути введене."""
    assert cs.pairs_text_to_list('100%') == [{'value': '100%', 'label': ''}]


def test_pairs_roundtrip():
    text = '6+ | груп\n100% | практика'
    assert cs.pairs_list_to_text(cs.pairs_text_to_list(text)) == text


def test_pairs_ignore_blank_lines():
    assert len(cs.pairs_text_to_list('a | b\n\n  \nc | d')) == 2


# --------------------------------------------------------------- блоки

def test_blocks_first_line_is_head():
    result = cs.blocks_text_to_list('Заголовок\nТекст рядок один\nдва',
                                    'title', 'text')
    assert result == [{'title': 'Заголовок', 'text': 'Текст рядок один\nдва'}]


def test_blocks_split_on_blank_line():
    assert len(cs.blocks_text_to_list('А\nтекст\n\nБ\nтекст', 'title', 'text')) == 2


def test_blocks_normalize_crlf():
    """Браузер шле textarea з CRLF -- без нормалізації все стало б одним блоком."""
    assert len(cs.blocks_text_to_list('А\r\nтекст\r\n\r\nБ\r\nтекст',
                                      'title', 'text')) == 2


def test_faq_helpers_reuse_block_parser():
    assert cs.faq_text_to_list('Питання?\nВідповідь.') == [
        {'question': 'Питання?', 'answer': 'Відповідь.'},
    ]


# -------------------------------------------------------------- галерея

def _media(app_ctx=None):
    media = MediaFile(filename='x.webp', file_path='2026/08/x.webp',
                      mime_type='image/webp')
    db.session.add(media)
    db.session.flush()
    return media


def test_parse_gallery_ignores_broken_json(app):
    """Зіпсоване приховане поле не має валити збереження курсу."""
    assert cs.parse_gallery_entries('{зламано') == []
    assert cs.parse_gallery_entries('') == []
    assert cs.parse_gallery_entries('{"not": "a list"}') == []


def test_parse_gallery_skips_entries_without_media_id(app):
    raw = '[{"caption": "без id"}, {"media_id": "7", "caption": "ок"}]'
    assert cs.parse_gallery_entries(raw) == [{'media_id': 7, 'caption': 'ок'}]


def test_save_gallery_sets_order_and_caption(app):
    course = Course(slug='g1', title='K', is_active=True)
    db.session.add(course)
    first, second = _media(), _media()
    db.session.commit()

    cs.save_gallery(course, [
        {'media_id': second.id, 'caption': 'Друге'},
        {'media_id': first.id, 'caption': 'Перше'},
    ], entity_type='course')
    db.session.commit()

    assert [(m.id, m.sort_order, m.caption) for m in course.gallery] == [
        (second.id, 1, 'Друге'), (first.id, 2, 'Перше'),
    ]


def test_removed_photo_is_detached_not_deleted(app):
    """Файл міг використовуватись деінде -- видалення це окрема дія."""
    course = Course(slug='g2', title='K', is_active=True)
    db.session.add(course)
    media = _media()
    db.session.commit()

    cs.save_gallery(course, [{'media_id': media.id, 'caption': None}],
                    entity_type='course')
    db.session.commit()
    cs.save_gallery(course, [], entity_type='course')
    db.session.commit()

    assert course.gallery == []
    survivor = db.session.get(MediaFile, media.id)
    assert survivor is not None
    assert survivor.entity_type is None
    assert survivor.usage_type == 'main'
