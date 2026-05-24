import json
import os
from functools import wraps
from flask import Flask, render_template, request, redirect, session, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, Student, TestResult, AnswerRecord, Admin

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///vocab_test.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

with open('questions.json', 'r', encoding='utf-8') as f:
    QUESTIONS = json.load(f)

TOTAL_LEVELS = len(QUESTIONS)


def load_questions(level_index):
    for lv in QUESTIONS:
        if lv['level_index'] == level_index:
            return lv['questions']
    return None


def build_option_map():
    opt = {}
    for lv in QUESTIONS:
        for q in lv['questions']:
            opt[(lv['level_index'], q['number'])] = q['options']
    return opt


OPTION_MAP = build_option_map()


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'admin_id' not in session:
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated


@app.context_processor
def inject_globals():
    ctx = {
        'total_levels': TOTAL_LEVELS,
        'level_names': {lv['level_index']: lv['level_name'] for lv in QUESTIONS},
        'completed_set': set(),
    }
    sid = session.get('student_id')
    if sid:
        ctx['completed_set'] = {r.level for r in TestResult.query.filter_by(student_id=sid).all()}
    return ctx


def init_admin():
    if not Admin.query.filter_by(username='admin').first():
        pw = os.environ.get('ADMIN_PASSWORD', 'admin123')
        admin = Admin(username='admin', password_hash=generate_password_hash(pw))
        db.session.add(admin)
        db.session.commit()


# ─── Student Routes ─────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/login', methods=['POST'])
def login():
    name = request.form.get('name', '').strip()
    role = request.form.get('role', '').strip()
    if not name:
        flash('请输入姓名')
        return redirect(url_for('index'))
    student = Student.query.filter_by(name=name).first()
    if not student:
        student = Student(name=name, role=role, current_level=1)
        db.session.add(student)
        db.session.commit()
    else:
        if role:
            student.role = role
            db.session.commit()
    session['student_id'] = student.id
    session['student_name'] = student.name
    return redirect(url_for('test'))


@app.route('/logout')
def logout():
    session.pop('student_id', None)
    session.pop('student_name', None)
    return redirect(url_for('index'))


@app.route('/test')
def test():
    if 'student_id' not in session:
        return redirect(url_for('index'))
    student = db.session.get(Student, session['student_id'])
    if not student:
        return redirect(url_for('index'))

    level = request.args.get('level', type=int)
    if not level or level < 1:
        level = student.current_level
    if level > TOTAL_LEVELS:
        return redirect(url_for('result'))

    questions = load_questions(level)
    if not questions:
        flash('题目加载失败')
        return redirect(url_for('result'))

    level_name = next((lv['level_name'] for lv in QUESTIONS if lv['level_index'] == level), '')

    return render_template('test.html', questions=questions, level=level,
                           level_name=level_name)


@app.route('/submit', methods=['POST'])
def submit():
    if 'student_id' not in session:
        return redirect(url_for('index'))
    student = db.session.get(Student, session['student_id'])
    if not student:
        return redirect(url_for('index'))

    level = request.form.get('level', type=int)
    if not level or level < 1 or level > TOTAL_LEVELS:
        return redirect(url_for('test'))

    questions = load_questions(level)
    if not questions:
        return redirect(url_for('test'))

    # Remove old records for this level (supports retake)
    AnswerRecord.query.filter_by(student_id=student.id, level=level).delete()
    TestResult.query.filter_by(student_id=student.id, level=level).delete()

    score = 0
    for q in questions:
        key = f'q_{q["number"]}'
        selected = request.form.get(key, '')
        correct = q['correct']
        is_correct = selected == correct
        if is_correct:
            score += 1
        db.session.add(AnswerRecord(
            student_id=student.id,
            level=level,
            q_number=q['number'],
            word=q['word'],
            selected=selected,
            correct=correct,
            is_correct=is_correct
        ))

    db.session.add(TestResult(
        student_id=student.id,
        level=level,
        score=score,
        total=len(questions)
    ))

    if student.current_level <= level:
        student.current_level = level + 1
    db.session.commit()

    session['last_score'] = score
    session['last_level'] = level
    return redirect(url_for('result'))


@app.route('/result')
def result():
    if 'student_id' not in session:
        return redirect(url_for('index'))
    student = db.session.get(Student, session['student_id'])
    if not student:
        return redirect(url_for('index'))

    results = TestResult.query.filter_by(student_id=student.id)\
        .order_by(TestResult.level).all()

    total_correct = sum(r.score for r in results)
    vocab_estimate = total_correct * 100
    completed_levels = len(results)

    wrong_count = AnswerRecord.query.filter_by(
        student_id=student.id, is_correct=False
    ).count()

    return render_template('result.html', student=student, results=results,
                           total_correct=total_correct, vocab_estimate=vocab_estimate,
                           completed_levels=completed_levels, wrong_count=wrong_count,
                           last_score=session.pop('last_score', None),
                           last_level=session.pop('last_level', None))


