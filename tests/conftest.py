import os
import sys

# scripts/ and mcp_server/ have no __init__.py (namespace packages) and this
# repo has no installable pyproject.toml package yet -- match the same
# sys.path bootstrap every script in the repo already uses, so tests can
# `import scripts.xxx` / `import mcp_server.xxx` regardless of the directory
# pytest is invoked from.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
