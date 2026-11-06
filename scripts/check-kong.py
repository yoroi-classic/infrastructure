#!/usr/bin/env python3
"""Validate gateway proxy configuration without printing pod environment values."""
import json
import sys
from helmfile_config import validate_gateway

try:
    validate_gateway(json.load(sys.stdin))
except (ValueError, KeyError, TypeError) as error:
    raise SystemExit("Kong prerequisite failed: " + str(error)) from error
print("Kong gateway proxy prerequisites verified")
