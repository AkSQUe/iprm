"""Admin: виручка й зобов'язання за місяць.

Правила "виконано / винні" живуть у app.services.finance_report -- тут лише
вибір місяця, сторінка і xlsx. Сторінка і файл будуються з одного звіту,
тож картка на екрані й сума аркуша не розійдуться.
"""
import logging
from datetime import date

from flask import render_template, request
from flask_login import current_user

from app.admin import _listing, admin_bp
from app.rbac import permission_required
from app.services import finance_report
from app.utils import kyiv_dt

audit_logger = logging.getLogger('audit')

MONTH_NAMES = ('Січень', 'Лютий', 'Березень', 'Квітень', 'Травень', 'Червень',
               'Липень', 'Серпень', 'Вересень', 'Жовтень', 'Листопад', 'Грудень')
# Скільки місяців назад пропонувати у виборі. Довільний місяць однаково
# відкривається через ?month=YYYY-MM.
MONTHS_BACK = 24


def _month_label(month):
    return f'{MONTH_NAMES[month.month - 1]} {month.year}'


def _month_options(current):
    options = []
    year, month = current.year, current.month
    for _ in range(MONTHS_BACK):
        value = date(year, month, 1)
        options.append((value.strftime('%Y-%m'), _month_label(value)))
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return options


def _report():
    today_month = finance_report.parse_month(None)
    month = finance_report.parse_month(request.args.get('month'))
    return finance_report.build_report(month), today_month


@admin_bp.route('/revenue')
@permission_required('revenue.view')
def revenue_report():
    report, today_month = _report()
    return render_template(
        'admin/revenue.html',
        report=report,
        month_value=report.month.strftime('%Y-%m'),
        month_label=_month_label(report.month),
        month_options=_month_options(today_month),
        as_of_label=kyiv_dt(report.as_of),
    )


@admin_bp.route('/revenue/export')
@permission_required('revenue.export')
def revenue_export():
    from app.services import xlsx_reports

    report, _ = _report()
    month_value = report.month.strftime('%Y-%m')
    rows = report.revenue + report.liabilities
    summary = _listing.export_summary(
        [
            ('Місяць', _month_label(report.month)),
            ('Станом на', kyiv_dt(report.as_of)),
            ('Виручка (грн)', float(report.revenue_total)),
            ("Зобов'язання на кінець періоду (грн)", float(report.liabilities_total)),
            ('Оплати без дати (не враховано)', ', '.join(report.undated) or '–'),
        ],
        len(rows),
    )
    audit_logger.info('Admin %s exported revenue report xlsx (%s, %d rows)',
                      current_user.email, month_value, len(rows))
    return _listing.xlsx_export(
        rows, f'vyruchka_{month_value}',
        lambda: xlsx_reports.export_finance_report_xlsx(report, summary),
        'admin.revenue_report', month=month_value,
    )
