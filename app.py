import sqlite3
# pyrefly: ignore [missing-import]
from flask import Flask, render_template, request, jsonify, g
import os
from datetime import datetime

app = Flask(__name__)
DATABASE = 'routine.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                start_date TEXT NOT NULL,
                time TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

# Ensure DB is created before first request
init_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/sw.js')
def sw():
    return app.send_static_file('sw.js')

@app.route('/manifest.json')
def manifest():
    return app.send_static_file('manifest.json')

@app.route('/manage')
def manage():
    return render_template('manage.html')

@app.route('/history')
def history():
    return render_template('history.html')

@app.route('/api/tasks', methods=['GET', 'POST'])
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
def reorder_tasks():
    db = get_db()
    data = request.json
    task_ids = data.get('task_ids', [])
    for idx, task_id in enumerate(task_ids):
        db.execute('UPDATE tasks SET order_index = ? WHERE id = ?', (idx, task_id))
    db.commit()
    return jsonify({'success': True})

@app.route('/api/logs', methods=['GET'])
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
def get_today_tasks():
    db = get_db()
    date_str = request.args.get('date') # YYYY-MM-DD
    if not date_str:
        date_str = datetime.now().strftime('%Y-%m-%d')
        
    # Get all tasks that started on or before today
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
def toggle_log():
    db = get_db()
    data = request.json
    task_id = data.get('task_id')
    date_str = data.get('date')
    
    if not task_id or not date_str:
        return jsonify({'error': 'Missing data'}), 400
        
    # Check if log exists
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
def get_stats():
    db = get_db()
    
    # Task별 List, 실행일, 미실행일 대쉬보드 (per task statistics)
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
        # Approximate total days since start date (for simple stats, ignoring future dates if any)
        # To be accurate, we'd need to calculate date differences in python
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
def api_history():
    db = get_db()
    # Get all logs and group by month
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
            
        # Sort tasks by order_index
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

@app.route('/api/backup/reset', methods=['POST'])
def reset_backup():
    db = get_db()
    try:
        db.execute('DELETE FROM task_logs')
        db.execute('DELETE FROM tasks')
        db.commit()
        return jsonify({'success': True, 'message': '모든 루틴 태스크와 수행 기록이 성공적으로 초기화되었습니다.'}), 200
    except Exception as e:
        app.logger.error(f"Error resetting data: {e}")
        return jsonify({'error': f'데이터 초기화 중 오류가 발생했습니다: {str(e)}'}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5100)
#    app.run(host='172.25.160.1', port=5100, debug=True)
