"""Два реальных запроса: создание + исправление контролируемого дефекта.
Каталог учебный; замечание подготовлено кодом, это НЕ проверка агента Галима.
"""
import json
import os
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from planner import build_plan, revise_plan
from model_client import load_environment
from contracts import validate_plan, validate_review, validate_revision


def main():
    load_environment()
    out = ROOT / 'output' / ('planner-live-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    out.mkdir(parents=True)
    task = 'Объясни результат и ограничения метода'
    catalog = json.loads((ROOT/'examples/catalog.json').read_text())
    started = time.monotonic()
    def save(name, value):
        (out/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    try:
        initial = validate_plan(build_plan(task, catalog), catalog)
        save('initial.json', initial)
        broken = deepcopy(initial)
        broken['scenes'][0]['caption'] = 'Метод доказал эффективность во всех реальных условиях.'
        save('controlled_defect.json', broken)
        review = {'schema_version':'1.0','items':[
            {'scene_id':s['scene_id'], 'decision':'revise_caption' if i==0 else 'accept',
             'issue':'Подпись содержит неподтверждённое утверждение' if i==0 else '',
             'evidence':s['source_quote'] if i==0 else '',
             'requested_change':'Замени подпись точным текстом source_quote этой сцены; остальные сцены сохрани полностью.' if i==0 else ''}
            for i,s in enumerate(broken['scenes'])]}
        validate_review(review, broken)
        save('manual_review.json', review)
        revised = validate_revision(broken, revise_plan(task, catalog, broken, review), review, catalog)
        if revised['scenes'][0]['caption'] != initial['scenes'][0]['source_quote']:
            raise ValueError('Модель не выполнила конкретную контрольную правку')
        save('revised.json', revised)
        save('result.json', {'status':'passed','model':os.getenv('TEXT_MODEL_NAME'),
            'utc':datetime.now(timezone.utc).isoformat(),'seconds':round(time.monotonic()-started,2),
            'dataset':'examples/catalog.json (synthetic, assets_are_real=false)',
            'review_origin':'controlled manual fixture, not reviewer agent',
            'accepted_scenes_preserved':True,'model_calls':2})
    except Exception as exc:
        save('result.json', {'status':'failed','error_type':type(exc).__name__,'message':str(exc)})
        print(f'Проверка не завершена: {exc}; результаты: {out}', file=sys.stderr)
        return 1
    print(f'Два реальных вызова выполнены, контрольная правка подтверждена: {out}')
    return 0

if __name__=='__main__':
    sys.exit(main())
