# Docstring
- python関数には、必ずGoogle形式（Args, Returns）のDocstringを日本語で追加すること。Noneの場合は、セクションは省略すること。

例:
```python
def add(a: int, b: int) -> int:
    """2つの整数を加算する関数。

    Args:
        a (int): 加算する最初の整数。
        b (int): 加算する2番目の整数。

    Returns:
        int: 加算結果。
    """
    return a + b
```
- クラスにも日本語のGoogle形式Docstringを付けること。必要に応じて Attributes を記述すること。

# 型アノテーション
- 初出の変数には必ず型アノテーションを付けること。
- すべての関数・メソッドに戻り値の型アノテーションを付けること。戻り値がない場合は -> None を明示すること。
- Any は原則使用しないこと。使用する場合は、その必要性が明確な箇所に限定すること。
- list、dict、tuple などのコレクション型は、要素型まで明示すること。
- Optional 相当の値は、Pythonのバージョンが許せば T | None の形式を使用すること。

# pytest
- pytestには、Argsに加え、関数のテストケース例をExampleとしてDocstringに記述すること。
- pytestには、適宜conftest.pyやfixturesを活用すること。

# Error
- ErrorやWarningを握りつぶさないこと。

# logger
- 基本 print を使用せず、logger を使用すること。
- 各モジュールで logger を定義し、以下の共通の設定を使用すること。

```python
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(levelname)s:%(name)s:%(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
```

# Content Exclusion
- コンテキストに含めないファイル・情報の基準は、[.github/instructions/content-exclusion.instructions.md](.github/instructions/content-exclusion.instructions.md) を参照すること。