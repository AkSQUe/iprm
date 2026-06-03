"""Адмін-інструменти. Наразі: генератор сертифікатів з xlsx.

Завантажується заповнена xlsx-таблиця (рядок = сертифікат), на виході --
ZIP з PDF-сертифікатами. Standalone: записів у БД не створює (для разових
чи зовнішніх заходів). Номер будується у форматі БПР; провайдер береться
з налаштувань сайту, решта сегментів -- з рядка таблиці.
"""
import io
import logging
import zipfile
from datetime import datetime

from flask import (
    flash, redirect, render_template, request, send_file, url_for,
)
from flask_login import current_user
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from app.admin import admin_bp
from app.admin.decorators import admin_required
from app.models.certificate import Certificate
from app.models.site_settings import SiteSettings
from app.services import certificate_service as cs

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger('audit')

# Колонки шаблону (порядок фіксований).
COLUMNS = [
    'ПІБ учасника',
    'Назва заходу',
    'Дата проведення (ДД.ММ.РРРР)',
    'Бали БПР',
    'ПІБ лектора',
    'Номер заходу БПР (7 цифр)',
    'Номер учасника (6 цифр)',
]
_WIDTHS = [28, 42, 26, 10, 24, 24, 22]


@admin_bp.route('/tools/certificate-generator')
@admin_required
def tool_certificate_generator():
    provider = (SiteSettings.get().bpr_provider_number or '').strip()
    return render_template(
        'admin/tools_certificate_generator.html',
        columns=COLUMNS,
        provider_number=provider,
    )


@admin_bp.route('/tools/certificate-generator/template')
@admin_required
def tool_certificate_generator_template():
    """Порожній xlsx-шаблон із заголовками + приклад-рядок."""
    wb = Workbook()
    ws = wb.active
    ws.title = 'Сертифікати'
    ws.append(COLUMNS)
    head_font = Font(bold=True, color='FFFFFF')
    head_fill = PatternFill('solid', fgColor='7055A4')
    for cell in ws[1]:
        cell.font = head_font
        cell.fill = head_fill
    ws.append([
        'Шевченко Тарас Григорович', 'Сучасні протоколи PRP-терапії',
        '15.05.2026', 10, 'Абрамович Є.В.', '1028974', '1',
    ])
    for i, w in enumerate(_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = 'A2'

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(
        buf,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='certificate-generator-template.xlsx',
    )


def _parse_date(val):
    if val in (None, ''):
        return None
    if isinstance(val, datetime):
        return val
    s = str(val).strip()
    for fmt in ('%d.%m.%Y', '%Y-%m-%d', '%d/%m/%Y', '%d.%m.%y'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


@admin_bp.route('/tools/certificate-generator/generate', methods=['POST'])
@admin_required
def tool_certificate_generator_run():
    provider = (SiteSettings.get().bpr_provider_number or '').strip()
    if not provider:
        flash('Спочатку задайте реєстраційний номер провайдера БПР '
              '(Налаштування сайту)', 'error')
        return redirect(url_for('admin.tool_certificate_generator'))

    file = request.files.get('xlsx')
    if not file or not file.filename:
        flash('Файл не вибрано', 'error')
        return redirect(url_for('admin.tool_certificate_generator'))
    if not file.filename.lower().endswith('.xlsx'):
        flash('Потрібен файл формату .xlsx', 'error')
        return redirect(url_for('admin.tool_certificate_generator'))

    try:
        wb = load_workbook(file, read_only=True, data_only=True)
        ws = wb.active
        raw_rows = list(ws.iter_rows(min_row=2, values_only=True))
    except Exception:
        logger.exception('certificate-generator: failed to read xlsx')
        flash('Не вдалося прочитати xlsx-файл', 'error')
        return redirect(url_for('admin.tool_certificate_generator'))

    items, errors = [], []
    for idx, row in enumerate(raw_rows, start=2):
        if not row or all(c is None or str(c).strip() == '' for c in row):
            continue
        cells = list(row) + [None] * (7 - len(row))
        name, title, date_raw, cpd_raw, lecturer, event_raw, part_raw = cells[:7]
        name = str(name).strip() if name is not None else ''
        title = str(title).strip() if title is not None else ''
        dt = _parse_date(date_raw)
        event_num = str(event_raw).strip() if event_raw is not None else ''
        part_num = str(part_raw).strip() if part_raw is not None else ''

        problems = []
        if not name:
            problems.append('немає ПІБ учасника')
        if not title:
            problems.append('немає назви заходу')
        if dt is None:
            problems.append('некоректна дата')
        if not event_num:
            problems.append('немає номера заходу')
        if not part_num:
            problems.append('немає номера учасника')
        cpd = None
        if cpd_raw not in (None, ''):
            try:
                cpd = int(float(str(cpd_raw).strip().replace(',', '.')))
            except ValueError:
                problems.append('бали БПР не число')

        if problems:
            errors.append(f'Рядок {idx}: ' + ', '.join(problems))
            continue
        items.append({
            'name': name, 'title': title, 'dt': dt, 'cpd': cpd,
            'lecturer': str(lecturer).strip() if lecturer else None,
            'event': event_num, 'part': part_num,
        })

    if errors:
        for e in errors[:25]:
            flash(e, 'error')
        return redirect(url_for('admin.tool_certificate_generator'))
    if not items:
        flash('У таблиці немає рядків з даними', 'error')
        return redirect(url_for('admin.tool_certificate_generator'))

    try:
        zbuf = io.BytesIO()
        with zipfile.ZipFile(zbuf, 'w', zipfile.ZIP_DEFLATED) as zf:
            for it in items:
                number = Certificate.format_number(
                    it['dt'].year, provider, it['event'], it['part'],
                )
                pdf = cs.render_adhoc_pdf(
                    number=number,
                    recipient_name=it['name'],
                    event_title=it['title'],
                    event_date=it['dt'],
                    cpd_points=it['cpd'],
                    lecturer_name=it['lecturer'],
                    issued_at=it['dt'],
                )
                zf.writestr(f'{number}.pdf', pdf)
        zbuf.seek(0)
    except Exception:
        logger.exception('certificate-generator: failed to render PDFs')
        flash('Помилка генерації PDF (перевірте, що WeasyPrint встановлено)', 'error')
        return redirect(url_for('admin.tool_certificate_generator'))

    audit_logger.info(
        'Admin %s generated %d certificates via xlsx tool',
        current_user.email, len(items),
    )
    return send_file(
        zbuf, mimetype='application/zip',
        as_attachment=True, download_name='certificates.zip',
    )
