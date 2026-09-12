"""Вартовий над довжиною ідентифікаторів alembic-ревізій.

Колонка `alembic_version.version_num` -- `character varying(32)`. Ревізія з
довшим id проходить усі локальні перевірки (файл валідний, ланцюг цілий,
`flask db heads` показує одну голову), а `flask db upgrade` падає на самому
кінці -- на UPDATE службової таблиці:

    ProgrammingError: значення задовге для типу character varying(32)
    [SQL: UPDATE alembic_version SET version_num='...']

Міграція при цьому відкочується, база лишається на попередній ревізії, і на
проді це виглядає як зламаний деплой без жодного натяку на причину. Цей
тест ловить таке ще в репозиторії.

Точна межа -- не наша вигадка: це дефолт alembic для version_num, і вона ж
стоїть у наших базах.
"""
import re
from pathlib import Path

import pytest

VERSIONS_DIR = Path(__file__).resolve().parents[2] / 'migrations' / 'versions'
MAX_LENGTH = 32

_REVISION_RE = re.compile(r"^revision\s*=\s*['\"]([^'\"]+)['\"]", re.MULTILINE)


def _revision_files():
    return sorted(VERSIONS_DIR.glob('*.py'))


def test_versions_directory_is_found():
    assert _revision_files(), 'каталог ревізій порожній -- тест дивиться не туди'


@pytest.mark.parametrize('path', _revision_files(), ids=lambda p: p.stem)
def test_revision_id_fits_the_version_column(path):
    match = _REVISION_RE.search(path.read_text(encoding='utf-8'))
    assert match, f'{path.name}: не знайдено рядка revision = "..."'

    revision_id = match.group(1)
    assert len(revision_id) <= MAX_LENGTH, (
        f'{path.name}: id ревізії "{revision_id}" має {len(revision_id)} '
        f'символів, а влазить {MAX_LENGTH}. `flask db upgrade` впаде на '
        f'UPDATE alembic_version -- перейменуйте ревізію коротше.'
    )
