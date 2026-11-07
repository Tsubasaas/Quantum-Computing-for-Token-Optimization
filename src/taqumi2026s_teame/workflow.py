"""依存関係から実行順序（STEP 段組み）を作る。

モデル割当は求解器（QUBO / Greedy）、実行順序はここ、と役割を分ける。
同じ段のタスクは前提が全て終われば同時に開始できる、という意味であって、
「無制限に並列実行してよい」という意味ではない（実運用の同時実行数は別管理）。

本モジュールは全体が生成 AI（Claude）支援で作成されています。
"""

from __future__ import annotations

from .models import Task

__all__ = ["levels", "dependency_errors"]


def dependency_errors(tasks: list[Task]) -> list[str]:
    """存在しない ID・自己参照・循環を検出して、利用者向けの説明文で返す。

    Args:
        tasks (list[Task]): 検査対象のタスク一覧。

    Returns:
        list[str]: 問題の説明。空なら依存関係は DAG として妥当。
    """

    known = {t.id for t in tasks}
    errors: list[str] = []
    for task in tasks:
        for dep in task.dependencies:
            if dep == task.id:
                errors.append(f"{task.id} が自分自身を前提にしています。")
            elif dep not in known:
                errors.append(f"{task.id} の前提 {dep} が存在しません。")
    if not errors and _has_cycle(tasks):
        errors.append("前提タスクが循環しています。依存関係を見直してください。")
    return errors


def _has_cycle(tasks: list[Task]) -> bool:
    known = {t.id for t in tasks}
    pending = {t.id: {d for d in t.dependencies if d in known} for t in tasks}
    done: set[str] = set()
    while pending:
        ready = [tid for tid, deps in pending.items() if deps <= done]
        if not ready:
            return True
        done.update(ready)
        for tid in ready:
            del pending[tid]
    return False


def levels(tasks: list[Task]) -> list[list[str]]:
    """タスクを実行段へ分ける。``[[STEP1 の task_id...], [STEP2 の...], ...]``。

    前提が全て前の段までに終わっているタスクを、同じ段へまとめる。循環がある場合は、
    どの段にも置けなくなった残りを最後の段へまとめて返す（画面を止めないため。
    循環そのものは :func:`dependency_errors` が別途報告する）。

    Args:
        tasks (list[Task]): 段分けするタスク一覧。

    Returns:
        list[list[str]]: 段ごとのタスク ID。タスクが無ければ空リスト。
    """

    if not tasks:
        return []
    order = [t.id for t in tasks]
    known = set(order)
    pending = {t.id: {d for d in t.dependencies if d in known and d != t.id} for t in tasks}
    result: list[list[str]] = []
    done: set[str] = set()
    while pending:
        ready = [tid for tid in order if tid in pending and pending[tid] <= done]
        if not ready:
            # 循環。残り全部を 1 段にまとめて打ち切る。
            result.append([tid for tid in order if tid in pending])
            break
        result.append(ready)
        done.update(ready)
        for tid in ready:
            del pending[tid]
    return result
