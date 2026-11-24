import os
import sys

# Automatically ensure parent directory is in sys.path
# so 'app.main:app' and 'import app' work seamlessly even if cwd is 'app/'
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
