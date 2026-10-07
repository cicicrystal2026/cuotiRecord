"""Opt-in paid Alibaba integration test, with synthetic English work only."""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image, ImageDraw
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import ai
from app.config import settings

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-paid', action='store_true', help='Explicitly authorize paid model calls with the configured local API Key')
    args = parser.parse_args()
    if not args.allow_paid:
        parser.error('Paid calls require --allow-paid. No API call was made.')
    if not settings()['configured']:
        parser.error('Configure an Alibaba API Key in local settings first.')
    out = Path(__file__).resolve().parents[1] / 'test-results' / 'real-ai'
    out.mkdir(parents=True, exist_ok=True)
    fixture = out / 'english-synthetic.png'
    image = Image.new('RGB', (1300, 500), 'white')
    ImageDraw.Draw(image).text((40, 50), 'English grammar practice (synthetic)\nFill in: She enjoys ___ (read) books.\nStudent answer: read', fill='black', font_size=40)
    image.save(fixture)
    page = {'path': str(fixture), 'text': ''}
    recognized = ai.recognize(page)
    assert recognized['questions'], 'No exercise recognized'
    question = recognized['questions'][0]
    assert 'enjoy' in question['stem'].lower(), 'Missing exercise context'
    assert question['work'].strip(), 'Missing student work'
    result = ai.analyze(question, page)
    assert result['answer'] and result['knowledge_ids'], 'Missing answer or knowledge'
    assert result['evidence'] and result['evidence'] in question['work'], 'Evidence not located'
    missing = ai.analyze({'stem': 'Fill in: She enjoys ___ (read) books.', 'work': '', 'missing': True})
    assert missing['uncertainty'] and not missing['issues'] and not missing['evidence'] and not missing['causes']
    report = {'tested_at': datetime.now(timezone.utc).isoformat(), 'synthetic_fixture': True, 'models': settings(), 'recognition': recognized, 'analysis': result, 'missing_work': missing, 'passed': True}
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Paid synthetic English integration test passed; report in test-results/real-ai/report.json')

if __name__ == '__main__':
    main()
