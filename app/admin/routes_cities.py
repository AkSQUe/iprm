"""Адмінка довідника локацій: назва + переклади ru/en в одній таблиці.

Довідник маленький і плоский, тож окремої форми редагування немає --
усі рядки редагуються й зберігаються однією таблицею. Це та сама сутність,
що й у /admin/translations/city/<id>, але для глосарія на десятки коротких
рядків посторінковий редактор був би зайвим клацанням.
"""
import logging

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.admin import admin_bp
from app.admin._helpers import try_commit
from app.admin.decorators import admin_required
from app.extensions import db
from app.i18n import PREFIXED_LANGUAGES
from app.models.city import City, normalize_city_name
from app.services import city_glossary

audit_logger = logging.getLogger('audit')


@admin_bp.route('/cities', methods=['GET'])
@admin_required
def cities_list():
    cities = City.query.order_by(City.name).all()
    return render_template(
        'admin/cities.html',
        cities=cities,
        languages=PREFIXED_LANGUAGES,
        unknown=city_glossary.unknown_locations(),
    )


@admin_bp.route('/cities/save', methods=['POST'])
@admin_required
def cities_save():
    """Зберегти переклади наявних рядків одним сабмітом."""
    cities = City.query.all()
    for city in cities:
        for lang in PREFIXED_LANGUAGES:
            key = f'tr__{lang}__{city.id}'
            if key not in request.form:
                continue
            city.set_translation(lang, 'name', (request.form.get(key) or '').strip() or None)
    if try_commit(log_context='cities_save'):
        audit_logger.info('Admin %s updated city glossary (%s rows)',
                          current_user.email, len(cities))
        flash('Довідник збережено.', 'success')
    return redirect(url_for('admin.cities_list'))


@admin_bp.route('/cities/add', methods=['POST'])
@admin_required
def cities_add():
    """Додати назву в довідник. Приймає і ручний ввід, і кнопку біля
    локації, якої бракує."""
    name = (request.form.get('name') or '').strip()
    if not name:
        flash('Вкажіть назву локації', 'error')
        return redirect(url_for('admin.cities_list'))

    exists = City.query.filter_by(name_normalized=normalize_city_name(name)).first()
    if exists:
        flash(f'"{exists.name}" вже є в довіднику', 'info')
        return redirect(url_for('admin.cities_list'))

    db.session.add(City(name=name))
    if try_commit(log_context=f'cities_add name={name!r}',
                  error_msg='Не вдалося додати локацію (можливо, її щойно '
                            'додав інший адміністратор)'):
        audit_logger.info('Admin %s added city %r to glossary', current_user.email, name)
        flash(f'Додано "{name}". Впишіть переклади і збережіть.', 'success')
    return redirect(url_for('admin.cities_list'))


@admin_bp.route('/cities/add-missing', methods=['POST'])
@admin_required
def cities_add_missing():
    """Додати всі локації розкладу, яких немає в довіднику.

    При першому наповненні їх десяток, і тиснути кнопку біля кожної нема сенсу.
    """
    missing = city_glossary.unknown_locations()
    if not missing:
        flash('Усі локації розкладу вже є в довіднику', 'info')
        return redirect(url_for('admin.cities_list'))

    for name in missing:
        db.session.add(City(name=name))
    if try_commit(log_context=f'cities_add_missing count={len(missing)}'):
        audit_logger.info('Admin %s added %s cities to glossary',
                          current_user.email, len(missing))
        flash(f'Додано локацій: {len(missing)}. Впишіть переклади і збережіть.',
              'success')
    return redirect(url_for('admin.cities_list'))


@admin_bp.route('/cities/<int:city_id>/delete', methods=['POST'])
@admin_required
def cities_delete(city_id):
    city = db.session.get(City, city_id)
    if city is None:
        flash('Локацію не знайдено', 'error')
        return redirect(url_for('admin.cities_list'))
    name = city.name
    db.session.delete(city)
    if try_commit(log_context=f'cities_delete id={city_id}'):
        audit_logger.info('Admin %s deleted city %r from glossary', current_user.email, name)
        flash(f'"{name}" видалено з довідника. Локація показуватиметься українською.',
              'success')
    return redirect(url_for('admin.cities_list'))
