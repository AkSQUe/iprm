"""Рахунок на оплату участі: Excel (openpyxl) + PDF (WeasyPrint).

Excel будується openpyxl за версткою IPRM-рахунка; PDF рендериться WeasyPrint
з HTML-шаблона invoices/invoice.html (той самий стек, що й сертифікати) --
без зовнішніх залежностей на кшталт LibreOffice. Обидва документи будуються
з одних даних. Реквізити постачальника беруться з SiteSettings (банк, IBAN,
ЄДРПОУ, податковий статус).
"""
import io
import logging
from decimal import Decimal

from flask import current_app, render_template
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from app.models.mixins import utcnow
from app.models.site_settings import SiteSettings
from app.services.number_to_words_ua import number_to_words_ua
from app.utils import ensure_utc

logger = logging.getLogger(__name__)

_MONTHS = ['', 'січня', 'лютого', 'березня', 'квітня', 'травня', 'червня',
           'липня', 'серпня', 'вересня', 'жовтня', 'листопада', 'грудня']

# Стилі
_THIN = Side(style='thin', color='000000')
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
_HDR_FILL = PatternFill('solid', fgColor='F0F0F0')
_BOLD = Font(bold=True)
_WRAP = Alignment(wrap_text=True, vertical='top')
_CENTER = Alignment(horizontal='center', vertical='center', wrap_text=True)
_RIGHT = Alignment(horizontal='right', vertical='center')

_COLS = ['A', 'B', 'C', 'D', 'E', 'F']
_WIDTHS = {'A': 5, 'B': 46, 'C': 9, 'D': 7, 'E': 13, 'F': 15}


class InvoiceError(Exception):
    """Помилка генерації/конвертації рахунка (показується користувачу)."""


def _date_phrase(dt):
    dt = ensure_utc(dt) or utcnow()
    return f'{dt.day} {_MONTHS[dt.month]} {dt.year} р.'


def _invoice_context(reg):
    settings = SiteSettings.get()
    course = reg.instance.course if reg.instance else None
    title = course.title if course else (reg.target_title or f'Реєстрація #{reg.id}')
    item_name = 'Участь у заході: ' + title
    if reg.instance and reg.instance.start_date:
        item_name += f' ({ensure_utc(reg.instance.start_date).strftime("%d.%m.%Y")})'
    payer = ''
    if reg.user:
        payer = (reg.user.full_name or '').strip() or reg.user.email or ''
    return {
        'settings': settings,
        'number': reg.id,
        'date': reg.created_at,
        'item_name': item_name,
        'amount': Decimal(reg.payment_amount or 0),
        'payer': payer or 'Фізична особа',
    }


