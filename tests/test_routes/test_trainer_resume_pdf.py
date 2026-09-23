"""PDF-резюме тренерів."""
from html.parser import HTMLParser

import pytest

from app.extensions import db
from tests.support.rbac import make_super_admin, make_user_with_role, switch_user
from tests.test_trainer_cabinet._factories import make_course, make_instance, make_trainer


def _weasyprint_available():
    try:
        import weasyprint  # noqa: F401
    except Exception:
        return False
    return True


# Тест «відповідь починається з %PDF» має сенс лише при справжньому рендері
# (як у test_offer_pdf.py) -- на машині без GTK WeasyPrint не імпортується.
requires_weasyprint = pytest.mark.skipif(
    not _weasyprint_available(), reason='WeasyPrint недоступний (немає GTK)')


def _admin(client):
    admin = make_super_admin(email='tc-resume-admin@test.com')
    db.session.commit()
    switch_user(client, admin)
    return admin


class _DialogParser(HTMLParser):
    """Розбирає ЛИШЕ форму з action на trainers_resume_pdf.

    Регулярка на розмітку діалогу була б крихкою при найменшій зміні
    відступів чи атрибутів -- html.parser бачить структуру, а не текст.
    Форми в самій сторінці не вкладені одна в одну, тож простого прапорця
    «зараз усередині потрібної форми» достатньо.
    """

    def __init__(self):
        super().__init__()
        self.in_form = False
        self.has_csrf = False
        self.columns = []  # [(value, checked)]
        self.labels = {}
        self._label_for = None
        self._label_text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.in_form = (attrs.get('action') or '').endswith('/trainers/resume.pdf')
            return
        if not self.in_form:
            return
        if tag == 'input':
            name = attrs.get('name')
            if name == 'csrf_token':
                self.has_csrf = True
            elif name == 'columns':
                self.columns.append((attrs.get('value'), 'checked' in attrs))
        elif tag == 'label' and attrs.get('for'):
            self._label_for = attrs['for']
            self._label_text = []

    def handle_data(self, data):
        if self._label_for is not None:
            self._label_text.append(data)

    def handle_endtag(self, tag):
        if tag == 'label' and self._label_for is not None:
            self.labels[self._label_for] = ''.join(self._label_text).strip()
            self._label_for = None
        elif tag == 'form':
            self.in_form = False


def _parse_dialog(html_bytes):
    parser = _DialogParser()
    parser.feed(html_bytes.decode('utf-8'))
    return parser


@requires_weasyprint
def test_export_returns_pdf(client):
    _admin(client)
    trainer = make_trainer(name='Експортний Т.')
    db.session.commit()
    resp = client.post('/admin/trainers/resume.pdf', data={
        'ids': [str(trainer.id)],
        'columns': ['full_name', 'workplace'],
    })
    assert resp.status_code == 200
    assert resp.mimetype == 'application/pdf'
    assert resp.data[:4] == b'%PDF'
    assert resp.headers['Cache-Control'] == 'no-store, private'


def test_export_without_ids_redirects(client):
    _admin(client)
    resp = client.post('/admin/trainers/resume.pdf', data={'ids': []})
    assert resp.status_code == 302


def test_export_requires_permission(client):
    from tests.test_trainer_cabinet._factories import login, make_user

    login(client, make_user())
    resp = client.post('/admin/trainers/resume.pdf', data={'ids': ['1']})
    assert resp.status_code in (302, 403, 404)


@requires_weasyprint
def test_unknown_column_is_ignored(client):
    _admin(client)
    trainer = make_trainer(name='Колонковий Т.')
    db.session.commit()
    resp = client.post('/admin/trainers/resume.pdf', data={
        'ids': [str(trainer.id)],
        'columns': ['full_name', 'fop_iban'],
    })
    assert resp.status_code == 200
    assert resp.data[:4] == b'%PDF'


@requires_weasyprint
def test_rows_follow_request_order_not_db_order(client):
    """Порядок рядків -- як у запиті, а не як віддала БД.

    Без сортування за id тренер, доданий пізніше, лежав би в БД раніше за
    того, що з меншим id, і документ мовчки переставляв би рядки місцями
    щодо порядку, в якому адмін обирав тренерів у поданні заходу.
    """
    _admin(client)
    first = make_trainer(name='Перший Т.')
    second = make_trainer(name='Другий Т.')
    db.session.commit()

    from app.services import trainer_resume_service as rs
    calls = []
    original = rs.build_rows

    def spy(trainers, keys):
        calls.append([t.id for t in trainers])
        return original(trainers, keys)

    rs.build_rows = spy
    try:
        resp = client.post('/admin/trainers/resume.pdf', data={
            'ids': [str(second.id), str(first.id)],
            'columns': ['full_name'],
        })
    finally:
        rs.build_rows = original

    assert resp.status_code == 200
    assert calls == [[second.id, first.id]]


