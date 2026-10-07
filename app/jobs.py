import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import ai, storage as db
from .documents import convert_file

POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix='cuoti-job')
_GUARD = threading.Lock()


def alive(task_id):
    return bool(db.one("SELECT id FROM tasks WHERE id=? AND status IN ('queued','running')", (task_id,)))


def create_task(source_id, kind):
    with _GUARD:
        old = db.one("SELECT * FROM tasks WHERE source_id=? AND kind=? AND status IN ('queued','running')", (source_id, kind))
        if old:
            return old['id'], False
        task_id = db.uid()
        stamp = db.now()
        db.execute('INSERT INTO tasks(id,source_id,kind,status,created_at,updated_at) VALUES(?,?,?,?,?,?)', (task_id, source_id, kind, 'queued', stamp, stamp))
        return task_id, True


def convert_job(task_id, source_id):
    db.task_update(task_id, 'running', '正在读取与生成资料预览')
    source = db.one('SELECT * FROM sources WHERE id=?', (source_id,))
    if not source:
        return
    try:
        files = db.rows('SELECT * FROM files WHERE source_id=? ORDER BY rowid', (source_id,))
        results = []
        warnings = []
        for file in files:
            folder = db.DATA_DIR / 'sources' / source_id / 'previews' / file['id']
            pages, warning = convert_file(Path(file['path']), file['kind'], folder)
            if warning:
                warnings.append(warning)
            results.extend(pages)
        if len(results) > 20:
            raise ValueError('资料总页数超过20页，请拆分后上传')
        if not alive(task_id):
            return
        with db.connect() as conn:
            if not conn.execute('SELECT id FROM sources WHERE id=?', (source_id,)).fetchone():
                return
            # Retry conversion only when no pages were saved.
            if not conn.execute('SELECT id FROM pages WHERE source_id=?', (source_id,)).fetchone():
                for n, page in enumerate(results, 1):
                    conn.execute('INSERT INTO pages(id,source_id,number,path,text) VALUES(?,?,?,?,?)', (db.uid(), source_id, n, page['path'], page['text']))
            conn.execute('UPDATE sources SET warning=? WHERE id=?', ('\n'.join(dict.fromkeys(warnings)), source_id))
        db.task_update(task_id, 'success', f'资料预览已完成，共{len(results)}页。可开始识别或手动录入。')
    except Exception as exc:
        message = str(exc) if isinstance(exc, ValueError) else '资料无法转换，请检查文件完整性或改用PDF'
        db.task_update(task_id, 'failed', '资料预览失败', message[:1500])


def recognize_job(task_id, source_id):
    db.task_update(task_id, 'running', '正在识别题目与作答')
    pages = db.rows("SELECT * FROM pages WHERE source_id=? AND (status!='success' OR recognition_version='') ORDER BY number", (source_id,))
    for page in pages:
        if not alive(task_id):
            return
        db.task_update(task_id, 'running', f"正在识别第{page['number']}页；已保存的题目不会覆盖")
        try:
            result = ai.recognize(page)
            if isinstance(result, tuple):
                questions,warning=result
                result={'questions':questions,'warning':warning,'text':page['text'],'subject':'英语','content_kind':'questions' if questions else 'notes','recognition_version':'legacy'}
            questions,warning=result['questions'],result['warning']
            if not alive(task_id):
                return
            if result['content_kind']=='unreadable':
                raise ai.AIError(warning or '页面文字无法读取，请检查反光、裁边和文字大小')
            with db.connect() as conn:
                if not conn.execute('SELECT id FROM pages WHERE id=?', (page['id'],)).fetchone():
                    return
                for q in (questions if page['status']!='success' else []):
                    qid = db.uid()
                    conn.execute('INSERT INTO questions(id,source_id,page_id,label,stem,work,missing,created_at) VALUES(?,?,?,?,?,?,?,?)', (qid, source_id, page['id'], q['label'], q['stem'], q['work'], int(q['missing']), db.now()))
                    conn.execute('INSERT INTO question_versions VALUES(?,?,?,?,?,?,?)', (db.uid(), qid, 1, q['stem'], q['work'], int(q['missing']), db.now()))
                conn.execute("UPDATE pages SET status='success',error=?,text=?,subject=?,content_kind=?,recognition_version=? WHERE id=?", (warning,result['text'] or page['text'],result['subject'],result['content_kind'],result['recognition_version'],page['id']))
        except Exception as exc:
            message = str(exc) if isinstance(exc, ValueError) else '本页识别失败，请稍后重试'
            db.execute("UPDATE pages SET status='failed',error=? WHERE id=?", (message[:1500], page['id']))
    statuses = db.rows('SELECT status FROM pages WHERE source_id=?', (source_id,))
    success = sum(p['status'] == 'success' for p in statuses)
    final = 'success' if success == len(statuses) else ('partial' if success else 'failed')
    db.task_update(task_id, final, f'{success}/{len(statuses)}页识别成功', '' if final == 'success' else '未成功的页面可重试，已成功的页面与题目保留。')


def insert_analysis(conn, q, result):
    aid = db.uid()
    conn.execute('''INSERT INTO analyses(id,question_id,question_version,status,answer,correct_parts,issues,evidence,check_action,causes,knowledge_ids,uncertainty,model,prompt_version,knowledge_version,proposal,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (aid, q['id'], q['version'], 'pending', result.get('answer',''), result.get('correct_parts',''), result.get('issues',''), result.get('evidence',''), result.get('check_action',''), db.encode(result.get('causes',[])), db.encode(result.get('knowledge_ids',[])), result.get('uncertainty',''), result['model'], result['prompt_version'], result['knowledge_version'], db.encode(result.get('proposal',{})), db.now()))
    return aid


def analyze_job(task_id, source_id, question_ids):
    db.task_update(task_id, 'running', '正在分析已核对题目')
    succeeded = 0
    failures = []
    for n, question_id in enumerate(question_ids, 1):
        if not alive(task_id):
            return
        q = db.one('SELECT * FROM questions WHERE id=? AND source_id=?', (question_id, source_id))
        if not q:
            continue
        db.task_update(task_id, 'running', f'正在分析第{n}/{len(question_ids)}题')
        try:
            page = db.one('SELECT * FROM pages WHERE id=?', (q['page_id'],)) if q['page_id'] else None
            result = ai.analyze(q, page)
            with db.connect() as conn:
                current = conn.execute('SELECT * FROM questions WHERE id=?', (question_id,)).fetchone()
                if not current or current['version'] != q['version'] or not alive(task_id):
                    failures.append(q['label'] + '已修改，请重新分析')
                    continue
                insert_analysis(conn, q, result)
            succeeded += 1
        except Exception as exc:
            failures.append(q['label'] + '：' + (str(exc) if isinstance(exc, ValueError) else '分析失败，请重试'))
    status = 'success' if succeeded == len(question_ids) else ('partial' if succeeded else 'failed')
    db.task_update(task_id, status, f'{succeeded}/{len(question_ids)}题分析成功', '\n'.join(failures)[:5000])
