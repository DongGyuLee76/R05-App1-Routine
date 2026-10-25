document.addEventListener('DOMContentLoaded', () => {
    const currentPath = window.location.pathname;

    if (currentPath === '/manage') {
        initManagePage();
    } else if (currentPath === '/') {
        initDashboard();
    } else if (currentPath === '/history') {
        initHistory();
    }
});

// --- API Helpers ---
async function fetchTasks() {
    const res = await fetch('/api/tasks');
    return res.json();
}

async function fetchTodayTasks(dateStr) {
    const res = await fetch(`/api/tasks/today?date=${dateStr}`);
    return res.json();
}

async function fetchLogs(startDate, endDate) {
    const res = await fetch(`/api/logs?start_date=${startDate}&end_date=${endDate}`);
    return res.json();
}

async function fetchStats() {
    const res = await fetch('/api/stats');
    return res.json();
}

async function toggleLog(taskId, dateStr) {
    const res = await fetch('/api/logs/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId, date: dateStr })
    });
    return res.json();
}

// --- Manage Page ---
function initManagePage() {
    const form = document.getElementById('addTaskForm');
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const name = document.getElementById('taskName').value;
            const startDate = document.getElementById('startDate').value;
            const hour = document.getElementById('taskHour').value || 0;
            const minute = document.getElementById('taskMinute').value || 0;
            
            let timeStr = [];
            if (hour > 0) timeStr.push(`${hour}시간`);
            if (minute > 0) timeStr.push(`${minute}분`);
            const time = timeStr.length > 0 ? timeStr.join(' ') : '0분';

            const res = await fetch('/api/tasks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, start_date: startDate, time })
            });

            if (res.ok) {
                form.reset();
                loadManageTasks();
            } else {
                alert('태스크 추가에 실패했습니다.');
            }
        });
    }

    const editForm = document.getElementById('editTaskForm');
    if (editForm) {
        editForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const id = document.getElementById('editTaskId').value;
            const name = document.getElementById('editTaskName').value;
            const startDate = document.getElementById('editStartDate').value;
            const hour = document.getElementById('editTaskHour').value || 0;
            const minute = document.getElementById('editTaskMinute').value || 0;
            
            let timeStr = [];
            if (hour > 0) timeStr.push(`${hour}시간`);
            if (minute > 0) timeStr.push(`${minute}분`);
            const time = timeStr.length > 0 ? timeStr.join(' ') : '0분';

            const res = await fetch(`/api/tasks/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, start_date: startDate, time })
            });

            if (res.ok) {
                closeEditModal();
                loadManageTasks();
            } else {
                alert('태스크 수정에 실패했습니다.');
            }
        });
    }

    loadManageTasks();
}

async function loadManageTasks() {
    const tbody = document.getElementById('taskListBody');
    if (!tbody) return;

    const tasks = await fetchTasks();
    tbody.innerHTML = '';

    if (tasks.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;">태스크가 없습니다.</td></tr>';
        return;
    }

    tasks.forEach(task => {
        const tr = document.createElement('tr');
        tr.dataset.id = task.id;
        tr.innerHTML = `
            <td style="cursor: grab;"><strong>≡ ${task.name}</strong></td>
            <td>${task.start_date}</td>
            <td>${task.time}</td>
            <td style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
                <button class="btn btn-outline" style="padding: 0.25rem 0.5rem; font-size: 0.75rem;" onclick='openEditModal(${JSON.stringify(task).replace(/'/g, "&#39;")})'>수정 (Edit)</button>
                <button class="btn btn-danger" style="padding: 0.25rem 0.5rem; font-size: 0.75rem;" onclick="deleteTask(${task.id})">삭제 (Delete)</button>
                <button class="btn btn-outline" style="padding: 0.25rem 0.5rem; font-size: 0.75rem; border-color: #f59e0b; color: #d97706;" onclick="resetTask(${task.id}, '${task.name.replace(/'/g, "\\'")}')">🔄 초기화</button>
            </td>
        `;
        tbody.appendChild(tr);
    });

    if (window.Sortable) {
        new Sortable(tbody, {
            animation: 150,
            ghostClass: 'sortable-ghost',
            onEnd: async function (evt) {
                const itemEls = tbody.querySelectorAll('tr[data-id]');
                const taskIds = Array.from(itemEls).map(el => parseInt(el.dataset.id));
                
                await fetch('/api/tasks/reorder', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ task_ids: taskIds })
                });
            }
        });
    }
}

window.resetTask = async function(id, name) {
    if (!confirm(`[${name}]의 수행 기록(체크 이력)을 초기화하시겠습니까?\n루틴명은 유지되고 실행 여부 기록만 삭제됩니다.`)) return;

    try {
        const res = await fetch(`/api/tasks/${id}/reset`, { method: 'POST' });
        const data = await res.json();
        if (res.ok && data.success) {
            alert(data.message || '수행 기록이 초기화되었습니다.');
            loadManageTasks();
        } else {
            alert('초기화 실패: ' + (data.error || '알 수 없는 오류'));
        }
    } catch (err) {
        console.error(err);
        alert('네트워크 오류가 발생했습니다.');
    }
};

window.deleteTask = async function(id) {
    if (confirm('정말로 삭제하시겠습니까?')) {
        const res = await fetch(`/api/tasks/${id}`, { method: 'DELETE' });
        if (res.ok) {
            loadManageTasks();
        }
    }
};

window.openEditModal = function(task) {
    document.getElementById('editTaskId').value = task.id;
    document.getElementById('editTaskName').value = task.name;
    document.getElementById('editStartDate').value = task.start_date;
    
    let h = ''; let m = '';
    const timeStr = task.time || '';
    const hMatch = timeStr.match(/(\d+)시간/);
    const mMatch = timeStr.match(/(\d+)분/);
    if (hMatch) h = hMatch[1];
    if (mMatch) m = mMatch[1];
    
    document.getElementById('editTaskHour').value = h;
    document.getElementById('editTaskMinute').value = m;
    
    document.getElementById('editModal').style.display = 'flex';
};

window.closeEditModal = function() {
    document.getElementById('editModal').style.display = 'none';
};

// --- Dashboard ---
let currentDate = new Date();
let selectedDateStr = formatDate(new Date());

function formatDate(date) {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, '0');
    const d = String(date.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
}

async function initDashboard() {
    document.getElementById('prevMonth').addEventListener('click', () => {
        currentDate.setMonth(currentDate.getMonth() - 1);
        renderCalendar();
    });
    document.getElementById('nextMonth').addEventListener('click', () => {
        currentDate.setMonth(currentDate.getMonth() + 1);
        renderCalendar();
    });

    await renderCalendar();
    await loadTodayTasks(selectedDateStr);
    await loadStats();
}

async function renderCalendar() {
    const y = currentDate.getFullYear();
    const m = currentDate.getMonth();
    
    document.getElementById('currentMonthLabel').textContent = `${y}년 ${m + 1}월`;

    const firstDay = new Date(y, m, 1).getDay();
    const daysInMonth = new Date(y, m + 1, 0).getDate();

    const startDateStr = formatDate(new Date(y, m, 1));
    const endDateStr = formatDate(new Date(y, m, daysInMonth));

    const logs = await fetchLogs(startDateStr, endDateStr);
    
    // Group logs by date
    const logsByDate = {};
    logs.forEach(log => {
        if (!logsByDate[log.date]) {
            logsByDate[log.date] = [];
        }
        logsByDate[log.date].push(log);
    });

    const tasks = await fetchTasks(); // To know which tasks exist and started before a date

    const grid = document.getElementById('calendarGrid');
    
    // Remove old days (keep headers)
    const headers = grid.querySelectorAll('.calendar-day-header');
    grid.innerHTML = '';
    headers.forEach(h => grid.appendChild(h));

    // Empty spaces
    for (let i = 0; i < firstDay; i++) {
        const div = document.createElement('div');
        div.className = 'calendar-day empty';
        grid.appendChild(div);
    }

    const todayStr = formatDate(new Date());

    // Days
    for (let i = 1; i <= daysInMonth; i++) {
        const dateStr = formatDate(new Date(y, m, i));
        const div = document.createElement('div');
        div.className = 'calendar-day';
        if (dateStr === todayStr) div.classList.add('today');
        if (dateStr === selectedDateStr) div.style.borderColor = 'var(--primary-color)';

        div.innerHTML = `<div class="calendar-date">${i}</div>`;
        
        const tasksContainer = document.createElement('div');
        tasksContainer.className = 'calendar-tasks';

        // Get tasks that are active on this date
        const activeTasks = tasks.filter(t => t.start_date <= dateStr);
        
        // Find logs for this date
        const dayLogs = logsByDate[dateStr] || [];

        activeTasks.forEach(task => {
            const log = dayLogs.find(l => l.task_id === task.id);
            const isCompleted = log && log.is_completed === 1;
            const star = document.createElement('span');
            star.className = `star ${isCompleted ? 'filled' : ''}`;
            star.innerHTML = '★';
            star.title = task.name;
            star.onclick = async (e) => {
                e.stopPropagation();
                await toggleLog(task.id, dateStr);
                renderCalendar();
                if(dateStr === selectedDateStr) {
                    loadTodayTasks(selectedDateStr);
                }
                loadStats();
            };
            tasksContainer.appendChild(star);
        });

        div.appendChild(tasksContainer);
        
        div.onclick = () => {
            selectedDateStr = dateStr;
            renderCalendar();
            loadTodayTasks(dateStr);
        };

        grid.appendChild(div);
    }
}

async function loadTodayTasks(dateStr) {
    const list = document.getElementById('todayTasksList');
    const title = document.getElementById('todayTitle');
    title.textContent = `${dateStr} 할 일 (Tasks)`;
    list.innerHTML = '<p style="color: var(--text-secondary); text-align: center; padding: 1rem;">로딩 중...</p>';
    
    const tasks = await fetchTodayTasks(dateStr);
    list.innerHTML = '';

    if (tasks.length === 0) {
        list.innerHTML = '<p style="color: var(--text-secondary); text-align: center; padding: 1rem;">이 날짜에 예정된 태스크가 없습니다.</p>';
        return;
    }

    tasks.forEach(task => {
        const item = document.createElement('div');
        item.className = 'task-item';
        item.dataset.id = task.id;
        
        const isCompleted = task.is_completed === 1;

        item.innerHTML = `
            <div class="task-info">
                <div class="task-name" style="${isCompleted ? 'text-decoration: line-through; color: var(--text-secondary);' : ''}">${task.name}</div>
                <div class="task-meta">${task.time}</div>
            </div>
            <div>
                <button class="btn ${isCompleted ? 'btn-success' : 'btn-outline'}" onclick="handleToggle(${task.id}, '${dateStr}')">
                    ${isCompleted ? '완료됨 (Done)' : '완료하기 (Complete)'}
                </button>
            </div>
        `;
        list.appendChild(item);
    });

    if (window.Sortable) {
        new Sortable(list, {
            animation: 150,
            ghostClass: 'sortable-ghost',
            onEnd: async function (evt) {
                const itemEls = list.querySelectorAll('.task-item');
                const taskIds = Array.from(itemEls).map(el => parseInt(el.dataset.id));
                
                await fetch('/api/tasks/reorder', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ task_ids: taskIds })
                });
                
                // Re-render calendar and stats to reflect new order
                await renderCalendar();
                await loadStats();
            }
        });
    }
}

window.handleToggle = async function(taskId, dateStr) {
    await toggleLog(taskId, dateStr);
    await loadTodayTasks(dateStr);
    await renderCalendar();
    await loadStats();
};

async function loadStats() {
    const list = document.getElementById('statsList');
    if (!list) return;

    const stats = await fetchStats();
    list.innerHTML = '';

    if (stats.length === 0) {
        list.innerHTML = '<p style="color: var(--text-secondary); text-align: center; padding: 1rem;">통계 데이터가 없습니다.</p>';
        return;
    }

    let totalDays = 0;
    let totalCompleted = 0;
    let totalMissed = 0;

    stats.forEach(stat => {
        totalDays += stat.total_days_since_start;
        totalCompleted += stat.completed_days;
        totalMissed += stat.missed_days;
    });

    const overallRate = totalDays > 0 ? Math.round((totalCompleted / totalDays) * 100) : 0;

    const overallDiv = document.createElement('div');
    overallDiv.style.marginBottom = '2rem';
    overallDiv.style.paddingBottom = '1.5rem';
    overallDiv.style.borderBottom = '2px solid var(--border-color)';
    overallDiv.innerHTML = `
        <div style="display:flex; justify-content:space-between; margin-bottom:0.5rem; align-items:center;">
            <strong style="font-size:1.125rem; color:var(--primary-color);">🏆 전체 태스크 종합 (Overall)</strong>
            <span class="badge ${overallRate >= 80 ? 'badge-success' : 'badge-neutral'}">총 달성률 ${overallRate}%</span>
        </div>
        <div class="stat-grid" style="margin-top:0;">
            <div class="stat-box" style="padding:0.75rem 0.5rem; background:var(--card-bg);">
                <div class="stat-value" style="font-size:1.5rem;">${totalDays}</div>
                <div class="stat-label">전체 합계 (Days)</div>
            </div>
            <div class="stat-box" style="padding:0.75rem 0.5rem; background:var(--card-bg);">
                <div class="stat-value" style="font-size:1.5rem; color:var(--success-color);">${totalCompleted}</div>
                <div class="stat-label">총 실행 (Done)</div>
            </div>
            <div class="stat-box" style="padding:0.75rem 0.5rem; background:var(--card-bg);">
                <div class="stat-value" style="font-size:1.5rem; color:var(--danger-color);">${totalMissed}</div>
                <div class="stat-label">총 미실행 (Missed)</div>
            </div>
        </div>
    `;
    list.appendChild(overallDiv);

    stats.forEach(stat => {
        const total = stat.total_days_since_start;
        const rate = total > 0 ? Math.round((stat.completed_days / total) * 100) : 0;
        
        const div = document.createElement('div');
        div.style.marginBottom = '1.5rem';
        div.innerHTML = `
            <div style="display:flex; justify-content:space-between; margin-bottom:0.5rem; align-items:center;">
                <strong>${stat.name}</strong>
                <span class="badge ${rate >= 80 ? 'badge-success' : 'badge-neutral'}">달성률 ${rate}%</span>
            </div>
            <div class="stat-grid" style="margin-top:0;">
                <div class="stat-box" style="padding:0.75rem 0.5rem;">
                    <div class="stat-value" style="font-size:1.25rem;">${total}</div>
                    <div class="stat-label">전체 (Days)</div>
                </div>
                <div class="stat-box" style="padding:0.75rem 0.5rem;">
                    <div class="stat-value" style="font-size:1.25rem; color:var(--success-color);">${stat.completed_days}</div>
                    <div class="stat-label">실행 (Done)</div>
                </div>
                <div class="stat-box" style="padding:0.75rem 0.5rem;">
                    <div class="stat-value" style="font-size:1.25rem; color:var(--danger-color);">${stat.missed_days}</div>
                    <div class="stat-label">미실행 (Missed)</div>
                </div>
            </div>
        `;
        list.appendChild(div);
    });
}

// --- History Page ---
let globalHistoryData = [];

async function initHistory() {
    const list = document.getElementById('historyList');
    if (!list) return;

    try {
        const res = await fetch('/api/history');
        globalHistoryData = await res.json();
        
        const yearList = document.getElementById('yearList');
        for (let y = 2050; y >= 2020; y--) {
            const opt = document.createElement('option');
            opt.value = y;
            yearList.appendChild(opt);
        }

        const filterYear = document.getElementById('filterYear');
        if (!filterYear.value) {
            filterYear.value = "2026";
        }

        const searchBtn = document.getElementById('searchHistoryBtn');
        if (searchBtn) {
            searchBtn.addEventListener('click', renderHistory);
        }
        
        const yearlyBtn = document.getElementById('yearlyReportBtn');
        if (yearlyBtn) {
            yearlyBtn.addEventListener('click', renderYearlyHistory);
        }

        renderHistory();
    } catch (err) {
        list.innerHTML = '<p style="color: var(--danger-color); text-align: center;">히스토리를 불러오는 중 오류가 발생했습니다.</p>';
        console.error(err);
    }
}

function renderHistory() {
    const list = document.getElementById('historyList');
    let selectedYear = document.getElementById('filterYear').value.trim();
    const selectedMonth = document.getElementById('filterMonth').value;
    
    // 연도 파싱 (예: "2026", "2026년" 등에서 앞 4자리 추출)
    const yearMatch = selectedYear.match(/\d{4}/);
    if (yearMatch) {
        selectedYear = yearMatch[0];
    } else if (selectedYear === '' || selectedYear.includes('전체') || selectedYear.toLowerCase() === 'all') {
        selectedYear = 'all';
    } else {
        // 4자리 숫자가 없고 '전체'도 아니면 유효하지 않은 연도
        selectedYear = 'invalid';
    }
    
    let filteredData = globalHistoryData;
    
    if (selectedYear === 'invalid') {
        filteredData = []; // 강제로 빈 배열로 처리
    } else if (selectedYear !== 'all') {
        filteredData = filteredData.filter(d => d.month.startsWith(selectedYear));
    }
    
    if (selectedMonth !== 'all') {
        filteredData = filteredData.filter(d => d.month.endsWith(`-${selectedMonth}`));
    }
    
    list.innerHTML = '';
    
    if (filteredData.length === 0) {
        list.innerHTML = '<p style="color: var(--text-secondary); text-align: center;">조건에 맞는 히스토리 데이터가 없습니다.</p>';
        return;
    }

    filteredData.forEach(monthData => {
        const monthDiv = document.createElement('div');
        monthDiv.className = 'card';
        monthDiv.style.marginBottom = '2rem';
        
        let tasksHtml = monthData.tasks.map(t => `
            <div style="display:flex; justify-content:space-between; padding: 0.75rem 0; border-bottom: 1px solid var(--border-color);">
                <span style="font-weight: 500;">${t.name}</span>
                <span>
                    <span style="color: var(--success-color); font-weight:600;">${t.completed}</span> / ${t.total} 
                    <span class="badge ${t.rate >= 80 ? 'badge-success' : 'badge-neutral'}" style="margin-left: 0.5rem;">${t.rate}%</span>
                </span>
            </div>
        `).join('');

        monthDiv.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:center; border-bottom: 2px solid var(--border-color); padding-bottom: 1rem; margin-bottom: 1rem;">
                <h2 style="font-size: 1.25rem; color: var(--primary-color); margin:0;">${monthData.month} 리포트</h2>
                <span class="badge ${monthData.rate >= 80 ? 'badge-success' : 'badge-neutral'}" style="font-size: 1rem; padding: 0.5rem 1rem;">
                    종합 달성률: ${monthData.rate}%
                </span>
            </div>
            <div style="display:flex; justify-content:space-around; margin-bottom: 1.5rem; background: var(--bg-color); padding: 1rem; border-radius: 8px;">
                <div style="text-align:center;">
                    <div style="font-size: 0.875rem; color: var(--text-secondary);">총 목표일</div>
                    <div style="font-size: 1.5rem; font-weight: bold;">${monthData.total}</div>
                </div>
                <div style="text-align:center;">
                    <div style="font-size: 0.875rem; color: var(--text-secondary);">총 실행일</div>
                    <div style="font-size: 1.5rem; font-weight: bold; color: var(--success-color);">${monthData.completed}</div>
                </div>
            </div>
            <div>
                <h3 style="font-size: 1rem; color: var(--text-secondary); margin-bottom: 0.5rem;">태스크별 상세 기록</h3>
                ${tasksHtml}
            </div>
        `;
        list.appendChild(monthDiv);
    });
}