def test_dialog_labels_match_pdf_headers(app):
    """Підписи діалогу й шапка PDF беруться з одного реєстру."""
    from app.services import trainer_resume_service as rs

    keys = ['full_name', 'workplace']
    assert rs.labels_for(keys) == [
        c.label for c in rs.COLUMNS if c.key in keys
    ]


def test_trainers_list_offers_export_dialog(client):
    """Список тренерів: форма, CSRF і чекбокси колонок -- з реєстру, а не
    вписані вручну в шаблон."""
    from app.services import trainer_resume_service as rs

    admin = _admin(client)
    make_trainer(name='Списковий Т.')
    db.session.commit()

    resp = client.get('/admin/trainers')
    assert resp.status_code == 200

    parsed = _parse_dialog(resp.data)
    assert parsed.has_csrf
    expected_keys = [c.key for c in rs.available_columns(admin)]
    assert [value for value, _ in parsed.columns] == expected_keys
    assert {value for value, checked in parsed.columns if checked} == set(rs.DEFAULT_KEYS)
    for column in rs.available_columns(admin):
        assert parsed.labels.get(f'resume-col-{column.key}') == column.label


def test_instance_page_offers_export_dialog(client):
    from app.services import trainer_resume_service as rs
    from app.services.trainer_links import set_trainers

    admin = _admin(client)
    course = make_course()
    trainer = make_trainer(name='Діалоговий Т.')
    set_trainers(course, [trainer.id])
    inst = make_instance(course)
    db.session.commit()

    resp = client.get(f'/admin/instances/{inst.id}/edit')
    assert resp.status_code == 200
    assert b'resume.pdf' in resp.data

    parsed = _parse_dialog(resp.data)
    assert parsed.has_csrf
    expected_keys = [c.key for c in rs.available_columns(admin)]
    assert [value for value, _ in parsed.columns] == expected_keys
    assert {value for value, checked in parsed.columns if checked} == set(rs.DEFAULT_KEYS)


def test_instance_without_trainers_hides_export_button(client):
    """Без тренерів заходу кнопка вела б у порожній діалог -- її немає."""
    _admin(client)
    course = make_course()
    inst = make_instance(course)
    db.session.commit()

    resp = client.get(f'/admin/instances/{inst.id}/edit')
    assert resp.status_code == 200
    assert b'data-modal-open="resume-columns-dialog"' not in resp.data


def test_dialog_hides_birth_date_without_finance_permission(client):
    """Дата народження -- trainers.finance; редактор контенту його не має."""
    from app.services import trainer_resume_service as rs

    editor = make_user_with_role('content_editor', email='tc-resume-editor@test.com')
    db.session.commit()
    switch_user(client, editor)
    make_trainer(name='Без фінансів Т.')
    db.session.commit()

    resp = client.get('/admin/trainers')
    assert resp.status_code == 200

    parsed = _parse_dialog(resp.data)
    values = [value for value, _ in parsed.columns]
    assert 'birth_date' not in values
    assert values == [c.key for c in rs.available_columns(editor)]


def _viewer_with(*perms):
    """Користувач з рівно цими правами -- вбудованої ролі «керує заходами,
    але не бачить тренерів» немає."""
    from app.models.rbac import Permission, Role

    role = Role(name='t_resume_' + '_'.join(p.replace('.', '') for p in perms),
                display_name='T')
    # Спершу в сесію: інакше autoflush на запиті Permission нижче
    # попереджає про роль поза сесією.
    db.session.add(role)
    for p in perms:
        role.permissions.append(Permission.query.filter_by(name=p).one())
    db.session.flush()
    return make_user_with_role(role.name, email='tc-resume-noview@test.com')


def test_instance_page_hides_export_without_trainers_view(client):
    """Кнопка вела б у маршрут під trainers.view -- без права її не видно."""
    from app.services.trainer_links import set_trainers

    user = _viewer_with('instances.view', 'instances.manage')
    db.session.commit()
    switch_user(client, user)
    course = make_course()
    trainer = make_trainer(name='Прихований Т.')
    set_trainers(course, [trainer.id])
    inst = make_instance(course)
    db.session.commit()

    resp = client.get(f'/admin/instances/{inst.id}/edit')
    assert resp.status_code == 200
    assert b'data-modal-open="resume-columns-dialog"' not in resp.data
    assert b'resume.pdf' not in resp.data


def _instance_id_inputs(html_bytes):
    class _Finder(HTMLParser):
        def __init__(self):
            super().__init__()
            self.values = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'input' and attrs.get('name') == 'instance_id':
                self.values.append(attrs.get('value'))

    finder = _Finder()
    finder.feed(html_bytes.decode('utf-8'))
    return finder.values


def test_instance_dialog_carries_instance_id(client):
    from app.services.trainer_links import set_trainers

    _admin(client)
    course = make_course()
    trainer = make_trainer(name='Номерний Т.')
    set_trainers(course, [trainer.id])
    inst = make_instance(course)
    db.session.commit()

    resp = client.get(f'/admin/instances/{inst.id}/edit')
    assert _instance_id_inputs(resp.data) == [str(inst.id)]

    listing = client.get('/admin/trainers')
    assert _instance_id_inputs(listing.data) == []


