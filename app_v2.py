# ==============================================================================
# 개발 변경 이력 (Development Change History)
# ==============================================================================
# v0.1: 기존 Routine Tracker 기본 기능 구현 (tasks, task_logs CRUD 및 통계)
# v1.0 (2026-07-03):
#   - 로그인 기능 구현: 회원별로 독립된 SQLite 데이터베이스 작동
#   - 관리자 계정 생성: 아이디 'admin', 초기 비밀번호 '~admin1'
#   - 관리자 회원관리 페이지(/admin) 추가: 회원 목록 조회, 추가, 비밀번호 수정, 삭제 기능
#   - 기존 routine.db 데이터를 'user01' 계정(비밀번호 '~user1')으로 자동 마이그레이션 처리
# v1.1 (2026-07-03):
#   - 우측 상단 로그인 정보 표시 및 로그인/로그아웃 단추 추가
#   - 비로그인 상태여도 기본 메뉴(대시보드, 태스크 관리, 리포트 히스토리)가 navbar에 모두 보이도록 수정
# v1.2 (2026-07-03):
#   - 서비스 워커 캐시 버전 업그레이드(v1 -> v2) 및 이전 오프라인 HTML 캐시 강제 삭제 로직 탑재
#   - 대시보드(/) 및 태스크 관리(/manage) 이동 시 캐시 오동작으로 인한 네비바 노출 불일치 이슈 근절
# v1.3 (2026-07-03):
#   - Render 클라우드 배포를 위한 PORT 환경 변수 동적 수신 및 0.0.0.0 외부 호스트 바인딩 적용
#   - Render Persistent Disk(/opt/render/project/src/data) 마운트 자동 감지 및 DB 경로 자동 연동 기능 추가
# v2.0 (2026-07-03):
#   - 외부 클라우드 DB(Supabase/PostgreSQL) 연동 지원 추가
#   - DATABASE_URL 환경 변수 감지 시 자동으로 Postgres 연결
#   - 로컬 테스트 환경을 위해 SQLite를 동일한 통합 테이블 구조로 백업 및 자동 마이그레이션 지원
# v2.1 (2026-07-06):
#   - 회원 데이터 백업 및 복원 기능 추가 (데이터 내보내기/가져오기)
#   - /api/backup/export 및 /api/backup/import 라우트 구현 (SQLite 파일 업로드/다운로드 방식)
# v2.2 (2026-10-25):
#   - 회원 데이터 초기화(Reset) 기능 추가 (/api/backup/reset)
# ==============================================================================

import sqlite3
import psycopg2
from psycopg2.extras import DictCursor
from flask import Flask, render_template, request, jsonify, g, session, redirect, url_for, flash, after_this_request, send_file
import os
import shutil
import tempfile
from datetime import datetime
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
# 세션을 유지하기 위한 시크릿 키 설정
app.secret_key = 'routine_tracker_secret_key_change_me_in_production'

# DB 경로 및 디렉토리 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Render Persistent Disk 마운트 경로(/opt/render/project/src/data) 자동 감지 및 설정 (SQLite 백업용)
RENDER_DATA_DIR = '/opt/render/project/src/data'
if os.path.exists(RENDER_DATA_DIR):
    DB_DIR = RENDER_DATA_DIR
else:
    DB_DIR = BASE_DIR

USERS_DIR = os.path.join(DB_DIR, 'users')
MAIN_DB = os.path.join(DB_DIR, 'routine_main.db')
OLD_DB = os.path.join(BASE_DIR, 'routine.db')

DATABASE_URL = os.environ.get('DATABASE_URL')
IS_POSTGRES = DATABASE_URL is not None

class DBConnection:
    """SQLite와 PostgreSQL의 실행 인터페이스를 통일하는 래퍼 클래스"""
    def __init__(self):
        if IS_POSTGRES:
            self.conn = psycopg2.connect(DATABASE_URL)
        else:
            self.conn = sqlite3.connect(MAIN_DB)
            self.conn.row_factory = sqlite3.Row

    def execute(self, sql, params=()):
        if IS_POSTGRES:
            # PostgreSQL은 ? 대신 %s 바인딩을 사용하므로 치환
            sql = sql.replace('?', '%s')
            cur = self.conn.cursor(cursor_factory=DictCursor)
        else:
            cur = self.conn.cursor()
            
        cur.execute(sql, params)
        return cur

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()

