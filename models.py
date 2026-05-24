from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(100), default='')
    current_level = db.Column(db.Integer, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    results = db.relationship('TestResult', backref='student', lazy=True, cascade='all, delete-orphan')
    answers = db.relationship('AnswerRecord', backref='student', lazy=True, cascade='all, delete-orphan')


class TestResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    level = db.Column(db.Integer, nullable=False)
    score = db.Column(db.Integer, nullable=False)
    total = db.Column(db.Integer, default=10)
    completed_at = db.Column(db.DateTime, default=datetime.utcnow)


class AnswerRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    level = db.Column(db.Integer, nullable=False)
    q_number = db.Column(db.Integer, nullable=False)
    word = db.Column(db.String(200), default='')
    selected = db.Column(db.String(10), default='')
    correct = db.Column(db.String(10), nullable=False)
    is_correct = db.Column(db.Boolean, default=False)


class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
