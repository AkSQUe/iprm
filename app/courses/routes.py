from flask import render_template

from app.courses import courses_bp


@courses_bp.route('/courses')
def course_list():
    return render_template('courses/list.html', active_nav='courses')


@courses_bp.route('/course-detail')
def course_detail():
    return render_template('courses/detail.html', active_nav='courses')


@courses_bp.route('/course-stomatology')
def course_stomatology():
    return render_template('courses/stomatology.html', active_nav='courses')


@courses_bp.route('/course-orthopedics')
def course_orthopedics():
    return render_template('courses/orthopedics.html', active_nav='courses')
