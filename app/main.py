import asyncio
import io
import os
import shutil
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw, ImageFont

from . import VERSION, ai, domain, jobs, storage as db
from .config import save_settings, settings
from .subjects import SUBJECTS, validate as validate_subject
from .knowledge import CAUSES, IDS, KNOWLEDGE_VERSION, NODES

ROOT = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    yield


app = FastAPI(title='知错 本地学习档案', version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware('http')
async def local_only(request: Request, call_next):
    host = request.url.hostname
    if host not in ('127.0.0.1', 'localhost', 'testserver'):
        return JSONResponse({'detail': '仅允许本机访问'}, status_code=403)
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail': '请求来源不允许'}, status_code=403)
        if request.headers.get('x-cuoti-client') != 'local-v1':
            return JSONResponse({'detail': '请从本地应用操作'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.url.path.startswith('/api'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.exception_handler(ValueError)
async def value_error(request, exc):
    return JSONResponse({'detail': str(exc)}, status_code=400)


def require(table, identifier):
    # table is always a hardcoded internal name, never user-supplied.
    value = db.one(f'SELECT * FROM {table} WHERE id=?', (identifier,))
    if not value:
        raise HTTPException(404, '记录不存在或已删除')
    return value


def text(value, name, max_length=20000, required=False):
    if not isinstance(value, str) or len(value) > max_length:
        raise ValueError(name + '格式或长度不正确')
    value = value.strip()
    if required and not value:
        raise ValueError('请填写' + name)
    return value


def study_date(value):
    try:
        parsed = date.fromisoformat(value)
    except (ValueError, TypeError):
        raise ValueError('学习日期格式不正确') from None
    if parsed > date.today():
        raise ValueError('学习日期不能晚于今天')
    return parsed.isoformat()


@app.get('/api/health')
def health():
    return {'ok': True, 'version': VERSION, 'data_dir': str(db.DATA_DIR), 'knowledge_version': KNOWLEDGE_VERSION}


@app.get('/api/bootstrap')
def bootstrap():
    return {'subjects': SUBJECTS, 'version': VERSION, 'profile': db.one('SELECT * FROM profile WHERE id=1'), 'config': settings(), 'knowledge': NODES, 'causes': CAUSES, 'data_dir': str(db.DATA_DIR)}


@app.put('/api/profile')
def update_profile(body: dict):
    nickname = text(body.get('nickname', ''), '昵称', 60, True)
    grade = body.get('grade', '高一')
    if grade not in ('高一', '高二', '高三'):
        raise ValueError('年级不正确')
    curriculum = text(body.get('curriculum','暂不确定'), '教材', 60, True)
    semester = text(body.get('semester',''), '学期名称', 100, True)
    try:
        start = date.fromisoformat(body.get('start_date',''))
        end = date.fromisoformat(body.get('end_date',''))
    except ValueError:
        raise ValueError('请输入有效的学期日期') from None
    if start > end:
        raise ValueError('学期开始日期不能晚于结束日期')
    old = db.one('SELECT * FROM profile WHERE id=1')
    with db.connect() as conn:
        conn.execute('INSERT OR REPLACE INTO profile VALUES(1,?,?,?,?,?,?)', (nickname, grade, curriculum, semester, start.isoformat(), end.isoformat()))
    return {'profile': db.one('SELECT * FROM profile WHERE id=1'), 'notice': '教材设置更新；已保存的考点与分析版本保留。' if old and old['curriculum'] != curriculum else '档案已保存'}


@app.get('/api/config')
def config():
    return settings()


@app.put('/api/config')
def update_config(body: dict):
    return save_settings(body)


@app.post('/api/config/test')
def test_config(body: dict):
    model = body.get('model', settings()['analysis_model'])
    if model not in (settings()['vision_model'], settings()['analysis_model']):
        raise ValueError('请选择已配置的模型')
    result, usage = ai.chat([{'role': 'user', 'content': '请只回复：连接成功'}], model, thinking=False, json_output=False)
    return {'ok': True, 'model': model, 'message': result[:300], 'usage': usage}


@app.get('/api/sources')
def sources(subject: str = Header('english',alias='X-Cuoti-Subject')):
    validate_subject(subject)
    result = db.rows('SELECT * FROM sources WHERE subject=? ORDER BY study_date DESC,created_at DESC',(subject,))
    for source in result:
        source['question_count'] = db.one('SELECT count(*) n FROM questions WHERE source_id=? AND saved=1', (source['id'],))['n']
        source['page_count'] = db.one('SELECT count(*) n FROM pages WHERE source_id=?', (source['id'],))['n']
        source['task'] = db.one('SELECT * FROM tasks WHERE source_id=? ORDER BY created_at DESC LIMIT 1', (source['id'],))
    return result


@app.get('/api/sources/{source_id}')
def source_detail(source_id: str):
    return domain.source_view(require('sources', source_id))


@app.post('/api/sources')
async def upload_source(files: list[UploadFile] = File(...), name: str = Form(...), learning_date: str = Form(...), subject: str = Form("english")):
    validate_subject(subject)
    if not db.one('SELECT id FROM profile WHERE id=1'):
        raise ValueError('请先建立学期档案')
    name = text(name, '资料名称', 150, True)
    learning_date = study_date(learning_date)
    if not files or len(files) > 20:
        raise ValueError('每次最多20张图片或一个PDF / DOCX文档')
    kinds = []
    for file in files:
        ext = Path(file.filename or '').suffix.lower()
        kind = 'image' if ext in ('.jpg','.jpeg','.png') else ('pdf' if ext == '.pdf' else ('docx' if ext == '.docx' else None))
        if not kind:
            raise ValueError('支持JPG、PNG、PDF与DOCX；.doc请另存为DOCX或PDF')
        kinds.append(kind)
    if len(files) > 1 and any(k != 'image' for k in kinds):
        raise ValueError('一次请选择一组图片或一个文档，不能混合上传')
    source_id = db.uid()
    folder = db.DATA_DIR / 'sources' / source_id
    folder.mkdir(parents=True, exist_ok=True)
    records = []
    try:
        for file, kind in zip(files, kinds):
            limit = 10*1024*1024 if kind == 'image' else 30*1024*1024
            fid = db.uid()
            original_name = Path((file.filename or '资料').replace('\\','/')).name[:180]
            target = folder / (fid + Path(original_name).suffix.lower())
            size = 0
            with target.open('wb') as stream:
                while chunk := await file.read(1024*1024):
                    size += len(chunk)
                    if size > limit:
                        raise ValueError('图片最多10MB，PDF与DOCX最多30MB')
                    stream.write(chunk)
            if not size:
                raise ValueError('文件为空，请重新选择')
            if kind == 'pdf' and not target.read_bytes()[:1024].lstrip().startswith(b'%PDF'):
                raise ValueError('文件内容不是有效PDF')
            records.append((fid, source_id, original_name, str(target), kind))
        with db.connect() as conn:
            conn.execute('INSERT INTO sources(id,name,study_date,created_at,kind,subject) VALUES(?,?,?,?,?,?)', (source_id, name, learning_date, db.now(), kinds[0],subject))
            conn.executemany('INSERT INTO files VALUES(?,?,?,?,?)', records)
        task_id, _ = jobs.create_task(source_id, 'convert')
        jobs.POOL.submit(jobs.convert_job, task_id, source_id)
        return {'id': source_id, 'task_id': task_id}
    except Exception:
        safe_remove(folder)
        raise


@app.post('/api/sources/{source_id}/convert')
def retry_convert(source_id: str):
    require('sources', source_id)
    if db.one('SELECT id FROM pages WHERE source_id=?', (source_id,)):
        raise ValueError('预览已生成，请进入核对页面')
    task_id, fresh = jobs.create_task(source_id, 'convert')
    if fresh:
        jobs.POOL.submit(jobs.convert_job, task_id, source_id)
    return {'task_id': task_id}


@app.post('/api/sources/{source_id}/recognize')
def start_recognize(source_id: str):
    require('sources', source_id)
    if not settings()['configured']:
        raise ValueError('请先在设置中配置阿里云API Key，也可以直接手动录入题目')
    if not db.one('SELECT id FROM pages WHERE source_id=?', (source_id,)):
        raise ValueError('请等待预览完成')
    task_id, fresh = jobs.create_task(source_id, 'recognize')
    if fresh:
        jobs.POOL.submit(jobs.recognize_job, task_id, source_id)
    return {'task_id': task_id}


@app.get('/api/tasks/{task_id}')
def task_status(task_id: str):
    return require('tasks', task_id)


@app.post('/api/sources/{source_id}/analyze')
def start_analyze(source_id: str, body: dict):
    source=require('sources', source_id)
    if source['subject']!='english':
        raise ValueError('当前'+source['subject']+'资料支持记录与核对；AI考点分析暂仅支持英语。')
    if not settings()['configured']:
        raise ValueError('请先在设置中配置阿里云API Key，真实AI分析不会使用演示结果替代')
    ids = body.get('question_ids') or [q['id'] for q in db.rows('SELECT id FROM questions WHERE source_id=? AND selected=1', (source_id,))]
    if not isinstance(ids, list) or not ids or len(ids) > 20 or len(set(ids)) != len(ids):
        raise ValueError('请选择1至20道不同题目')
    for qid in ids:
        q = require('questions', qid)
        page=db.one('SELECT subject,status,recognition_version FROM pages WHERE id=?',(q['page_id'],)) if q['page_id'] else None
        if page and page['status']=='success' and not page['recognition_version']:
            raise ValueError('这是旧识别结果，请先读取页面以核对学科，再进行英语考点分析。原题不会重复生成。')
        if page and page['subject'] not in ('','英语','不确定'):
            raise ValueError('该页识别为'+page['subject']+'。当前只支持英语考点分析；已读取文字和题目保留，可核对和保存，暂不生成该学科分析。')
        if q['source_id'] != source_id or not q['stem'].strip():
            raise ValueError('题目归属或题干不正确')
    task_id, fresh = jobs.create_task(source_id, 'analyze')
    if fresh:
        jobs.POOL.submit(jobs.analyze_job, task_id, source_id, ids)
    return {'task_id': task_id}


@app.post('/api/sources/{source_id}/questions')
def add_question(source_id: str, body: dict):
    require('sources', source_id)
    page_id = body.get('page_id') or None
    if page_id and require('pages', page_id)['source_id'] != source_id:
        raise ValueError('页面不属于这份资料')
    stem = text(body.get('stem',''), '题干', required=True)
    work = text(body.get('work',''), '作答')
    missing = bool(body.get('missing', not work))
    label = text(body.get('label','手动题目'), '题号', 100, True)
    qid = db.uid()
    with db.connect() as conn:
        conn.execute('INSERT INTO questions(id,source_id,page_id,label,stem,work,missing,created_at) VALUES(?,?,?,?,?,?,?,?)', (qid, source_id, page_id, label, stem, work, int(missing), db.now()))
        conn.execute('INSERT INTO question_versions VALUES(?,?,?,?,?,?,?)', (db.uid(), qid, 1, stem, work, int(missing), db.now()))
    return domain.question_view(require('questions', qid))


@app.put('/api/questions/{question_id}')
def update_question(question_id: str, body: dict):
    q = require('questions', question_id)
    expected = body.get('version', q['version'])
    if expected != q['version']:
        raise HTTPException(409, '题目已更新，请重新加载后对比修改')
    stem = text(body.get('stem',q['stem']), '题干', required=True)
    work = text(body.get('work',q['work']), '作答')
    missing = bool(body.get('missing', q['missing'])) or not work
    label = text(body.get('label',q['label']), '题号', 100, True)
    result = body.get('result', q['result'])
    if result not in ('wrong','correct','unanswered','unknown'):
        raise ValueError('作答状态不正确')
    changed = (stem, work, int(missing), result) != (q['stem'],q['work'],q['missing'],q['result'])
    version = q['version'] + int(changed)
    reflection = text(body.get('reflection',q['reflection']), '反思', 5000)
    with db.connect() as conn:
        updated = conn.execute('UPDATE questions SET stem=?,work=?,missing=?,label=?,result=?,selected=?,version=?,reflection=? WHERE id=? AND version=?', (stem, work, int(missing), label, result, int(bool(body.get('selected',q['selected']))), version, reflection, question_id, expected)).rowcount
        if not updated:
            raise HTTPException(409, '题目已更新，请重新加载')
        if changed:
            conn.execute('INSERT INTO question_versions VALUES(?,?,?,?,?,?,?)', (db.uid(), question_id, version, stem, work, int(missing), db.now()))
            conn.execute("UPDATE analyses SET status='stale' WHERE question_id=?", (question_id,))
    return domain.question_view(require('questions',question_id))


@app.get('/api/questions/{question_id}')
def get_question(question_id: str):
    q = domain.question_view(require('questions', question_id))
    q['source'] = require('sources', q['source_id'])
    q['page'] = db.one('SELECT id,number,status,error FROM pages WHERE id=?', (q['page_id'],)) if q['page_id'] else None
    q['versions'] = db.rows('SELECT * FROM question_versions WHERE question_id=? ORDER BY version DESC', (question_id,))
    q['analysis_history'] = db.rows('SELECT id,status,question_version,model,prompt_version,created_at,confirmed_at FROM analyses WHERE question_id=? ORDER BY created_at DESC', (question_id,))
    return q


@app.post('/api/questions/{question_id}/manual-analysis')
def create_manual_analysis(question_id: str):
    q = require('questions',question_id)
    if require('sources',q['source_id'])['subject']!='english':
        raise ValueError('其他学科可保存题目记录，英语考点分析暂不适用。')
    # Explicit human entry, never masquerading as a model response.
    result = {'model':'manual', 'prompt_version':'human-1', 'knowledge_version':KNOWLEDGE_VERSION, 'proposal':{}, 'uncertainty':'缺少孩子作答，仅能确认考点。' if q['missing'] else ''}
    with db.connect() as conn:
        jobs.insert_analysis(conn, q, result)
    return domain.question_view(q)


@app.put('/api/questions/{question_id}/analysis')
def update_analysis(question_id: str, body: dict):
    q = require('questions',question_id)
    analysis = domain.latest_analysis(question_id)
    if require('sources',q['source_id'])['subject']!='english':
        raise ValueError('当前学科不适用英语分析，请保存题目记录。')
    if analysis and analysis['knowledge_version']!=KNOWLEDGE_VERSION:
        raise ValueError('旧知识库分析已过期，请重新生成英语分析或新建手动分析。')
    if not analysis or analysis['question_version'] != q['version']:
        raise ValueError('请先生成当前版本分析，或新建手动分析')
    if body.get('analysis_id') != analysis['id'] or body.get('question_version') != q['version']:
        raise HTTPException(409, '分析版本已更新，请重新加载')
    status = body.get('status','pending')
    if status not in ('confirmed','pending'):
        raise ValueError('分析状态不正确')
    ids = body.get('knowledge_ids', analysis['knowledge_ids'])
    causes = body.get('causes',analysis['causes'])
    if not isinstance(ids,list) or len(ids)>3 or len(set(ids))!=len(ids) or any(i not in IDS for i in ids):
        raise ValueError('请选择1至3个库内考点')
    if not isinstance(causes,list) or len(causes)>2 or any(c not in CAUSES for c in causes):
        raise ValueError('错因最多两项，且必须来自选项')
    value = {key:text(body.get(key,analysis[key]), key, 20000) for key in ('answer','correct_parts','issues','evidence','check_action','uncertainty')}
    if q['missing'] or not q['work'].strip():
        if status == 'confirmed':
            raise ValueError('缺少实际作答，只能保存为待确认，不能确认个人错因')
        value.update(issues='',evidence='',correct_parts='',uncertainty='缺少孩子作答，仅提供考点与解法建议。')
        causes=[]
    if status == 'confirmed':
        if not ids or not value['answer']:
            raise ValueError('确认前请填写可靠答案并选择至少一个考点')
        if value['uncertainty']:
            raise ValueError('分析仍有疑问，请先核对并清除疑问说明，再确认')
        if q['result']=='wrong' and (not value['issues'] or not value['evidence'] or value['evidence'] not in q['work']):
            raise ValueError('确认错因需要问题说明，以及实际作答中的连续证据片段')
    stamp = db.now()
    with db.connect() as conn:
        current = conn.execute('SELECT version FROM questions WHERE id=?', (question_id,)).fetchone()
        if not current or current['version'] != q['version']:
            raise HTTPException(409, '题目已修改，请重新分析')
        conn.execute('UPDATE analyses SET status=?,answer=?,correct_parts=?,issues=?,evidence=?,check_action=?,causes=?,knowledge_ids=?,uncertainty=?,confirmed_at=? WHERE id=?', (status,value['answer'],value['correct_parts'],value['issues'],value['evidence'],value['check_action'],db.encode(causes),db.encode(ids),value['uncertainty'],stamp if status=='confirmed' else None,analysis['id']))
        conn.execute('INSERT INTO analysis_changes VALUES(?,?,?,?,?)', (db.uid(),analysis['id'],db.encode(analysis),db.encode({**body,**value}),stamp))
        conn.execute('UPDATE questions SET reflection=? WHERE id=?', (text(body.get('reflection',q['reflection']), '反思', 5000),question_id))
    return domain.question_view(require('questions',question_id))


@app.post('/api/sources/{source_id}/save')
def save_records(source_id: str):
    require('sources',source_id)
    with db.connect() as conn:
        count = conn.execute('SELECT count(*) FROM questions WHERE source_id=? AND selected=1', (source_id,)).fetchone()[0]
        if not count:
            raise ValueError('请选择至少一道题目后再保存')
        conn.execute('UPDATE questions SET saved=1 WHERE source_id=? AND selected=1',(source_id,))
        conn.execute("UPDATE sources SET state='saved' WHERE id=?",(source_id,))
    return {'saved_count':count}


@app.put('/api/sources/{source_id}')
def edit_source(source_id: str, body: dict):
    source = require('sources',source_id)
    db.execute('UPDATE sources SET name=?,study_date=? WHERE id=?', (text(body.get('name',source['name']), '资料名称',150,True),study_date(body.get('study_date',source['study_date'])),source_id))
    return domain.source_view(require('sources',source_id))


@app.get('/api/history')
def history(knowledge: str = '', status: str = '', after: str = '', before: str = '', query: str = '', subject: str = Header('english',alias='X-Cuoti-Subject')):
    validate_subject(subject)
    result = domain.list_questions(subject)
    if knowledge:
        result=[q for q in result if q['analysis'] and knowledge in q['analysis']['knowledge_ids']]
    if status:
        result=[q for q in result if q['state']==status]
    if after:
        result=[q for q in result if q['study_date']>=after]
    if before:
        result=[q for q in result if q['study_date']<=before]
    if query:
        result=[q for q in result if query in q['stem'] or query in q['source_name']]
    return result


@app.get('/api/knowledge')
def knowledge_list(subject: str = Header('english',alias='X-Cuoti-Subject')):
    return domain.knowledge_stats(validate_subject(subject))


@app.get('/api/dashboard')
def dashboard(subject: str = Header('english',alias='X-Cuoti-Subject')):
    validate_subject(subject)
    questions = domain.list_questions(subject)
    knowledge = domain.knowledge_stats(subject)
    active = db.one("SELECT * FROM sessions WHERE status IN ('active','paused') ORDER BY created_at DESC LIMIT 1")
    tasks = db.rows("SELECT * FROM tasks WHERE status IN ('queued','running') ORDER BY created_at DESC")
    return {'record_count':len(questions),'wrong_count':sum(q['result']=='wrong' for q in questions), 'point_count':sum(k['count']>0 for k in knowledge), 'pending_count':sum(q['state']=='待确认' for q in questions), 'review_count':sum(q['eligible'] and q['state']!='已验证' for q in questions), 'active_session':domain.session_view(active) if active and subject=='english' else None, 'tasks':tasks, 'recent':questions[:4], 'sample_count':sum(bool(q['sample']) for q in questions)}


@app.get('/api/review/candidates')
def candidates(knowledge: str = '',subject: str = Header('english',alias='X-Cuoti-Subject')):
    validate_subject(subject)
    values = [q for q in domain.list_questions(subject) if q['eligible'] and q['state']!='已验证' and (not knowledge or knowledge in q['analysis']['knowledge_ids'])]
    counts = {}
    for q in values:
        for cause in q['analysis']['causes']:
            counts[cause]=counts.get(cause,0)+1
    for q in values:
        attempts = domain.attempts_for(q)
        if attempts and attempts[-1]['result'] != 'right':
            q['reason']='上次重做仍错或用了提示';q['priority']=0
        elif any(counts[c]>=2 for c in q['analysis']['causes']):
            q['reason']='相同错因类型在多题出现';q['priority']=1
        elif not attempts:
            q['reason']='尚未独立重做';q['priority']=2
        else:
            q['reason']='需要隔天再次验证';q['priority']=3
    return sorted(values,key=lambda q:(q['priority'],-date.fromisoformat(q['study_date']).toordinal()))


@app.post('/api/review/sessions')
def create_session(body: dict):
    request_key=text(body.get('request_key',''), '请求标识',100,True)
    existing=db.one('SELECT * FROM sessions WHERE request_key=?',(request_key,))
    if existing:
        return domain.session_view(existing)
    active=db.one("SELECT * FROM sessions WHERE status IN ('active','paused')")
    if active:
        raise HTTPException(409, f"还有未完成的复习，请先继续或结束（{active['id']}）")
    ids=body.get('question_ids',[])
    if not isinstance(ids,list) or not ids or len(ids)>20 or len(set(ids))!=len(ids):
        raise ValueError('请选择1至20道不同题目')
    selected=[]
    for qid in ids:
        q=domain.question_view(require('questions',qid))
        if not q['eligible']:
            raise ValueError('只能选择已确认、作答完整且有可靠答案的错题')
        selected.append(q)
    sid=db.uid();stamp=db.now()
    with db.connect() as conn:
        # Serialize creation against other simultaneous browser tabs.
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute("SELECT id FROM sessions WHERE status IN ('active','paused')").fetchone():
            raise HTTPException(409,'还有未完成的复习，请先继续或结束')
        conn.execute('INSERT INTO sessions(id,name,status,created_at,request_key) VALUES(?,?,?,?,?)',(sid,text(body.get('name','原题复习'),'复习名称',100,True),'active',stamp,request_key))
        for n,q in enumerate(selected):
            a=q['analysis']
            snapshot={'stem':q['stem'],'label':q['label'],'answer':a['answer'],'check_action':a['check_action'],'knowledge':q['knowledge'],'question_version':q['version'],'analysis_id':a['id'],'sample':bool(db.one('SELECT sample FROM sources WHERE id=?',(q['source_id'],))['sample'])}
            conn.execute('INSERT INTO items(id,session_id,question_id,position,snapshot) VALUES(?,?,?,?,?)',(db.uid(),sid,q['id'],n,db.encode(snapshot)))
    return domain.session_view(require('sessions',sid))


@app.get('/api/review/sessions/{session_id}')
def session_detail(session_id: str):
    return domain.session_view(require('sessions',session_id))


@app.post('/api/review/sessions/{session_id}/state')
def session_state(session_id: str,body:dict):
    session=require('sessions',session_id)
    action=body.get('action')
    if action not in ('pause','resume','finish'):
        raise ValueError('操作不正确')
    if session['status'] in ('completed','ended'):
        return domain.session_view(session)
    status={'pause':'paused','resume':'active','finish':'ended'}[action]
    db.execute('UPDATE sessions SET status=?,completed_at=? WHERE id=?',(status,db.now() if status=='ended' else None,session_id))
    return domain.session_view(require('sessions',session_id))


@app.post('/api/review/items/{item_id}/reveal')
def reveal(item_id: str,body:dict):
    item=require('items',item_id);session=require('sessions',item['session_id'])
    if session['status'] not in ('active','paused') or item['position']!=session['current_index']:
        raise ValueError('请从当前题继续复习')
    if not item['question_id']:
        raise ValueError('此题已删除')
    kind=body.get('kind','answer')
    if kind not in ('hint','answer'):
        raise ValueError('展开类型不正确')
    column='hint_used' if kind=='hint' else 'revealed'
    db.execute(f'UPDATE items SET {column}=1 WHERE id=?',(item_id,))
    return domain.session_view(require('sessions',item['session_id']))


@app.post('/api/review/items/{item_id}/attempt')
def submit_attempt(item_id: str,body:dict):
    item=require('items',item_id)
    old=db.one('SELECT * FROM attempts WHERE item_id=?',(item_id,))
    if old:
        return domain.session_view(require('sessions',item['session_id']))
    session=require('sessions',item['session_id'])
    if session['status']!='active' or item['position']!=session['current_index']:
        raise ValueError('请先继续当前复习计划')
    if not item['question_id']:
        raise ValueError('此题已删除')
    if not item['revealed']:
        raise ValueError('请先完成作答并核对答案')
    result=body.get('result')
    if result not in ('right','hint','wrong'):
        raise ValueError('请选择实际重做结果')
    if item['hint_used'] and result=='right':
        raise ValueError('已经查看提示，不能记为独立做对')
    snap=db.decode(item['snapshot'],{})
    q=require('questions',item['question_id'])
    if q['version']!=snap['question_version']:
        raise ValueError('原题已修改，本次旧版本结果不能用于新题验证，请结束计划后重新开始')
    with db.connect() as conn:
        conn.execute('INSERT OR IGNORE INTO attempts VALUES(?,?,?,?,?,?,?,?)',(db.uid(),item['session_id'],item_id,item['question_id'],snap['question_version'],result,int(bool(item['hint_used']) or result=='hint'),db.now()))
        domain.advance_session(conn,item['session_id'])
    return domain.session_view(require('sessions',item['session_id']))


@app.put('/api/pages/{page_id}/subject')
def confirm_page_subject(page_id: str,body:dict):
    require('pages',page_id)
    if body.get('subject')!='英语':
        raise ValueError('本版只支持明确确认英语学科')
    db.execute("UPDATE pages SET subject='英语',recognition_version='manual-en-1' WHERE id=?",(page_id,))
    return {'confirmed':True,'subject':'英语'}


@app.get('/api/pages/{page_id}/image')
def page_image(page_id: str):
    page=require('pages',page_id)
    path=Path(page['path']).resolve()
    if not path.is_relative_to(db.DATA_DIR) or not path.is_file():
        raise HTTPException(404,'原页预览不存在')
    return FileResponse(path,media_type='image/jpeg')


@app.get('/api/files/{file_id}/download')
def download_file(file_id: str):
    file=require('files',file_id)
    path=Path(file['path']).resolve()
    if not path.is_relative_to(db.DATA_DIR) or not path.is_file():
        raise HTTPException(404,'原文件不存在')
    return FileResponse(path,filename=file['name'],media_type='application/octet-stream')


def safe_remove(folder):
    root=(db.DATA_DIR/'sources').resolve();target=Path(folder).resolve()
    if target==root or not target.is_relative_to(root):
        raise ValueError('清理目录不在资料目录内')
    if target.exists():
        shutil.rmtree(target)


@app.delete('/api/questions/{question_id}')
def remove_question(question_id: str):
    require('questions',question_id)
    with db.connect() as conn:
        sessions=[r['session_id'] for r in conn.execute('SELECT DISTINCT session_id FROM items WHERE question_id=?',(question_id,)).fetchall()]
        domain.delete_question(conn,question_id)
        for sid in sessions:
            status=conn.execute('SELECT status FROM sessions WHERE id=?',(sid,)).fetchone()
            if status and status['status'] in ('active','paused'):
                domain.advance_session(conn,sid)
    return {'deleted':True}


@app.delete('/api/sources/{source_id}')
def remove_source(source_id: str):
    require('sources',source_id)
    folder=db.DATA_DIR/'sources'/source_id
    with db.connect() as conn:
        sessions=set()
        for q in conn.execute('SELECT id FROM questions WHERE source_id=?',(source_id,)).fetchall():
            sessions.update(r['session_id'] for r in conn.execute('SELECT DISTINCT session_id FROM items WHERE question_id=?',(q['id'],)))
            domain.delete_question(conn,q['id'])
        conn.execute('DELETE FROM sources WHERE id=?',(source_id,))
        for sid in sessions:
            status=conn.execute('SELECT status FROM sessions WHERE id=?',(sid,)).fetchone()
            if status and status['status'] in ('active','paused'):
                domain.advance_session(conn,sid)
    safe_remove(folder)
    return {'deleted':True}


@app.post('/api/sample')
def import_sample():
    if not db.one('SELECT id FROM profile WHERE id=1'):
        raise ValueError('请先建立学期档案')
    existing=db.one("SELECT id FROM sources WHERE sample=1 AND name='示例练习 · 英语专题'")
    if existing:
        return {'id':existing['id'],'existing':True}
    sid=db.uid();pid=db.uid();fid=db.uid()
    folder=db.DATA_DIR/'sources'/sid;folder.mkdir(parents=True,exist_ok=True)
    image=Image.new('RGB',(1100,1350),'#ffffff');draw=ImageDraw.Draw(image)
    fontpath='C:/Windows/Fonts/msyh.ttc'
    font=ImageFont.truetype(fontpath,26) if Path(fontpath).exists() else ImageFont.load_default()
    lines=['知错 · 英语示例（非真实AI分析）','1. She enjoys ___ (read) books.','我的作答：read','2. He has lived here ___ 2020.','A. for  B. since','我的作答：A. for']
    for n,line in enumerate(lines):draw.text((45,55+n*72),line,font=font,fill='#263d31')
    path=folder/'sample.jpg';image.save(path,'JPEG',quality=94)
    examples=[{'label': '第1题', 'stem': '填空：She enjoys ___ (read) books.', 'work': 'read', 'answer': 'reading。enjoy后接动名词，句子为She enjoys reading books.', 'correct_parts': '选用了正确词根read。', 'issues': 'enjoy后需用动名词，不能直接用动词原形。', 'evidence': 'read', 'check_action': '检查动词后接to do还是doing。', 'causes': ['语法'], 'knowledge_ids': ['en_nonfinite', 'en_collocation']}, {'label': '第2题', 'stem': '选择：He has lived here ___ 2020. A. for B. since', 'work': 'A. for', 'answer': 'B. since。2020是时间起点，since接起点；for接时间段。', 'correct_parts': '注意到了时间表达。', 'issues': '混淆时间起点与持续时长。', 'evidence': 'A. for', 'check_action': '先判断时间是起点还是一段时长。', 'causes': ['语法', '审题'], 'knowledge_ids': ['en_tense_voice', 'en_articles_prepositions']}]
    with db.connect() as conn:
        conn.execute("INSERT INTO sources(id,name,study_date,created_at,kind,state,sample,warning) VALUES(?,?,?,?,?,'saved',1,?)",(sid,'示例练习 · 英语专题',date.today().isoformat(),db.now(),'image','这是用于体验页面流程的固定示例，不是阿里云模型分析结果。'))
        conn.execute('INSERT INTO files VALUES(?,?,?,?,?)',(fid,sid,'示例练习.jpg',str(path),'image'))
        conn.execute("INSERT INTO pages(id,source_id,number,path,status,subject,content_kind,recognition_version) VALUES(?,?,1,?,'success','英语','questions','sample-en-1')",(pid,sid,str(path)))
        for value in examples:
            qid=db.uid();q={**value,'id':qid,'version':1}
            conn.execute('INSERT INTO questions(id,source_id,page_id,label,stem,work,saved,reflection,created_at) VALUES(?,?,?,?,?,?,1,?,?)',(qid,sid,pid,value['label'],value['stem'],value['work'],value['check_action'],db.now()))
            conn.execute('INSERT INTO question_versions VALUES(?,?,?,?,?,?,?)',(db.uid(),qid,1,value['stem'],value['work'],0,db.now()))
            aid=jobs.insert_analysis(conn,q,{**value,'model':'sample','prompt_version':'sample-1','knowledge_version':KNOWLEDGE_VERSION,'proposal':value})
            conn.execute("UPDATE analyses SET status='confirmed',confirmed_at=? WHERE id=?",(db.now(),aid))
    return {'id':sid,'sample':True}


app.mount('/static',StaticFiles(directory=ROOT/'web'),name='static')


@app.get('/')
def index():
    return FileResponse(ROOT/'web'/'index.html',headers={'Cache-Control':'no-store'})
