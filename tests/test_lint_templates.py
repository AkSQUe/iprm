"""Лінт шаблонів: як шаблони звуть сутності.

Застосунок тут не піднімається -- це перевірка тексту репозиторію, а не
поведінки роуту, тому вона й лежить окремо від тестів сторінок.
"""


def test_no_template_names_an_instance_by_its_course_title():
    """Сторож проти напівпройденої заміни.

    Назва проведення береться з `effective_title`. Звертання виду
    `<проведення>.course.title` у шаблоні означає, що це місце заміну
    проґавило -- і сторінка зве захід назвою курсу, поки сусідня зве темою.
    Саме так уже сталося з каталогом `/courses`: перший прохід шукав
    `.course.title` і не побачив перекладної форми `.course.t('title')`.
    """
    import re
    from pathlib import Path

    # Єдиний виняток -- картка проведення: там курс названий НАВМИСНО, як
    # батько теми (підпис "курс: ..." і плейсхолдер поля). Її поведінку
    # тримає TestCard.test_card_subtitle_shows_topic_and_course.
    ALLOWED = {'app/templates/admin/instance_edit.html'}

    templates = Path('app/templates')
    pattern = re.compile(r"\b(inst|instance)\w*\.course\.(title|t\('title'\))")
    offenders = []
    for path in templates.rglob('*.html'):
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if pattern.search(line) and path.as_posix() not in ALLOWED:
                offenders.append(f'{path.as_posix()}:{number}')
    assert not offenders, 'проведення назване назвою курсу: ' + ', '.join(offenders)
