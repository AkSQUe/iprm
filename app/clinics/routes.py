from flask import render_template, abort

from app.clinics import clinics_bp
from app.models.clinic import Clinic


@clinics_bp.route('/')
def clinic_list():
    clinics = Clinic.query.filter_by(is_active=True).order_by(Clinic.sort_order).all()
    return render_template('clinics/list.html', active_nav='clinics', clinics=clinics)


@clinics_bp.route('/<slug>')
def clinic_detail(slug):
    clinic = Clinic.query.filter_by(slug=slug, is_active=True).first()
    if not clinic:
        abort(404)
    return render_template('clinics/detail.html', active_nav='clinics', clinic=clinic)
