import json
from pathlib import Path

RELEASE = json.loads(Path(__file__).with_name('release.json').read_text())