def migrate_sqlite_to_unified():
    """기존 개별 SQLite DB 파일들을 단일 메인 DB로 통합 마이그레이션 (로컬 전용)"""
    if not IS_POSTGRES and os.path.exists(USERS_DIR):
        for filename in os.listdir(USERS_DIR):
            if filename.startswith('routine_') and filename.endswith('.db'):
                username = filename[8:-3]
                user_db_path = os.path.join(USERS_DIR, filename)
                try:
                    user_conn = sqlite3.connect(user_db_path)
                    user_cur = user_conn.cursor()
                    
                    # tasks 테이블 존재 여부 확인
                    user_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
                    if not user_cur.fetchone():
                        user_conn.close()
                        continue
                        
                    user_cur.execute("SELECT id, name, start_date, time, created_at, order_index FROM tasks")
                    tasks = user_cur.fetchall()
                    
                    main_conn = sqlite3.connect(MAIN_DB)
                    main_cur = main_conn.cursor()
                    
                    for t in tasks:
                        old_task_id = t[0]
                        name = t[1]
                        start_date = t[2]
                        time = t[3]
                        created_at = t[4]
                        order_index = t[5]
                        
                        # 이미 가져온 태스크인지 중복 방지 검사
                        main_cur.execute("SELECT id FROM tasks WHERE username = ? AND name = ?", (username, name))
                        if not main_cur.fetchone():
                            main_cur.execute("""
                                INSERT INTO tasks (username, name, start_date, time, created_at, order_index)
                                VALUES (?, ?, ?, ?, ?, ?)
                            """, (username, name, start_date, time, created_at, order_index))
                            new_task_id = main_cur.lastrowid
                            
                            # 해당 태스크의 로그도 복제
                            user_cur.execute("SELECT date, is_completed FROM task_logs WHERE task_id = ?", (old_task_id,))
                            logs = user_cur.fetchall()
                            for log in logs:
                                main_cur.execute("""
                                    INSERT INTO task_logs (task_id, date, is_completed)
                                    VALUES (?, ?, ?)
                                """, (new_task_id, log[0], log[1]))
                                
                    main_conn.commit()
                    main_conn.close()
                    user_conn.close()
                    
                    # 마이그레이션이 성공한 파일은 확장자 변경
                    os.rename(user_db_path, user_db_path + '.migrated')
                    print(f"Successfully migrated SQLite DB for user '{username}' to unified DB.")
                except Exception as e:
                    print(f"Migration error for {filename}: {e}")

