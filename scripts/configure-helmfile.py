#!/usr/bin/env python3
"""Merge deployment settings into config.yaml through SOPS on an authorized machine."""
import json
from pathlib import Path
import subprocess
import sys
import yaml

settings = yaml.safe_load(Path(sys.argv[1]).read_text())["helmfile"]
assignment = '["helmfile"] ' + json.dumps(settings)
subprocess.run(["sops", "--in-place", "--set", assignment, "config.yaml"], check=True)