def _export(client, monkeypatch, **extra):
    """Вивантаження без WeasyPrint -- тут перевіряється лише імʼя файлу."""
    from app.services import trainer_resume_service as rs

    monkeypatch.setattr(rs, 'render_pdf', lambda trainers, keys: b'%PDF-fake%')
    trainer = make_trainer(name='Файловий Т.')
    db.session.commit()
    return client.post('/admin/trainers/resume.pdf', data={
        'ids': [str(trainer.id)], 'columns': ['full_name'], **extra,
    })


def test_filename_from_instance_page_has_event_number(client, monkeypatch):
    from datetime import date

    _admin(client)
    course = make_course()
    course.bpr_event_number = '4321'
    inst = make_instance(course)
    db.session.commit()

    resp = _export(client, monkeypatch, instance_id=str(inst.id))

    assert resp.status_code == 200
    disposition = resp.headers['Content-Disposition']
    assert f'rezume-treneriv-4321-{date.today():%Y-%m-%d}.pdf' in disposition


def test_filename_falls_back_to_instance_id_without_number(client, monkeypatch):
    _admin(client)
    inst = make_instance(make_course())
    db.session.commit()

    resp = _export(client, monkeypatch, instance_id=str(inst.id))

    assert f'rezume-treneriv-{inst.id}-' in resp.headers['Content-Disposition']


def test_filename_from_trainers_list_has_only_date(client, monkeypatch):
    from datetime import date

    _admin(client)
    resp = _export(client, monkeypatch)
    assert (f'rezume-treneriv-{date.today():%Y-%m-%d}.pdf'
            in resp.headers['Content-Disposition'])


def test_trainers_table_select_column_is_labelled(client):
    """Мобільні картки (admin-table-cards.js) беруть підпис комірки з тексту
    <th>; порожній заголовок лишав чекбокс без підпису і для скрінрідера."""
    _admin(client)
    make_trainer(name='Картковий Т.')
    db.session.commit()

    html = client.get('/admin/trainers').get_data(as_text=True)
    assert '<span class="visually-hidden">Обрати</span>' in html
    assert '<td data-label="Обрати">' in html


# --- Офіційна форма «Резюме викладача/тренера» (БПР) ------------------------

def _export_recording(client, monkeypatch, **extra):
    """Вивантаження без WeasyPrint із записом, який рендер викликано."""
    from app.services import trainer_resume_service as rs

    called = []
    monkeypatch.setattr(rs, 'render_pdf',
                        lambda trainers, keys: called.append('table') or b'%PDF-t%')
    monkeypatch.setattr(rs, 'render_form_pdf',
                        lambda trainers, keys: called.append('form') or b'%PDF-f%')
    trainer = make_trainer(name='Режимний Т.')
    db.session.commit()
    resp = client.post('/admin/trainers/resume.pdf', data={
        'ids': [str(trainer.id)], 'columns': ['full_name'], **extra,
    })
    return resp, called


def test_form_layout_renders_the_official_form_with_its_own_filename(client, monkeypatch):
    """Форма й таблиця -- різні документи: різне імʼя, щоб два вивантаження
    одного дня не перезаписали одне одного в завантаженнях."""
    from datetime import date

    _admin(client)
    resp, called = _export_recording(client, monkeypatch, layout='form')

    assert resp.status_code == 200
    assert called == ['form']
    assert (f'rezume-forma-bpr-{date.today():%Y-%m-%d}.pdf'
            in resp.headers['Content-Disposition'])


def test_request_without_layout_stays_a_table(client, monkeypatch):
    """Прямий запит без поля (старий клієнт) -- таблиця, як до появи форми."""
    _admin(client)
    resp, called = _export_recording(client, monkeypatch)

    assert resp.status_code == 200
    assert called == ['table']
    assert 'rezume-treneriv-' in resp.headers['Content-Disposition']


def test_dialog_offers_the_form_first_and_checked(client):
    """Форма -- за замовчуванням: вона й іде в пакет документів до реєстру."""
    _admin(client)
    make_trainer(name='Діалоговий Т.')
    db.session.commit()

    html = client.get('/admin/trainers').get_data(as_text=True)

    form_at = html.index('value="form" id="resume-layout-form" checked')
    table_at = html.index('value="table" id="resume-layout-table"')
    assert form_at < table_at
    assert 'value="table" id="resume-layout-table" checked' not in html


@requires_weasyprint
def test_form_export_returns_pdf(client):
    _admin(client)
    trainer = make_trainer(name='Формовий Т.')
    db.session.commit()
    resp = client.post('/admin/trainers/resume.pdf', data={
        'ids': [str(trainer.id)], 'columns': ['full_name', 'workplace'],
        'layout': 'form',
    })
    assert resp.status_code == 200
    assert resp.data[:4] == b'%PDF'
    assert resp.headers['Cache-Control'] == 'no-store, private'
