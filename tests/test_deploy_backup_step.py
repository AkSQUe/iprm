"""Вартовий над пред-деплойною копією БД у деплой-воркфлоу.

Цінність тут не в наявності кроку, а в його МІСЦІ. Копія, зроблена після
`flask db upgrade`, не варта нічого: вона знімає вже змінену схему, тобто
саме той стан, від якого мала б страхувати. А копія до `pip install` може не
зробитись узагалі -- flask не підніметься, якщо залежності в
requirements.lock змінились.

Порядок кроків -- рівно те, що губиться при ручній правці скрипта, і зовні
це не виглядає поламаним: деплой проходить, копія в списку є, і лише в день
аварії з'ясовується, що повертатись нікуди.
"""
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / '.github' / 'workflows' / 'deploy.yml'


@pytest.fixture(scope='module')
def commands():
    """Лише виконувані рядки воркфлоу, без коментарів.

    Порядок не можна міряти пошуком по сирому тексту: коментар, який ПОЯСНЮЄ
    крок, згадує назву сусідньої команди, і пошук знаходить прозу замість
    команди. Перша версія цього тесту впала саме на цьому -- на власному
    коментарі про `flask db upgrade`.
    """
    text = WORKFLOW.read_text(encoding='utf-8')
    return [
        line.strip() for line in text.splitlines()
        if line.strip() and not line.strip().startswith('#')
    ]


def _position(commands, needle):
    for index, line in enumerate(commands):
        if needle in line:
            return index
    raise AssertionError(f'у воркфлоу немає кроку: {needle}')


def test_deploy_creates_a_backup(commands):
    assert _position(commands, 'flask backup create') >= 0


def test_backup_is_made_before_the_migration(commands):
    """Копія після міграції знімає вже змінену схему -- тобто нічого не страхує."""
    assert _position(commands, 'flask backup create') < \
        _position(commands, 'flask db upgrade')


def test_backup_is_made_after_dependencies_are_installed(commands):
    """Без установлених залежностей flask може не піднятись зовсім."""
    assert _position(commands, 'pip install -r requirements.lock') < \
        _position(commands, 'flask backup create')


def test_backup_is_made_after_postgres_client_is_ensured(commands):
    """Без pg_dump копія неможлива, тож перевірка пакета йде першою."""
    assert _position(commands, 'command -v pg_dump') < \
        _position(commands, 'flask backup create')


def test_commit_is_injected_by_actions_not_read_from_remote_env(commands):
    """Версію коду мусить підставити GitHub Actions у текст скрипта.

    `$GITHUB_SHA` тут не працює: скрипт виконується НА СЕРВЕРІ через
    ssh-action, а це змінна оточення раннера. На сервері вона порожня, тож
    опис копії молча втратив би версію -- і пред-деплойну копію в списку
    стало б не відрізнити від щоденної.
    """
    assert any('github.sha' in line for line in commands), \
        'версія коду мусить приходити через ${{ github.sha }}'
    assert not any('GITHUB_SHA' in line for line in commands), \
        '$GITHUB_SHA на віддаленій машині порожній'


def test_backup_description_carries_the_commit(commands):
    """В описі копії мусить стояти версія коду, інакше в списку копій не
    відрізнити пред-деплойну від щоденної."""
    line = commands[_position(commands, 'flask backup create')]

    assert 'SHA' in line, f'опис без версії коду: {line}'