def init_db():
    """데이터베이스 테이블 생성 및 초기 데이터 설정 (Postgres / SQLite 공용)"""
    if IS_POSTGRES:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # users 테이블 생성
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(100) UNIQUE NOT NULL,
                password VARCHAR(255) NOT NULL,
                is_admin INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # tasks 테이블 생성 (단일 DB이므로 username으로 데이터 격리)
        cur.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY,
                username VARCHAR(100) NOT NULL,
                name TEXT NOT NULL,
                start_date VARCHAR(10) NOT NULL,
                time VARCHAR(5) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                order_index INTEGER DEFAULT 0
            )
        ''')
        
        # task_logs 테이블 생성
        cur.execute('''
            CREATE TABLE IF NOT EXISTS task_logs (
                id SERIAL PRIMARY KEY,
                task_id INTEGER NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
                date VARCHAR(10) NOT NULL,
                is_completed INTEGER DEFAULT 0
            )
        ''')
        
        # 기본 관리자 admin 계정 생성 (~admin1)
        cur.execute('SELECT * FROM users WHERE username = %s', ('admin',))
        if not cur.fetchone():
            cur.execute(
                'INSERT INTO users (username, password, is_admin) VALUES (%s, %s, %s)',
                ('admin', generate_password_hash('~admin1'), 1)
            )
            
        # 기본 사용자 user01 계정 생성 (~user1)
        cur.execute('SELECT * FROM users WHERE username = %s', ('user01',))
        if not cur.fetchone():
            cur.execute(
                'INSERT INTO users (username, password, is_admin) VALUES (%s, %s, %s)',
                ('user01', generate_password_hash('~user1'), 0)
            )
            
        conn.commit()
        cur.close()
        conn.close()
        print("PostgreSQL Database initialized.")
    else:
        # 로컬 SQLite 초기화 및 레거시 데이터 마이그레이션 처리
        if not os.path.exists(DB_DIR):
            os.makedirs(DB_DIR)
            
        # 레거시 백업 체크 (app v1.0 호환성)
        if os.path.exists(OLD_DB):
            if not os.path.exists(USERS_DIR):
                os.makedirs(USERS_DIR)
            user01_db_path = os.path.join(USERS_DIR, 'routine_user01.db')
            try:
                shutil.copy(OLD_DB, user01_db_path)
                backup_path = OLD_DB + '.backup'
                os.rename(OLD_DB, backup_path)
                print(f"Legacy SQLite DB routine.db moved to {user01_db_path}")
            except Exception as e:
                print(f"Error copying legacy DB: {e}")

        conn = sqlite3.connect(MAIN_DB)
        cur = conn.cursor()
        
        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                is_admin INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cur.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                name TEXT NOT NULL,
                start_date TEXT NOT NULL,
                time TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                order_index INTEGER DEFAULT 0
            )
        ''')
        
        cur.execute('''
            CREATE TABLE IF NOT EXISTS task_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                is_completed INTEGER DEFAULT 0,
                FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE
            )
        ''')
        
        cur.execute('SELECT * FROM users WHERE username = ?', ('admin',))
        if not cur.fetchone():
            cur.execute(
                'INSERT INTO users (username, password, is_admin) VALUES (?, ?, ?)',
                ('admin', generate_password_hash('~admin1'), 1)
            )
            
        cur.execute('SELECT * FROM users WHERE username = ?', ('user01',))
        if not cur.fetchone():
            cur.execute(
                'INSERT INTO users (username, password, is_admin) VALUES (?, ?, ?)',
                ('user01', generate_password_hash('~user1'), 0)
            )
            
        conn.commit()
        cur.close()
        conn.close()
        print("SQLite Database initialized.")
        
        # 개별 DB -> 단일 통합 DB 마이그레이션 실행
        migrate_sqlite_to_unified()

# 앱 기동 시 데이터베이스 구조화
init_db()

def get_db():
    """요청 시 데이터베이스 세션 획득"""
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = DBConnection()
    return db