function renderYearlyHistory() {
    const list = document.getElementById('historyList');
    let selectedYear = document.getElementById('filterYear').value.trim();
    
    // 연도 파싱
    const yearMatch = selectedYear.match(/\d{4}/);
    if (yearMatch) {
        selectedYear = yearMatch[0];
    } else {
        list.innerHTML = '<p style="color: var(--danger-color); text-align: center;">연도별 통합 보고서를 보려면 특정 연도(예: 2026)를 입력해야 합니다.</p>';
        return;
    }
    
    // Filter data for the specific year
    const yearData = globalHistoryData.filter(d => d.month.startsWith(selectedYear));
    
    list.innerHTML = '';
    
    if (yearData.length === 0) {
        list.innerHTML = '<p style="color: var(--text-secondary); text-align: center;">조건에 맞는 히스토리 데이터가 없습니다.</p>';
        return;
    }
    
    // Aggregate data
    let totalDays = 0;
    let totalCompleted = 0;
    let tasksMap = {};
    
    yearData.forEach(monthData => {
        totalDays += monthData.total;
        totalCompleted += monthData.completed;
        
        monthData.tasks.forEach(t => {
            if (!tasksMap[t.name]) {
                tasksMap[t.name] = { name: t.name, total: 0, completed: 0, order_index: t.order_index };
            }
            tasksMap[t.name].total += t.total;
            tasksMap[t.name].completed += t.completed;
        });
    });
    
    const overallRate = totalDays > 0 ? Math.round((totalCompleted / totalDays) * 100) : 0;
    
    const yearDiv = document.createElement('div');
    yearDiv.className = 'card';
    yearDiv.style.marginBottom = '2rem';
    yearDiv.style.border = '2px solid var(--primary-color)';
    
    const sortedTasks = Object.values(tasksMap).sort((a, b) => {
        const orderA = a.order_index !== null ? a.order_index : 999;
        const orderB = b.order_index !== null ? b.order_index : 999;
        return orderA - orderB;
    });

    let tasksHtml = sortedTasks.map(t => {
        const tRate = t.total > 0 ? Math.round((t.completed / t.total) * 100) : 0;
        return `
            <div style="display:flex; justify-content:space-between; padding: 0.75rem 0; border-bottom: 1px solid var(--border-color);">
                <span style="font-weight: 500;">${t.name}</span>
                <span>
                    <span style="color: var(--success-color); font-weight:600;">${t.completed}</span> / ${t.total} 
                    <span class="badge ${tRate >= 80 ? 'badge-success' : 'badge-neutral'}" style="margin-left: 0.5rem;">${tRate}%</span>
                </span>
            </div>
        `;
    }).join('');

    yearDiv.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; border-bottom: 2px solid var(--border-color); padding-bottom: 1rem; margin-bottom: 1rem;">
            <h2 style="font-size: 1.25rem; color: var(--primary-color); margin:0;">🏆 ${selectedYear}년 통합 보고서</h2>
            <span class="badge ${overallRate >= 80 ? 'badge-success' : 'badge-neutral'}" style="font-size: 1rem; padding: 0.5rem 1rem;">
                연간 종합 달성률: ${overallRate}%
            </span>
        </div>
        <div style="display:flex; justify-content:space-around; margin-bottom: 1.5rem; background: var(--bg-color); padding: 1rem; border-radius: 8px;">
            <div style="text-align:center;">
                <div style="font-size: 0.875rem; color: var(--text-secondary);">연간 총 목표일</div>
                <div style="font-size: 1.5rem; font-weight: bold;">${totalDays}</div>
            </div>
            <div style="text-align:center;">
                <div style="font-size: 0.875rem; color: var(--text-secondary);">연간 총 실행일</div>
                <div style="font-size: 1.5rem; font-weight: bold; color: var(--success-color);">${totalCompleted}</div>
            </div>
        </div>
        <div>
            <h3 style="font-size: 1rem; color: var(--text-secondary); margin-bottom: 0.5rem;">태스크별 연간 상세 기록</h3>
            ${tasksHtml}
        </div>
    `;
    list.appendChild(yearDiv);
}