def build_invoice_xlsx(reg) -> io.BytesIO:
    """Згенерувати Excel-рахунок (BytesIO) за версткою IPRM."""
    ctx = _invoice_context(reg)
    s = ctx['settings']
    amount = ctx['amount']

    wb = Workbook()
    ws = wb.active
    ws.title = 'Рахунок'
    for col, w in _WIDTHS.items():
        ws.column_dimensions[col].width = w

    r = 1

    def merge_cell(row, text, *, bold=False, align=None, fill=None, border=False,
                   col_from='A', col_to='F', number_format=None):
        ws.merge_cells(f'{col_from}{row}:{col_to}{row}')
        cell = ws[f'{col_from}{row}']
        cell.value = text
        if bold:
            cell.font = _BOLD
        cell.alignment = align or _WRAP
        if fill:
            cell.fill = _HDR_FILL
        if number_format:
            cell.number_format = number_format
        if border:
            for c in range(_COLS.index(col_from), _COLS.index(col_to) + 1):
                ws.cell(row=row, column=c + 1).border = _BORDER
        return cell

    # Попередження
    merge_cell(r, (
        'Увага! Оплата цього рахунку означає погодження з умовами надання послуг. '
        'Повідомлення про оплату є обов\'язковим. Послуга надається за фактом '
        'надходження коштів на рахунок Постачальника.'
    ))
    ws.row_dimensions[r].height = 36
    r += 2

    # Зразок заповнення платіжного доручення
    merge_cell(r, 'Зразок заповнення платіжного доручення', bold=True, align=_CENTER, fill=True, border=True)
    r += 1
    for label, value in [
        ('Отримувач', s.company_full_name or 'ІПРМ'),
        ('Код', s.edrpou or ''),
        ('Банк отримувача', s.bank_name or ''),
        ('Рахунок №', s.bank_iban or ''),
    ]:
        ws.merge_cells(f'A{r}:B{r}')
        ws.merge_cells(f'C{r}:F{r}')
        lc = ws[f'A{r}']
        lc.value = label
        lc.font = _BOLD
        lc.alignment = _WRAP
        ws[f'C{r}'].value = value
        ws[f'C{r}'].alignment = _WRAP
        for c in range(1, 7):
            ws.cell(row=r, column=c).border = _BORDER
        r += 1
    r += 1

    # Заголовок
    merge_cell(r, 'РАХУНОК НА ОПЛАТУ', bold=True, align=_CENTER).font = Font(bold=True, size=16)
    r += 1
    merge_cell(r, f'№ {ctx["number"]} від {_date_phrase(ctx["date"])}', align=_CENTER)
    r += 2

    # Постачальник
    merge_cell(r, 'Постачальник:', bold=True)
    r += 1
    merge_cell(r, s.company_full_name or 'ІПРМ', bold=True)
    r += 1
    merge_cell(r, f'п/р {s.bank_iban} у банку {s.bank_name}')
    r += 1
    merge_cell(r, f'код за ЄДРПОУ {s.edrpou}')
    r += 1
    merge_cell(r, s.tax_status or '')
    r += 2

    # Платник
    merge_cell(r, 'Платник:', bold=True)
    r += 1
    merge_cell(r, ctx['payer'], bold=True)
    r += 2

    # Замовлення
    merge_cell(r, f'Замовлення № {ctx["number"]} від {_date_phrase(ctx["date"])}')
    r += 2

    # Таблиця послуг -- заголовок
    headers = ['№', 'Найменування робіт, послуг', 'Кіл-ть', 'Од.', 'Ціна', 'Сума']
    for idx, h in enumerate(headers):
        cell = ws.cell(row=r, column=idx + 1, value=h)
        cell.font = _BOLD
        cell.alignment = _CENTER
        cell.fill = _HDR_FILL
        cell.border = _BORDER
    r += 1

    # Позиція
    row_vals = [1, ctx['item_name'], 1, 'посл', float(amount), float(amount)]
    for idx, v in enumerate(row_vals):
        cell = ws.cell(row=r, column=idx + 1, value=v)
        cell.border = _BORDER
        if idx in (0, 2, 3):
            cell.alignment = _CENTER
        elif idx in (4, 5):
            cell.alignment = _RIGHT
            cell.number_format = '#,##0.00'
        else:
            cell.alignment = _WRAP
    r += 1

    # Разом
    ws.merge_cells(f'A{r}:E{r}')
    tc = ws[f'A{r}']
    tc.value = 'Разом:'
    tc.font = _BOLD
    tc.alignment = _RIGHT
    sum_cell = ws.cell(row=r, column=6, value=float(amount))
    sum_cell.font = _BOLD
    sum_cell.alignment = _RIGHT
    sum_cell.number_format = '#,##0.00'
    for c in range(1, 7):
        ws.cell(row=r, column=c).border = _BORDER
    r += 2

    # Підсумок + сума прописом
    merge_cell(r, f'Всього найменувань: 1, на суму {amount:.2f} грн.', bold=True)
    r += 1
    words = number_to_words_ua(amount, 'UAH')
    words = words[0].upper() + words[1:] if words else words
    merge_cell(r, f'Сума прописом: {words}')
    r += 2

    # Підпис
    merge_cell(r, 'Виписав(ла): ______________________________')

    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out


def _money(value):
    """Грошовий формат у стилі '1 500,00' (пробіл-тисячі, кома-копійки)."""
    s = f'{Decimal(value):,.2f}'  # 1,500.00
    return s.replace(',', ' ').replace('.', ',')


def _invoice_template_ctx(reg):
    """Підготувати дані для HTML-шаблона рахунка."""
    ctx = _invoice_context(reg)
    s = ctx['settings']
    amount = ctx['amount']
    words = number_to_words_ua(amount, 'UAH')
    words = (words[0].upper() + words[1:]) if words else words
    return {
        'number': ctx['number'],
        'date_phrase': _date_phrase(ctx['date']),
        'supplier': {
            'name': s.company_full_name or 'ІПРМ',
            'iban': s.bank_iban or '',
            'bank': s.bank_name or '',
            'edrpou': s.edrpou or '',
            'tax_status': s.tax_status or '',
        },
        'payer': ctx['payer'],
        'item_name': ctx['item_name'],
        'amount_str': _money(amount),
        'amount_words': words,
    }


def render_invoice_pdf(reg) -> bytes:
    """Згенерувати PDF-рахунок через WeasyPrint (HTML -> PDF, без LibreOffice).

    Кидає InvoiceError, якщо рендер не вдався."""
    try:
        from weasyprint import HTML
    except Exception as exc:  # бібліотека не встановлена / системні залежності
        logger.exception('WeasyPrint unavailable for invoice reg=%s', reg.id)
        raise InvoiceError(f'PDF-рендер недоступний: {exc}')
    try:
        html = render_template('invoices/invoice.html', **_invoice_template_ctx(reg))
        return HTML(string=html, base_url=current_app.static_folder).write_pdf()
    except InvoiceError:
        raise
    except Exception as exc:
        logger.exception('Invoice PDF render failed for reg=%s', reg.id)
        raise InvoiceError(f'Помилка генерації PDF-рахунка: {exc}')


def invoice_filename(reg, ext):
    return f'rahunok-{reg.id}.{ext}'
