import json
import os
from pathlib import Path
import subprocess
import sys

from sdd.__main__ import run_tests, validate_baseline

ROOT = Path(__file__).resolve().parents[1]


def test_baseline_is_behavior_failure(tmp_path):
    record, report = run_tests(tmp_path, "before")
    validate_baseline(record, report)
    assert record["exit_code"] == 1


def test_powercontext_persists_across_processes(tmp_path):
    code = """
import json, sys
from pathlib import Path
from sdd.state import state
record = {'done': ['baseline checked'], 'todo': ['implement status']} if sys.argv[2] == 'save' else None
print(json.dumps(state(Path(sys.argv[1]), 'restart-proof', record)))
"""
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    saved = subprocess.run([sys.executable, "-c", code, str(tmp_path), "save"],
                           capture_output=True, text=True, check=True, env=env)
    restored = subprocess.run([sys.executable, "-c", code, str(tmp_path), "read"],
                              capture_output=True, text=True, check=True, env=env)
    entry = json.loads(saved.stdout)["entry"]
    hits = json.loads(restored.stdout)["hits"]
    assert any(hit["text"] == entry["text"] and hit["citation"] == entry["citation"] for hit in hits)
