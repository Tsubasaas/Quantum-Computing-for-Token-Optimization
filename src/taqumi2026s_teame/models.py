"""Q-Orchestrator のドメインモデル（タスク・エージェント・最適化設定・結果）。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Task:
    """開発タスク 1 件。``role`` は :data:`taqumi2026s_teame.data.task_types.ROLES` のいずれか。"""

    id: str
    title: str
    role: str
    difficulty: int = 3  # 1..5
    priority: int = 3  # 1..5（重要度 w_j = priority / 5）
    est_time: float = 2.0  # 見積り作業量（時間）
    dependencies: list[str] = field(default_factory=list)
    confidential: bool = False
    # 成果物の個数（画像なら生成枚数）。コストは C_ja × quantity で線形に増える。
    # QUBO の変数・制約・目的関数の形は変えない（c 行列のスケールだけが変わる）。
    quantity: int = 1
    deliverable: str = ""  # 画面表示用の成果物名。最適化には使わない。

    @property
    def weight(self) -> float:
        return self.priority / 5.0


@dataclass(slots=True)
class Agent:
    """割当候補となる AI モデル / コーディングエージェント。

    ``quality`` は役割ブレンドで合成済みの Q_ja（0..1）。生のベンチマーク値は
    ``capability`` / ``benchmark_scores`` 側に持つ。
    """

    id: str
    name: str
    layer: str  # "agent"（Codex 等）| "model"（素のモデル）
    external: bool  # True なら社外 API。機密タスクへ割当不可
    quality: dict[str, float]  # role -> 合成品質 Q_ja（0..1）
    reliability: dict[str, float]  # role -> 信頼性 Pass@5 相当（0..1）
    cost_per_task: float  # 1 タスクあたりコスト（USD、既定難易度）
    latency_sec: float  # 1 タスクあたり基準処理時間（秒）
    max_tasks: int | None = None
    provider: str = ""
    model_type: str = "llm"  # llm | coding_agent | image | video | audio
    is_agent: bool = False
    agent_harness: str | None = None
    context_window: int | None = None
    capability: dict[str, float | None] = field(default_factory=dict)  # 生の正規化スコア
    pricing: dict[str, float | None] = field(default_factory=dict)

    def q(self, role: str) -> float:
        return float(self.quality.get(role, 0.0))

    def r(self, role: str) -> float:
        return float(self.reliability.get(role, 0.0))

    def can_do(self, role: str) -> bool:
        return role in self.quality


@dataclass(slots=True)
class Weights:
    """目的関数の重み。

    ``F = α·品質 + β·信頼性 − γ·コスト(正規化) − μ·担当数のばらつき``

    ユーザーが動かすのは γ（品質⟷コストのトレードオフ）だけ。
    β（信頼性）と μ（負荷分散）は運用上の配慮として固定寄り。
    """

    alpha: float = 1.0
    beta: float = 0.4
    gamma: float = 1.0
    mu: float = 0.2


@dataclass(slots=True)
class SolveOptions:
    budget: float | None = None  # 予算上限 B（USD）
    deadline: float | None = None  # 締切上限 D（秒・エージェント別 makespan）
    hard_capacity: bool = False
    seed: int = 0


@dataclass(slots=True)
class SolveMetric:
    method: str
    objective: float
    exp_quality: float  # Σ w_j q_ij x_ij
    reliability: float  # Σ w_j r_ij x_ij
    cost_total: float
    makespan: float
    load_std: float
    feasible: bool
    within_budget: bool
    within_deadline: bool
    violations: int
    solve_ms: float
    message: str = ""


@dataclass(slots=True)
class AssignmentResult:
    method: str
    assignments: dict[str, str]  # task_id -> agent_id
    metric: SolveMetric
    per_agent: dict[str, list[str]]  # agent_id -> [task_id, ...]
