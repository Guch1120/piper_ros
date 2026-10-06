import os
import sys

# `pytest vlm_supervisor/tests` をどこから実行しても `import vlm_supervisor` できるように
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