@app.route('/wrong')
def wrong():
    if 'student_id' not in session:
        return redirect(url_for('index'))
    student = db.session.get(Student, session['student_id'])
    if not student:
        return redirect(url_for('index'))

    records = AnswerRecord.query.filter_by(
        student_id=student.id, is_correct=False
    ).order_by(AnswerRecord.level, AnswerRecord.q_number).all()

    wrong_by_level = {}
    for r in records:
        wrong_by_level.setdefault(r.level, []).append(r)

    level_names = {lv['level_index']: lv['level_name'] for lv in QUESTIONS}

    return render_template('wrong.html', student=student,
                           wrong_by_level=wrong_by_level, level_names=level_names,
                           option_map=OPTION_MAP)


# ─── Admin Routes ─────────────────────────────────

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        admin = Admin.query.filter_by(username=username).first()
        if admin and check_password_hash(admin.password_hash, password):
            session['admin_id'] = admin.id
            session['admin_username'] = admin.username
            return redirect(url_for('admin_dashboard'))
        flash('用户名或密码错误')
    return render_template('admin_login.html')


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_id', None)
    session.pop('admin_username', None)
    return redirect(url_for('admin_login'))


@app.route('/admin')
@admin_required
def admin_dashboard():
    students = Student.query.order_by(Student.created_at.desc()).all()
    student_data = []
    for s in students:
        results = TestResult.query.filter_by(student_id=s.id).all()
        total_correct = sum(r.score for r in results)
        vocab_estimate = total_correct * 100
        completed = len(results)
        student_data.append({
            'student': s,
            'completed': completed,
            'total_correct': total_correct,
            'vocab_estimate': vocab_estimate
        })
    return render_template('admin_dashboard.html', students=student_data)


@app.route('/admin/student/<int:student_id>')
@admin_required
def admin_student_detail(student_id):
    student = db.session.get(Student, student_id)
    if not student:
        flash('学生不存在')
        return redirect(url_for('admin_dashboard'))
    results = TestResult.query.filter_by(student_id=student.id)\
        .order_by(TestResult.level).all()
    total_correct = sum(r.score for r in results)
    vocab_estimate = total_correct * 100

    wrong_records = AnswerRecord.query.filter_by(
        student_id=student.id, is_correct=False
    ).order_by(AnswerRecord.level, AnswerRecord.q_number).all()

    return render_template('admin_student.html', student=student,
                           results=results, total_correct=total_correct,
                           vocab_estimate=vocab_estimate, wrong_records=wrong_records,
                           option_map=OPTION_MAP)


@app.route('/admin/student/add', methods=['GET', 'POST'])
@admin_required
def admin_add_student():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        role = request.form.get('role', '').strip()
        if not name:
            flash('请输入姓名')
            return render_template('admin_add_student.html')
        student = Student(name=name, role=role, current_level=1)
        db.session.add(student)
        db.session.commit()
        flash(f'已添加学生: {name}')
        return redirect(url_for('admin_dashboard'))
    return render_template('admin_add_student.html')


@app.route('/admin/student/<int:student_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_edit_student(student_id):
    student = db.session.get(Student, student_id)
    if not student:
        flash('学生不存在')
        return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        role = request.form.get('role', '').strip()
        level = request.form.get('current_level', type=int)
        if name:
            student.name = name
        student.role = role
        if level and 1 <= level <= TOTAL_LEVELS + 1:
            student.current_level = level
        db.session.commit()
        flash('已更新')
        return redirect(url_for('admin_student_detail', student_id=student.id))
    return render_template('admin_edit_student.html', student=student,
                           total_levels=TOTAL_LEVELS)


@app.route('/admin/student/<int:student_id>/delete', methods=['POST'])
@admin_required
def admin_delete_student(student_id):
    student = db.session.get(Student, student_id)
    if student:
        db.session.delete(student)
        db.session.commit()
        flash(f'已删除学生: {student.name}')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/student/<int:student_id>/reset', methods=['POST'])
@admin_required
def admin_reset_student(student_id):
    student = db.session.get(Student, student_id)
    if student:
        TestResult.query.filter_by(student_id=student.id).delete()
        AnswerRecord.query.filter_by(student_id=student.id).delete()
        student.current_level = 1
        db.session.commit()
        flash(f'已重置学生: {student.name}')
    return redirect(url_for('admin_student_detail', student_id=student_id))


# ─── Init & Run ─────────────────────────────────

with app.app_context():
    db.create_all()
    init_admin()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, debug=True)
