from flask import Blueprint, render_template

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    return render_template('iprm-preview/index.html', active_nav='labs')


@main_bp.route('/courses')
def courses():
    return render_template('iprm-preview/courses.html', active_nav='courses')


@main_bp.route('/course-detail')
def course_detail():
    return render_template('iprm-preview/course-detail.html', active_nav='courses')


@main_bp.route('/course-stomatology')
def course_stomatology():
    return render_template('iprm-preview/course-stomatology.html', active_nav='courses')


@main_bp.route('/course-orthopedics')
def course_orthopedics():
    return render_template('iprm-preview/course-orthopedics.html', active_nav='courses')


@main_bp.route('/design-system')
def design_system():
    return render_template('iprm-preview/design-system.html')


@main_bp.route('/404')
def page_404():
    return render_template('iprm-preview/404.html', active_nav=None)
