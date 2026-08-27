import pytest

from app.models.error_log import ErrorLog


@pytest.mark.parametrize('url, expected', [
    # У базі лежить `request.url` цілком -- саме такий вигляд має бойовий запис.
    ('https://iprm.space/uk/courses/plazmohel/register', '/uk/courses/plazmohel/register'),
    ('http://localhost:5000/admin/meta-leads', '/admin/meta-leads'),
    # Хост без шляху: реєстр не має показувати порожню комірку.
    ('https://iprm.space', '/'),
    # Уже відносний шлях (частина записів приходить не з `request.url`).
    ('/static/css/app.css', '/static/css/app.css'),
    ('', ''),
    (None, ''),
])
def test_url_path_strips_scheme_and_host(url, expected):
    """Колонка URL показує шлях: схема й хост однакові в кожному рядку."""
    assert ErrorLog(error_code=500, error_type='X', error_message='m', url=url).url_path == expected


def test_url_path_keeps_query_string():
    """Параметри лишаються: саме вони часто й ламають сторінку."""
    log = ErrorLog(error_code=500, error_type='X', error_message='m',
                   url='https://iprm.space/courses/?page=99&sort=bad')
    assert log.url_path == '/courses/?page=99&sort=bad'
