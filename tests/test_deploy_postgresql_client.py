"""Вартовий над встановленням postgresql-client у деплой-воркфлоу.

Без цього пакета на сервері резервне копіювання не працює ВЗАГАЛІ, і зовні
це не виглядає поламаним: сторінка `/admin/backups` відкривається, список
копій просто порожній. Саме так система простояла мертвою з 12.06.2026 по
12.09.2026 -- `pg_dump` викликається через subprocess, тож відсутність
бінарника бачить лише той, хто читає журнал.

Тест читає yaml як текст: груба перевірка, але вона ловить саме те, що
губиться при ручній правці скрипта деплою.
"""
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / '.github' / 'workflows' / 'deploy.yml'


@pytest.fixture(scope='module')
def workflow():
    return WORKFLOW.read_text(encoding='utf-8')


def test_deploy_installs_postgresql_client(workflow):
    assert 'postgresql-client' in workflow


def test_client_version_is_not_older_than_the_server(workflow):
    """Сервер БД -- PostgreSQL 16.11.

    Старший pg_dump відмовляється знімати копію з новішої бази, тому версія
    пакета закріплена явно, а не лишена на відкуп дефолту дистрибутива.
    """
    assert 'postgresql-client-16' in workflow


def test_install_is_skipped_when_binary_is_already_there(workflow):
    """Деплой трапляється на кожен push, а apt-get update -- дорогий.

    Тому встановлення має стояти за перевіркою наявності: на вже налаштованій
    машині крок мусить бути майже безкоштовним, але свіжа машина має
    залікувати себе сама.
    """
    assert 'command -v pg_dump' in workflow
