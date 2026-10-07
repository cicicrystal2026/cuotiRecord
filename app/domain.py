from datetime import datetime, timedelta, timezone

from . import storage as db
from .knowledge import BY_ID, NODES, KNOWLEDGE_VERSION


def latest_analysis(question_id):
    value = db.one('SELECT * FROM analyses WHERE question_id=? ORDER BY created_at DESC,id DESC LIMIT 1', (question_id,))
    if value:
        for key in ('causes', 'knowledge_ids', 'proposal'):
            value[key] = db.decode(value[key], [] if key != 'proposal' else {})
    return value


def eligible(q, analysis):
    return bool((q.get('subject') or db.one('SELECT subject FROM sources WHERE id=?',(q['source_id'],))['subject'])=='english' and q['saved'] and q['result'] == 'wrong' and analysis and analysis['status'] == 'confirmed' and analysis['knowledge_version']==KNOWLEDGE_VERSION and analysis['question_version'] == q['version'] and analysis['answer'].strip() and not analysis['uncertainty'].strip() and not q['missing'] and q['work'].strip())


def attempts_for(question):
    return db.rows('SELECT * FROM attempts WHERE question_id=? AND question_version=? ORDER BY completed_at,id', (question['id'], question['version']))


def question_state(q, analysis, attempts=None):
    subject=q.get('subject') or db.one('SELECT subject FROM sources WHERE id=?',(q['source_id'],))['subject']
    if subject!='english':
        return {'wrong':'记录为错题','correct':'记录为做对','unanswered':'记录为未作答','unknown':'待核对'}.get(q['result'],'待核对')
    if not analysis or analysis['status'] != 'confirmed' or analysis['knowledge_version']!=KNOWLEDGE_VERSION or analysis['question_version'] != q['version'] or analysis['uncertainty'] or q['missing']:
        return '待确认'
    if q['result'] == 'correct':
        return '已接触'
    if q['result'] != 'wrong':
        return '待确认'
    attempts = attempts if attempts is not None else attempts_for(q)
    if not attempts or attempts[-1]['result'] != 'right':
        return '需要巩固'
    tail = []
    for value in reversed(attempts):
        if value['result'] != 'right' or value['hint_used']:
            break
        tail.append(value)
    if len(tail) >= 2:
        latest = datetime.fromisoformat(tail[0]['completed_at'])
        tz = timezone(timedelta(hours=8))
        if any(latest - datetime.fromisoformat(v['completed_at']) >= timedelta(hours=24) and latest.astimezone(tz).date() != datetime.fromisoformat(v['completed_at']).astimezone(tz).date() for v in tail[1:]):
            return '已验证'
    return '本次独立做对'


def question_view(question, include_attempts=True):
    value = dict(question)
    analysis = latest_analysis(value['id'])
    attempts = attempts_for(value)
    value['analysis'] = analysis
    value['state'] = question_state(value, analysis, attempts)
    value['eligible'] = eligible(value, analysis)
    if include_attempts:
        value['attempts'] = db.rows('SELECT * FROM attempts WHERE question_id=? ORDER BY completed_at DESC', (value['id'],))
    value['knowledge'] = [BY_ID[i] for i in analysis['knowledge_ids'] if i in BY_ID] if analysis else []
    return value


def source_view(source):
    value = dict(source)
    value['pages'] = db.rows('SELECT id,source_id,number,text,status,error,subject,content_kind,recognition_version FROM pages WHERE source_id=? ORDER BY number', (value['id'],))
    value['files'] = db.rows('SELECT id,name,kind FROM files WHERE source_id=? ORDER BY rowid', (value['id'],))
    value['questions'] = [question_view(q) for q in db.rows('SELECT * FROM questions WHERE source_id=? ORDER BY created_at,id', (value['id'],))]
    value['tasks'] = db.rows('SELECT * FROM tasks WHERE source_id=? ORDER BY created_at DESC', (value['id'],))
    return value


def list_questions(subject="english"):
    return [question_view(q) for q in db.rows('SELECT q.*,s.name source_name,s.study_date,s.sample,s.subject FROM questions q JOIN sources s ON q.source_id=s.id WHERE q.saved=1 AND s.subject=? ORDER BY s.study_date DESC,q.created_at DESC',(subject,))]


def knowledge_stats(subject="english"):
    if subject!="english": return []
    questions = list_questions(subject)
    output = []
    for node in NODES:
        related = [q for q in questions if q['analysis'] and node['id'] in q['analysis']['knowledge_ids']]
        confirmed = [q for q in related if q['analysis']['status'] == 'confirmed' and q['analysis']['question_version'] == q['version']]
        states = [q['state'] for q in confirmed]
        if '需要巩固' in states:
            state = '需要巩固'
        elif '本次独立做对' in states:
            state = '本次独立做对'
        elif any(s == '待确认' for s in states):
            state = '待确认'
        elif states and all(s in ('已验证', '已接触') for s in states) and '已验证' in states:
            state = '已验证'
        elif states:
            state = '已接触'
        elif related:
            state = '待确认'
        else:
            state = '未记录'
        output.append({**node, 'state': state, 'count': len(confirmed), 'wrong_count': sum(q['result'] == 'wrong' for q in confirmed), 'pending_count': len(related)-len(confirmed), 'questions': related})
    return output


def session_view(session):
    value = dict(session)
    items = db.rows('SELECT * FROM items WHERE session_id=? ORDER BY position', (value['id'],))
    for item in items:
        snap = db.decode(item['snapshot'], {})
        attempt = db.one('SELECT * FROM attempts WHERE item_id=?', (item['id'],))
        # Do not send hidden answers to the browser before reveal.
        if not item['revealed'] and not attempt:
            snap.pop('answer', None)
        if not item['hint_used'] and not item['revealed'] and not attempt:
            snap.pop('check_action', None)
        item['snapshot'] = snap
        item['attempt'] = attempt
    value['items'] = items
    value['finished'] = sum(i['attempt'] is not None for i in items)
    value['right'] = sum(i['attempt'] is not None and i['attempt']['result'] == 'right' for i in items)
    return value


def delete_question(db_conn, question_id):
    # Scrub copies of deleted content in active/completed session snapshots.
    for item in db_conn.execute('SELECT id FROM items WHERE question_id=?', (question_id,)).fetchall():
        db_conn.execute('UPDATE items SET snapshot=?,question_id=NULL WHERE id=?', (db.encode({'stem': '题目已删除', 'label': '已删除记录', 'answer': '', 'deleted': True}), item['id']))
    db_conn.execute('DELETE FROM attempts WHERE question_id=?', (question_id,))
    db_conn.execute('DELETE FROM questions WHERE id=?', (question_id,))


def advance_session(conn, session_id):
    pending = conn.execute('SELECT i.position FROM items i LEFT JOIN attempts a ON a.item_id=i.id WHERE i.session_id=? AND i.question_id IS NOT NULL AND a.id IS NULL ORDER BY i.position LIMIT 1', (session_id,)).fetchone()
    if pending:
        conn.execute('UPDATE sessions SET current_index=? WHERE id=?', (pending['position'], session_id))
    else:
        conn.execute("UPDATE sessions SET status='completed',completed_at=? WHERE id=?", (db.now(), session_id))