def get_main_db():
    """사용자 관리 및 코어 데이터베이스 동일하게 호출"""
    return get_db()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# 인증용 데코레이터 정의
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def api_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session or not session.get('is_admin'):
            flash('관리자 권한이 필요합니다.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# --- 라우트 정의 ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'username' in session:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        if not username or not password:
            flash('아이디와 비밀번호를 입력해주세요.', 'danger')
            return render_template('login.html')
            
        db = get_main_db()
        cursor = db.execute('SELECT * FROM users WHERE username = ?', (username,))
        user = cursor.fetchone()
        
        if user and check_password_hash(user['password'], password):
            session['username'] = user['username']
            session['is_admin'] = user['is_admin']
            flash(f'{username}님, 환영합니다!', 'success')
            return redirect(url_for('index'))
        else:
            flash('아이디 또는 비밀번호가 올바르지 않습니다.', 'danger')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('로그아웃 되었습니다.', 'success')
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/sw.js')
def sw():
    return app.send_static_file('sw.js')

@app.route('/manifest.json')
def manifest():
    return app.send_static_file('manifest.json')

@app.route('/manage')
@login_required
def manage():
    return render_template('manage.html')

@app.route('/history')
@login_required
def history():
    return render_template('history.html')

# --- 관리자(Admin) 전용 API 및 라우트 ---

@app.route('/admin')
@admin_required
def admin():
    return render_template('admin.html')

@app.route('/api/admin/users', methods=['GET', 'POST'])
@admin_required
def api_users():
    db = get_main_db()
    if request.method == 'GET':
        cursor = db.execute('SELECT id, username, is_admin, created_at FROM users ORDER BY created_at DESC')
        users = [dict(row) for row in cursor.fetchall()]
        return jsonify(users)
        
    elif request.method == 'POST':
        data = request.json
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        is_admin = 1 if data.get('is_admin') else 0
        
        if not username or not password:
            return jsonify({'error': '아이디와 비밀번호를 입력해주세요.'}), 400
            
        cursor = db.execute('SELECT id FROM users WHERE username = ?', (username,))
        if cursor.fetchone():
            return jsonify({'error': '이미 존재하는 아이디입니다.'}), 400
            
        try:
            db.execute(
                'INSERT INTO users (username, password, is_admin) VALUES (?, ?, ?)',
                (username, generate_password_hash(password), is_admin)
            )
            db.commit()
            return jsonify({'success': True, 'message': '사용자가 추가되었습니다.'}), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE', 'PUT'])
@admin_required
def handle_user(user_id):
    db = get_main_db()
    
    cursor = db.execute('SELECT username, is_admin FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    if not user:
        return jsonify({'error': '사용자를 찾을 수 없습니다.'}), 404
        
    if request.method == 'DELETE':
        # 본인 계정 삭제 시도 방지
        if user['username'] == session.get('username'):
            return jsonify({'error': '자기 자신은 삭제할 수 없습니다.'}), 400
            
        # admin 삭제 방지
        if user['username'] == 'admin':
            return jsonify({'error': '기본 관리자 계정(admin)은 삭제할 수 없습니다.'}), 400
            
        # 회원 태스크 및 로그 삭제
        db.execute('DELETE FROM tasks WHERE username = ?', (user['username'],))
        db.execute('DELETE FROM users WHERE id = ?', (user_id,))
        db.commit()
        return '', 204
        
    elif request.method == 'PUT':
        data = request.json
        password = data.get('password', '').strip()
        is_admin = 1 if data.get('is_admin') else 0
        
        if user['username'] == 'admin' and not is_admin:
            return jsonify({'error': '기본 관리자 계정(admin)의 관리자 권한을 해제할 수 없습니다.'}), 400
            
        if password:
            db.execute(
                'UPDATE users SET password = ?, is_admin = ? WHERE id = ?',
                (generate_password_hash(password), is_admin, user_id)
            )
        else:
            db.execute(
                'UPDATE users SET is_admin = ? WHERE id = ?',
                (is_admin, user_id)
            )
        db.commit()
        
        if user['username'] == session.get('username'):
            session['is_admin'] = is_admin
            
        return jsonify({'success': True, 'message': '사용자 정보가 수정되었습니다.'}), 200

# --- 루틴 태스크/로그 조회 및 설정 API ---

@app.route('/api/tasks', methods=['GET', 'POST'])
@api_login_required
def api_tasks():
    db = get_db()
    username = session.get('username')
    
    if request.method == 'GET':
        cursor = db.execute('SELECT * FROM tasks WHERE username = ? ORDER BY order_index ASC, created_at ASC', (username,))
        tasks = [dict(row) for row in cursor.fetchall()]
        return jsonify(tasks)
        
    elif request.method == 'POST':
        data = request.json
        name = data.get('name')
        start_date = data.get('start_date')
        time = data.get('time')
        if not name or not start_date or not time:
            return jsonify({'error': 'Missing data'}), 400
        
        if IS_POSTGRES:
            cursor = db.execute(
                'INSERT INTO tasks (username, name, start_date, time) VALUES (?, ?, ?, ?) RETURNING id',
                (username, name, start_date, time)
            )
            db.commit()
            task_id = cursor.fetchone()[0]
        else:
            cursor = db.execute(
                'INSERT INTO tasks (username, name, start_date, time) VALUES (?, ?, ?, ?)',
                (username, name, start_date, time)
            )
            db.commit()
            task_id = cursor.lastrowid
            
        return jsonify({'id': task_id, 'name': name, 'start_date': start_date, 'time': time}), 201

@app.route('/api/tasks/<int:task_id>', methods=['DELETE', 'PUT'])
@api_login_required
def handle_task(task_id):
    db = get_db()
    username = session.get('username')
    
    if request.method == 'DELETE':
        db.execute('''
            DELETE FROM task_logs 
            WHERE task_id IN (SELECT id FROM tasks WHERE id = ? AND username = ?)
        ''', (task_id, username))
        db.execute('DELETE FROM tasks WHERE id = ? AND username = ?', (task_id, username))
        db.commit()
        return '', 204
        
    elif request.method == 'PUT':
        data = request.json
        name = data.get('name')
        start_date = data.get('start_date')
        time = data.get('time')
        
        db.execute(
            'UPDATE tasks SET name = ?, start_date = ?, time = ? WHERE id = ? AND username = ?', 
            (name, start_date, time, task_id, username)
        )
        db.commit()
        return jsonify({'id': task_id, 'name': name, 'start_date': start_date, 'time': time}), 200

@app.route('/api/tasks/<int:task_id>/reset', methods=['POST'])
@api_login_required
def reset_task_logs(task_id):
    """특정 루틴의 수행 기록(task_logs)만 초기화 - 루틴명은 유지"""
    db = get_db()
    username = session.get('username')

    # 해당 태스크가 현재 로그인한 사용자 소유인지 검증
    cursor = db.execute('SELECT id, name FROM tasks WHERE id = ? AND username = ?', (task_id, username))
    task = cursor.fetchone()
    if not task:
        return jsonify({'error': '태스크를 찾을 수 없거나 권한이 없습니다.'}), 404

    try:
        db.execute('DELETE FROM task_logs WHERE task_id = ?', (task_id,))
        db.commit()
        task_name = task['name'] if hasattr(task, '__getitem__') else task[1]
        return jsonify({'success': True, 'message': f'[{task_name}]의 수행 기록이 초기화되었습니다.'}), 200
    except Exception as e:
        app.logger.error(f"Error resetting task logs for task_id={task_id}, user={username}: {e}")
        return jsonify({'error': f'수행 기록 초기화 중 오류가 발생했습니다: {str(e)}'}), 500

@app.route('/api/tasks/reorder', methods=['POST'])
@api_login_required
def reorder_tasks():
    db = get_db()
    username = session.get('username')
    data = request.json
    task_ids = data.get('task_ids', [])
    for idx, task_id in enumerate(task_ids):
        db.execute('UPDATE tasks SET order_index = ? WHERE id = ? AND username = ?', (idx, task_id, username))
    db.commit()
    return jsonify({'success': True})

@app.route('/api/logs', methods=['GET'])
@api_login_required
def get_logs():
    db = get_db()
    username = session.get('username')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    query = '''
        SELECT l.*, t.name, t.time 
        FROM task_logs l 
        JOIN tasks t ON l.task_id = t.id 
        WHERE t.username = ?
    '''
    params = [username]
    
    if start_date and end_date:
        query += ' AND l.date BETWEEN ? AND ?'
        params.extend([start_date, end_date])
        
    cursor = db.execute(query, params)
    logs = [dict(row) for row in cursor.fetchall()]
    return jsonify(logs)

@app.route('/api/tasks/today', methods=['GET'])
@api_login_required
def get_today_tasks():
    db = get_db()
    username = session.get('username')
    date_str = request.args.get('date') # YYYY-MM-DD
    if not date_str:
        date_str = datetime.now().strftime('%Y-%m-%d')
        
    query = '''
        SELECT t.*, COALESCE(l.is_completed, 0) as is_completed
        FROM tasks t
        LEFT JOIN task_logs l ON t.id = l.task_id AND l.date = ?
        WHERE t.username = ? AND t.start_date <= ?
        ORDER BY t.order_index ASC, t.created_at ASC
    '''
    cursor = db.execute(query, (date_str, username, date_str))
    tasks = [dict(row) for row in cursor.fetchall()]
    return jsonify(tasks)

@app.route('/api/logs/toggle', methods=['POST'])
@api_login_required
def toggle_log():
    db = get_db()
    username = session.get('username')
    data = request.json
    task_id = data.get('task_id')
    date_str = data.get('date')
    
    if not task_id or not date_str:
        return jsonify({'error': 'Missing data'}), 400
        
    cursor = db.execute('''
        SELECT l.id, l.is_completed 
        FROM task_logs l 
        JOIN tasks t ON l.task_id = t.id 
        WHERE l.task_id = ? AND l.date = ? AND t.username = ?
    ''', (task_id, date_str, username))
    log = cursor.fetchone()
    
    if log:
        new_status = 0 if log['is_completed'] else 1
        db.execute('UPDATE task_logs SET is_completed = ? WHERE id = ?', (new_status, log['id']))
    else:
        new_status = 1
        # 태스크 권한 소유 확인 후 입력
        chk = db.execute('SELECT id FROM tasks WHERE id = ? AND username = ?', (task_id, username))
        if chk.fetchone():
            db.execute('INSERT INTO task_logs (task_id, date, is_completed) VALUES (?, ?, ?)', (task_id, date_str, new_status))
        else:
            return jsonify({'error': 'Unauthorized'}), 403
        
    db.commit()
    return jsonify({'task_id': task_id, 'date': date_str, 'is_completed': new_status})

@app.route('/api/stats', methods=['GET'])
@api_login_required
def get_stats():
    db = get_db()
    username = session.get('username')
    
    query = '''
        SELECT 
            t.id, t.name, t.start_date,
            COUNT(l.id) as total_logged_days,
            SUM(CASE WHEN l.is_completed = 1 THEN 1 ELSE 0 END) as completed_days
        FROM tasks t
        LEFT JOIN task_logs l ON t.id = l.task_id
        WHERE t.username = ?
        GROUP BY t.id
        ORDER BY t.order_index ASC, t.created_at ASC
    '''
    cursor = db.execute(query, (username,))
    stats = []
    
    today_date = datetime.now().strftime('%Y-%m-%d')
    
    for row in cursor.fetchall():
        stat = dict(row)
        start_date_obj = datetime.strptime(stat['start_date'], '%Y-%m-%d')
        today_obj = datetime.strptime(today_date, '%Y-%m-%d')
        
        days_since_start = (today_obj - start_date_obj).days + 1
        if days_since_start < 0:
            days_since_start = 0
            
        stat['total_days_since_start'] = days_since_start
        stat['completed_days'] = stat['completed_days'] or 0
        stat['missed_days'] = days_since_start - stat['completed_days']
        if stat['missed_days'] < 0:
            stat['missed_days'] = 0
            
        stats.append(stat)
        
    return jsonify(stats)

@app.route('/api/history', methods=['GET'])
@api_login_required
def api_history():
    db = get_db()
    username = session.get('username')
    query = '''
        SELECT l.date, l.is_completed, t.name, t.order_index 
        FROM task_logs l
        JOIN tasks t ON l.task_id = t.id
        WHERE t.username = ?
        ORDER BY l.date DESC
    '''
    cursor = db.execute(query, (username,))
    logs = [dict(row) for row in cursor.fetchall()]
    
    history_data = {}
    for log in logs:
        month = log['date'][:7] # YYYY-MM
        if month not in history_data:
            history_data[month] = {'total': 0, 'completed': 0, 'tasks': {}}
            
        history_data[month]['total'] += 1
        if log['is_completed'] == 1:
            history_data[month]['completed'] += 1
            
        task_name = log['name']
        if task_name not in history_data[month]['tasks']:
            history_data[month]['tasks'][task_name] = {'total': 0, 'completed': 0, 'order_index': log['order_index']}
            
        history_data[month]['tasks'][task_name]['total'] += 1
        if log['is_completed'] == 1:
            history_data[month]['tasks'][task_name]['completed'] += 1
            
    result = []
    for month, data in history_data.items():
        rate = int((data['completed'] / data['total']) * 100) if data['total'] > 0 else 0
        task_list = []
        for t_name, t_data in data['tasks'].items():
            t_rate = int((t_data['completed'] / t_data['total']) * 100) if t_data['total'] > 0 else 0
            task_list.append({
                'name': t_name,
                'total': t_data['total'],
                'completed': t_data['completed'],
                'rate': t_rate,
                'order_index': t_data['order_index']
            })
            
        task_list.sort(key=lambda x: (x['order_index'] if x['order_index'] is not None else 999))
            
        result.append({
            'month': month,
            'total': data['total'],
            'completed': data['completed'],
            'rate': rate,
            'tasks': task_list
        })
        
    result.sort(key=lambda x: x['month'], reverse=True)
    return jsonify(result)

# --- 백업 및 복원 (내보내기 / 가져오기) API ---

@app.route('/api/backup/export', methods=['GET'])
@login_required
def export_backup():
    username = session.get('username')
    db = get_db()
    
    # 임시 SQLite DB 파일 경로 생성
    temp_dir = tempfile.gettempdir()
    temp_file_name = f"temp_export_{username}_{datetime.now().strftime('%Y%m%d%H%M%S')}.db"
    temp_file_path = os.path.join(temp_dir, temp_file_name)
    
    try:
        temp_conn = sqlite3.connect(temp_file_path)
        temp_cur = temp_conn.cursor()
        
        # 다운로드받을 개별 사용자용 SQLite 테이블 생성
        temp_cur.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                start_date TEXT NOT NULL,
                time TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                order_index INTEGER DEFAULT 0
            )
        ''')
        temp_cur.execute('''
            CREATE TABLE IF NOT EXISTS task_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                is_completed INTEGER DEFAULT 0,
                FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE
            )
        ''')
        temp_conn.commit()
        
        # 현재 로그인된 사용자의 태스크 획득
        cursor = db.execute(
            'SELECT id, name, start_date, time, created_at, order_index FROM tasks WHERE username = ?',
            (username,)
        )
        tasks = cursor.fetchall()
        
        for t in tasks:
            old_task_id = t['id']
            # 임시 SQLite DB에 태스크 삽입
            temp_cur.execute(
                'INSERT INTO tasks (name, start_date, time, created_at, order_index) VALUES (?, ?, ?, ?, ?)',
                (t['name'], t['start_date'], t['time'], t['created_at'], t['order_index'])
            )
            new_task_id = temp_cur.lastrowid
            
            # 해당 태스크의 완료 로그 획득 및 삽입
            logs_cursor = db.execute(
                'SELECT date, is_completed FROM task_logs WHERE task_id = ?',
                (old_task_id,)
            )
            logs = logs_cursor.fetchall()
            for log in logs:
                temp_cur.execute(
                    'INSERT INTO task_logs (task_id, date, is_completed) VALUES (?, ?, ?)',
                    (new_task_id, log['date'], log['is_completed'])
                )
        
        temp_conn.commit()
        temp_conn.close()
        
        # 응답이 완료된 후 임시 파일을 안전하게 삭제하기 위한 데코레이터
        @after_this_request
        def remove_file(response):
            try:
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
            except Exception as e:
                app.logger.error(f"Error removing temp export file: {e}")
            return response
            
        return send_file(
            temp_file_path,
            as_attachment=True,
            download_name=f"routine_{username}.db",
            mimetype="application/x-sqlite3"
        )
        
    except Exception as e:
        if 'temp_conn' in locals():
            try:
                temp_conn.close()
            except:
                pass
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except:
                pass
        return jsonify({'error': str(e)}), 500

@app.route('/api/backup/import', methods=['POST'])
@login_required
def import_backup():
    username = session.get('username')
    db = get_db()
    
    if 'file' not in request.files:
        return jsonify({'error': '업로드된 파일이 없습니다.'}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '선택된 파일명이 비어 있습니다.'}), 400
        
    if not file.filename.endswith('.db'):
        return jsonify({'error': '.db 확장자 파일만 지원합니다.'}), 400
        
    temp_dir = tempfile.gettempdir()
    temp_file_name = f"temp_import_{username}_{datetime.now().strftime('%Y%m%d%H%M%S')}.db"
    temp_file_path = os.path.join(temp_dir, temp_file_name)
    
    try:
        file.save(temp_file_path)
        
        # 파일 구조 검증
        uploaded_conn = sqlite3.connect(temp_file_path)
        uploaded_cur = uploaded_conn.cursor()
        
        uploaded_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'")
        has_tasks = uploaded_cur.fetchone()
        uploaded_cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='task_logs'")
        has_logs = uploaded_cur.fetchone()
        
        if not has_tasks or not has_logs:
            uploaded_conn.close()
            os.remove(temp_file_path)
            return jsonify({'error': '유효하지 않은 백업 파일입니다. 필수 테이블 구조(tasks, task_logs)가 없습니다.'}), 400
            
        # 백업 DB에서 데이터 읽기
        uploaded_cur.execute("SELECT id, name, start_date, time, created_at, order_index FROM tasks")
        tasks = uploaded_cur.fetchall()
        
        # 기존 회원 데이터 삭제 (트랜잭션 세션 보장)
        # 1. 태스크 완료 로그 삭제
        db.execute('DELETE FROM task_logs WHERE task_id IN (SELECT id FROM tasks WHERE username = ?)', (username,))
        # 2. 태스크 삭제
        db.execute('DELETE FROM tasks WHERE username = ?', (username,))
        
        # 백업 데이터 복사 시작
        for t in tasks:
            old_task_id = t[0]
            name = t[1]
            start_date = t[2]
            time = t[3]
            created_at = t[4]
            order_index = t[5]
            
            # 신규 태스크 삽입 후 생성된 새 ID 획득
            if IS_POSTGRES:
                cursor = db.execute('''
                    INSERT INTO tasks (username, name, start_date, time, created_at, order_index)
                    VALUES (?, ?, ?, ?, ?, ?) RETURNING id
                ''', (username, name, start_date, time, created_at, order_index))
                new_task_id = cursor.fetchone()[0]
            else:
                cursor = db.execute('''
                    INSERT INTO tasks (username, name, start_date, time, created_at, order_index)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (username, name, start_date, time, created_at, order_index))
                new_task_id = cursor.lastrowid
                
            # 해당 태스크의 수행 이력(로그) 복사
            uploaded_cur.execute("SELECT date, is_completed FROM task_logs WHERE task_id = ?", (old_task_id,))
            logs = uploaded_cur.fetchall()
            for log in logs:
                db.execute(
                    'INSERT INTO task_logs (task_id, date, is_completed) VALUES (?, ?, ?)',
                    (new_task_id, log[0], log[1])
                )
                
        db.commit()
        uploaded_conn.close()
        os.remove(temp_file_path)
        
        return jsonify({'success': True, 'message': '가져오기가 성공적으로 완료되었습니다.'}), 200
        
    except Exception as e:
        if 'uploaded_conn' in locals():
            try:
                uploaded_conn.close()
            except:
                pass
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except:
                pass
        # 에러 발생 시 트랜잭션 롤백은 DBConnection 내부나 SQLAlchemy 등에서 자동으로 연계되거나 close될 때 처리
        return jsonify({'error': f'복원 처리 중 오류가 발생했습니다: {str(e)}'}), 500

@app.route('/api/backup/reset', methods=['POST'])
@login_required
def reset_backup():
    username = session.get('username')
    db = get_db()
    try:
        # 루틴명(tasks)은 그대로 유지하고 태스크 실행 여부/수행 기록(task_logs)만 초기화
        db.execute('DELETE FROM task_logs WHERE task_id IN (SELECT id FROM tasks WHERE username = ?)', (username,))
        db.commit()
        return jsonify({'success': True, 'message': '루틴명은 유지되고 모든 태스크의 실행 여부(수행 기록)가 성공적으로 초기화되었습니다.'}), 200
    except Exception as e:
        app.logger.error(f"Error resetting user data for {username}: {e}")
        return jsonify({'error': f'실행 기록 초기화 중 오류가 발생했습니다: {str(e)}'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5100))
    app.run(debug=True, host='0.0.0.0', port=port)
