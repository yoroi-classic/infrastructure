#!/usr/bin/env python3
"""Update config.yaml through SOPS on an authorized operator machine."""
import argparse
import json
from pathlib import Path
import subprocess
import yaml
from helmfile_config import validate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("settings_file")
    args = parser.parse_args()
    settings = yaml.safe_load(Path(args.settings_file).read_text()).get("helmfile")
    try:
        validate(settings, complete=True)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    subprocess.run(["sops", "set", "--value-stdin", "config.yaml", '["helmfile"]'],
                   input=json.dumps(settings), text=True, check=True)


if __name__ == "__main__":
    main()
