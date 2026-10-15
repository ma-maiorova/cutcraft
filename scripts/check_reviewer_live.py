"""Реальная проверка критика на трёх контрольных случаях: по одному запросу к модели на случай.
Планы подготовлены вручную; это проверка агента-критика, а не монтажёра.
Использование: python3 scripts/check_reviewer_live.py [--case correct|lost_caveat|wrong_frame]
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from main import resolve_frames
from model_client import load_environment
from contracts import validate_catalog, validate_plan
from reviewer import review_plan

CASES = ROOT / "docs/evidence/reviewer/cases"


def score(review, expected):
    """Пропуск — ожидалось замечание, а критик принял; ложный отказ — ожидалось accept, а критик отклонил."""
    got = {i["scene_id"]: i["decision"] for i in review["items"]}
    misses = [s for s, ok in expected.items() if "accept" not in ok and got[s] == "accept"]
    false_rejects = [s for s, ok in expected.items() if ok == ["accept"] and got[s] != "accept"]
    wrong_kind = [s for s, ok in expected.items() if got[s] != "accept" and got[s] not in ok and s not in false_rejects]
    return {"decisions": got, "misses": misses, "false_rejects": false_rejects, "other_decision": wrong_kind,
            "passed": not (misses or false_rejects or wrong_kind)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    spec = json.loads((CASES / "cases.json").read_text(encoding="utf-8"))
    parser.add_argument("--case", choices=[c["name"] for c in spec["cases"]])
    args = parser.parse_args()
    load_environment()
    out = ROOT / "output" / ("reviewer-live-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    out.mkdir(parents=True)
    save = lambda name, value: (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    results = []
    for case in spec["cases"]:
        if args.case and case["name"] != args.case:
            continue
        started = time.monotonic()
        print(f"… {case['name']}: отправляю план и кадры модели {os.getenv('VISION_MODEL_NAME')}, "
              f"жду ответ не дольше ~{2 * float(os.getenv('MODEL_TIMEOUT_SECONDS', '60')):g} с", flush=True)
        try:
            catalog = validate_catalog(json.loads((CASES / case["catalog"]).read_text(encoding="utf-8")))
            plan = validate_plan(json.loads((CASES / case["plan"]).read_text(encoding="utf-8")), catalog)
            review = review_plan(spec["task"], catalog, plan, resolve_frames(catalog, CASES))
            save(f"{case['name']}_review.json", review)
            result = {"case": case["name"], **score(review, case["expected"])}
        except Exception as exc:
            result = {"case": case["name"], "passed": False, "error_type": type(exc).__name__, "message": str(exc)}
            if getattr(exc, "usage", None):
                result["usage"] = exc.usage
            if getattr(exc, "partial", None):
                (out / f"{case['name']}_partial.txt").write_text(exc.partial, encoding="utf-8")
                result["partial_file"] = f"{case['name']}_partial.txt"
        result["seconds"] = round(time.monotonic() - started, 2)
        results.append(result)
        print(("OK   " if result["passed"] else "FAIL ") + case["name"] + ": " + json.dumps({k: v for k, v in result.items() if k not in ("case", "passed")}, ensure_ascii=False))
    summary = {"model": os.getenv("VISION_MODEL_NAME"), "utc": datetime.now(timezone.utc).isoformat(),
               "dataset": "docs/evidence/reviewer/cases (synthetic PNG illustrations, assets_are_real=false)",
               "plans_origin": "hand-written control plans, not planner agent",
               "model_calls": sum(1 for r in results if "decisions" in r), "results": results}
    save("result.json", summary)
    print(f"Результаты: {out}")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
