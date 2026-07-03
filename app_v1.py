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
# ==============================================================================

import sqlite3
from flask import Flask, render_template, request, jsonify, g, session, redirect, url_for, flash
import os
import shutil
from datetime import datetime
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
# 세션을 유지하기 위한 시크릿 키 설정
app.secret_key = 'routine_tracker_secret_key_change_me_in_production'

# DB 경로 및 디렉토리 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Render Persistent Disk 마운트 경로(/opt/render/project/src/data) 자동 감지 및 설정
RENDER_DATA_DIR = '/opt/render/project/src/data'
if os.path.exists(RENDER_DATA_DIR):
    DB_DIR = RENDER_DATA_DIR
else:
    DB_DIR = BASE_DIR

USERS_DIR = os.path.join(DB_DIR, 'users')
MAIN_DB = os.path.join(DB_DIR, 'routine_main.db')
OLD_DB = os.path.join(BASE_DIR, 'routine.db')

def init_user_db(db):
    """회원별 독립 데이터베이스의 테이블 초기화"""
    db.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            start_date TEXT NOT NULL,
            time TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            order_index INTEGER DEFAULT 0
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS task_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            is_completed INTEGER DEFAULT 0,
            FOREIGN KEY (task_id) REFERENCES tasks (id)
        )
    ''')
    try:
        db.execute('ALTER TABLE tasks ADD COLUMN order_index INTEGER DEFAULT 0')
    except sqlite3.OperationalError:
        pass # Column already exists
    db.commit()

def init_main_db():
    """메인 DB 생성 및 회원 마이그레이션 로직"""
    if not os.path.exists(USERS_DIR):
        os.makedirs(USERS_DIR)
        
    conn = sqlite3.connect(MAIN_DB)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    
    # 2. 관리자는 admin, 초기비번은 ~admin1
    cursor.execute('SELECT * FROM users WHERE username = ?', ('admin',))
    if not cursor.fetchone():
        cursor.execute(
            'INSERT INTO users (username, password, is_admin) VALUES (?, ?, ?)',
            ('admin', generate_password_hash('~admin1'), 1)
        )
        conn.commit()
        print("Admin account created.")
        
    # 4. 현재 구현된 데이터 DB는 user01, 비밀번호 ~user1에게 마이그레이션
    cursor.execute('SELECT * FROM users WHERE username = ?', ('user01',))
    if not cursor.fetchone():
        cursor.execute(
            'INSERT INTO users (username, password, is_admin) VALUES (?, ?, ?)',
            ('user01', generate_password_hash('~user1'), 0)
        )
        conn.commit()
        print("user01 account created.")
        
        # 기존 routine.db가 존재하면 user01의 독립 DB로 복사 마이그레이션 수행
        user01_db_path = os.path.join(USERS_DIR, 'routine_user01.db')
        if os.path.exists(OLD_DB):
            try:
                shutil.copy(OLD_DB, user01_db_path)
                print(f"Successfully migrated {OLD_DB} to {user01_db_path}")
                # 마이그레이션 후 안전하게 원본 파일명 변경
                backup_path = OLD_DB + '.backup'
                os.rename(OLD_DB, backup_path)
                print(f"Renamed old database to {backup_path}")
            except Exception as e:
                print(f"Migration error: {e}")
        else:
            print("Old database routine.db not found. Skip physical migration.")
            
    conn.close()

# 앱 실행 시 메인 DB 및 마이그레이션 처리 실행
init_main_db()

def get_db():
    """로그인한 사용자의 독립된 SQLite 데이터베이스 커넥션 획득"""
    username = session.get('username')
    if not username:
        return get_main_db()
        
    db = getattr(g, '_database', None)
    if db is None:
        db_path = os.path.join(USERS_DIR, f'routine_{username}.db')
        db = g._database = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        init_user_db(db)
    return db

def get_main_db():
    """사용자 관리용 메인 데이터베이스 커넥션 획득"""
    db = getattr(g, '_main_database', None)
    if db is None:
        db = g._main_database = sqlite3.connect(MAIN_DB)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()
    main_db = getattr(g, '_main_database', None)
    if main_db is not None:
        main_db.close()

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
            
            # 신규 유저 DB 생성 및 초기화
            user_db_path = os.path.join(USERS_DIR, f'routine_{username}.db')
            conn = sqlite3.connect(user_db_path)
            init_user_db(conn)
            conn.close()
            
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
            
        db.execute('DELETE FROM users WHERE id = ?', (user_id,))
        db.commit()
        
        # 해당 유저의 DB 파일도 제거하여 리소스 삭제
        user_db_path = os.path.join(USERS_DIR, f'routine_{user["username"]}.db')
        if os.path.exists(user_db_path):
            try:
                os.remove(user_db_path)
            except Exception as e:
                print(f"Error removing user DB file: {e}")
                
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

# --- 루틴 태스크/로그 조회 및 설정 API (회원 개별 DB에서 작동) ---

@app.route('/api/tasks', methods=['GET', 'POST'])
@api_login_required
def api_tasks():
    db = get_db()
    if request.method == 'GET':
        cursor = db.execute('SELECT * FROM tasks ORDER BY order_index ASC, created_at ASC')
        tasks = [dict(row) for row in cursor.fetchall()]
        return jsonify(tasks)
    elif request.method == 'POST':
        data = request.json
        name = data.get('name')
        start_date = data.get('start_date')
        time = data.get('time')
        if not name or not start_date or not time:
            return jsonify({'error': 'Missing data'}), 400
        
        cursor = db.execute('INSERT INTO tasks (name, start_date, time) VALUES (?, ?, ?)', (name, start_date, time))
        db.commit()
        return jsonify({'id': cursor.lastrowid, 'name': name, 'start_date': start_date, 'time': time}), 201

@app.route('/api/tasks/<int:task_id>', methods=['DELETE', 'PUT'])
@api_login_required
def handle_task(task_id):
    db = get_db()
    if request.method == 'DELETE':
        db.execute('DELETE FROM task_logs WHERE task_id = ?', (task_id,))
        db.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
        db.commit()
        return '', 204
    elif request.method == 'PUT':
        data = request.json
        name = data.get('name')
        start_date = data.get('start_date')
        time = data.get('time')
        
        db.execute('UPDATE tasks SET name = ?, start_date = ?, time = ? WHERE id = ?', 
                   (name, start_date, time, task_id))
        db.commit()
        return jsonify({'id': task_id, 'name': name, 'start_date': start_date, 'time': time}), 200

@app.route('/api/tasks/reorder', methods=['POST'])
@api_login_required
def reorder_tasks():
    db = get_db()
    data = request.json
    task_ids = data.get('task_ids', [])
    for idx, task_id in enumerate(task_ids):
        db.execute('UPDATE tasks SET order_index = ? WHERE id = ?', (idx, task_id))
    db.commit()
    return jsonify({'success': True})

@app.route('/api/logs', methods=['GET'])
@api_login_required
def get_logs():
    db = get_db()
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    
    query = '''
        SELECT l.*, t.name, t.time 
        FROM task_logs l 
        JOIN tasks t ON l.task_id = t.id 
    '''
    params = []
    
    if start_date and end_date:
        query += ' WHERE l.date BETWEEN ? AND ?'
        params.extend([start_date, end_date])
        
    cursor = db.execute(query, params)
    logs = [dict(row) for row in cursor.fetchall()]
    return jsonify(logs)

@app.route('/api/tasks/today', methods=['GET'])
@api_login_required
def get_today_tasks():
    db = get_db()
    date_str = request.args.get('date') # YYYY-MM-DD
    if not date_str:
        date_str = datetime.now().strftime('%Y-%m-%d')
        
    query = '''
        SELECT t.*, COALESCE(l.is_completed, 0) as is_completed
        FROM tasks t
        LEFT JOIN task_logs l ON t.id = l.task_id AND l.date = ?
        WHERE t.start_date <= ?
        ORDER BY t.order_index ASC, t.created_at ASC
    '''
    cursor = db.execute(query, (date_str, date_str))
    tasks = [dict(row) for row in cursor.fetchall()]
    return jsonify(tasks)

@app.route('/api/logs/toggle', methods=['POST'])
@api_login_required
def toggle_log():
    db = get_db()
    data = request.json
    task_id = data.get('task_id')
    date_str = data.get('date')
    
    if not task_id or not date_str:
        return jsonify({'error': 'Missing data'}), 400
        
    cursor = db.execute('SELECT id, is_completed FROM task_logs WHERE task_id = ? AND date = ?', (task_id, date_str))
    log = cursor.fetchone()
    
    if log:
        new_status = 0 if log['is_completed'] else 1
        db.execute('UPDATE task_logs SET is_completed = ? WHERE id = ?', (new_status, log['id']))
    else:
        new_status = 1
        db.execute('INSERT INTO task_logs (task_id, date, is_completed) VALUES (?, ?, ?)', (task_id, date_str, new_status))
        
    db.commit()
    return jsonify({'task_id': task_id, 'date': date_str, 'is_completed': new_status})

@app.route('/api/stats', methods=['GET'])
@api_login_required
def get_stats():
    db = get_db()
    
    query = '''
        SELECT 
            t.id, t.name, t.start_date,
            COUNT(l.id) as total_logged_days,
            SUM(CASE WHEN l.is_completed = 1 THEN 1 ELSE 0 END) as completed_days
        FROM tasks t
        LEFT JOIN task_logs l ON t.id = l.task_id
        GROUP BY t.id
        ORDER BY t.order_index ASC, t.created_at ASC
    '''
    cursor = db.execute(query)
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
    query = '''
        SELECT l.date, l.is_completed, t.name, t.order_index 
        FROM task_logs l
        JOIN tasks t ON l.task_id = t.id
        ORDER BY l.date DESC
    '''
    cursor = db.execute(query)
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5100))
    app.run(debug=True, host='0.0.0.0', port=port)
