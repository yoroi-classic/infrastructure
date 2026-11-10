#!/usr/bin/env python3
"""Validate settings before credentialed Helmfile operations."""
import argparse
from pathlib import Path
import yaml
from helmfile_config import validate, write_github_env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--deploy", action="store_true")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--github-env")
    parser.add_argument("--authenticated-project")
    args = parser.parse_args()
    config = yaml.safe_load(Path(args.config).read_text()).get("helmfile")
    try:
        validate(config, complete=args.deploy, require_enabled=args.deploy,
                 authenticated_project=args.authenticated_project)
        if args.github_env:
            write_github_env(config, args.github_env)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print("Helmfile configuration validated")


if __name__ == "__main__":
    main()
