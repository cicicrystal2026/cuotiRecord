SUBJECTS = [{'id': 'chinese', 'name': '语文'}, {'id': 'math', 'name': '数学'}, {'id': 'english', 'name': '英语'}, {'id': 'physics', 'name': '物理'}, {'id': 'politics', 'name': '政治'}, {'id': 'history', 'name': '历史'}, {'id': 'geography', 'name': '地理'}]
IDS={x['id'] for x in SUBJECTS}
def validate(value):
    if value not in IDS: raise ValueError('请选择有效学科')
    return value
