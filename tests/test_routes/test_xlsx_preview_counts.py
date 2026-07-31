"""Регресія: лічильники в прев'ю імпорту не мають натикатись на методи dict.

`{{ c.update }}` у Jinja резолвиться в dict.update (метод), а не в ключ
'update': атрибут має пріоритет над елементом. Плитка "Оновити" показувала
репр методу, а кнопка "Підтвердити імпорт" з'являлась завжди, бо метод
істинний. Обидва шаблони прев'ю мають читати лічильники індексом.
"""
import re
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parents[2] / 'app' / 'templates' / 'admin'
PREVIEWS = ['xlsx_preview.html', 'xlsx_translations_preview.html']

# Ключі лічильників, які збігаються з методами dict.
SHADOWED = ('update', 'get', 'items', 'keys', 'values', 'copy', 'clear', 'pop')


@pytest.mark.parametrize('name', PREVIEWS)
def test_counts_are_read_by_index(name):
    text = (TEMPLATES / name).read_text(encoding='utf-8')
    for key in SHADOWED:
        assert not re.search(rf'\bc\.{key}\b', text), (
            f'{name}: c.{key} резолвиться в метод dict, а не в лічильник — '
            f"використайте c['{key}']"
        )


@pytest.mark.parametrize('name', PREVIEWS)
def test_counts_variable_is_defined(name):
    text = (TEMPLATES / name).read_text(encoding='utf-8')
    assert 'set c = plan.counts' in text


def test_jinja_attribute_lookup_really_shadows_dict_keys():
    """Фіксуємо причину, а не лише наслідок."""
    from jinja2 import Environment
    env = Environment()
    rendered = env.from_string('{{ c.update }}').render(c={'update': 5})
    assert 'built-in method' in rendered
    assert env.from_string("{{ c['update'] }}").render(c={'update': 5}) == '5'
