"""パッケージ未インストールでも `streamlit run app/app.py` が動くようにするパス調整。"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Streamlit の各ページを直接起動した場合も、プロジェクト直下の設定を使う。
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
