"""自然言語の開発要求をタスク一覧へ分解する層。"""

from __future__ import annotations

from .decompose import Decomposition, decompose, decompose_request

__all__ = ["Decomposition", "decompose", "decompose_request"]
