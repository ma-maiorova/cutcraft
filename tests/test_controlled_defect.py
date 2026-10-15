import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from main import ROOT, run
from planner import build_plan


class ControlledDefectTests(unittest.TestCase):
    def test_injection_is_separate_from_model_output_and_only_changes_caption(self):
        catalog = json.loads((ROOT / 'data/catalog.json').read_text())
        original = build_plan('test', catalog, demo=True)
        def review(task, catalog, plan, frames, **kwargs):
            return {'schema_version': '1.0', 'items': [
                {'scene_id': s['scene_id'], 'decision': 'accept', 'issue': '', 'evidence': '', 'requested_change': ''}
                for s in plan['scenes']]}
        with tempfile.TemporaryDirectory() as directory, patch('main.build_plan', return_value=original), patch('main.review_plan', side_effect=review):
            out = Path(directory) / 'run'
            self.assertEqual(run('test', ROOT / 'data/catalog.json', out, controlled_defect=True), 'accepted')
            generated = json.loads((out / 'plan_generated.json').read_text())
            damaged = json.loads((out / 'plan_0.json').read_text())
            self.assertEqual(original, generated)
            self.assertNotEqual(generated['scenes'][0]['caption'], damaged['scenes'][0]['caption'])
            damaged['scenes'][0]['caption'] = generated['scenes'][0]['caption']
            self.assertEqual(generated, damaged)
            self.assertEqual(original, generated)  # Caller-owned model result was not mutated.
            text = (out / 'report.html').read_text()
            self.assertIn('КОНТРОЛЬНЫЙ ДЕФЕКТ', text)
            self.assertIn('не естественная ошибка модели', text)
            journal = json.loads((out / 'events.json').read_text())
            self.assertTrue(any(e['stage'] == 'controlled_defect' and e['actor'] == 'code' for e in journal['events']))

    def test_cannot_mix_fixed_demo_with_live_control(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                run('test', ROOT / 'data/catalog.json', Path(directory) / 'run', demo=True, controlled_defect=True)
