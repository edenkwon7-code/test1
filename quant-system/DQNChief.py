"""
DQNChief.py — 심층 강화학습(DQN) 자기진화형 비서실장
══════════════════════════════════════════════════════
순수 numpy 기반 Deep Q-Network. 외부 ML 라이브러리 불필요.

핵심 설계:
  상태(State)   : 시장 지표 + 3대 에이전트 성과 지표 (12차원 벡터)
  행동(Action)  : 예산 배분 전략 7가지 (이산 행동 공간)
  보상(Reward)  : 변동성 조정 수익률 — 손실 한도 초과 시 페널티
  경험 리플레이  : SQLite에 (s, a, r, s', done) 저장 → 배치 학습
  할인율(γ)    : 0.75  (단기충격 방어 + 중기 수익 균형)
  탐색(ε)      : 1.0 → 0.1 점진 감소 (greedy 비율 90%까지 수렴)
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# 행동 공간 (Action Space) — 7가지 예산 배분 전략
# ═══════════════════════════════════════════════════════════

ACTIONS: list[dict] = [
    {"id": 0, "label": "⚖️ 균형형",
     "value_finder": 0.33, "trend_rider": 0.33, "swing_master": 0.33, "cash": 0.01,
     "desc": "3대 에이전트 균등 분배 (기본 전략)"},
    {"id": 1, "label": "💎 가치주 집중형",
     "value_finder": 0.50, "trend_rider": 0.20, "swing_master": 0.20, "cash": 0.10,
     "desc": "밸류파인더 과반 — 안정적 상승장 최적"},
    {"id": 2, "label": "🏄 추세 집중형",
     "value_finder": 0.15, "trend_rider": 0.60, "swing_master": 0.15, "cash": 0.10,
     "desc": "트렌드라이더 주도 — 강한 상승 추세 최적"},
    {"id": 3, "label": "🏓 반등 집중형",
     "value_finder": 0.15, "trend_rider": 0.15, "swing_master": 0.60, "cash": 0.10,
     "desc": "스윙마스터 주도 — 횡보·반등 장세 최적"},
    {"id": 4, "label": "🛡️ 보수 방어형",
     "value_finder": 0.30, "trend_rider": 0.10, "swing_master": 0.30, "cash": 0.30,
     "desc": "현금 30% 확보 — 불확실성 구간 방어"},
    {"id": 5, "label": "⚔️ 공격 추세형",
     "value_finder": 0.10, "trend_rider": 0.70, "swing_master": 0.15, "cash": 0.05,
     "desc": "트렌드라이더 70% — 강세장 최대 공세"},
    {"id": 6, "label": "🚨 전시 방어형",
     "value_finder": 0.10, "trend_rider": 0.05, "swing_master": 0.15, "cash": 0.70,
     "desc": "현금 70% 사수 — 극단적 공포 구간 생존"},
]

N_STATES  = 12
N_ACTIONS = len(ACTIONS)


# ═══════════════════════════════════════════════════════════
# 순수 numpy 신경망 (2-hidden-layer MLP)
# ═══════════════════════════════════════════════════════════

class NumpyMLP:
    """
    2-hidden-layer MLP (Q-network & Target network 공유 구조)
    Layer sizes: 12 → 64 → 32 → 7
    """

    def __init__(self, n_in: int = N_STATES, n_h1: int = 64,
                 n_h2: int = 32, n_out: int = N_ACTIONS, lr: float = 1e-3):
        self.lr = lr
        rng = np.random.default_rng(42)

        # Xavier 초기화
        self.W1 = rng.standard_normal((n_in, n_h1))  * np.sqrt(2.0 / n_in)
        self.b1 = np.zeros(n_h1)
        self.W2 = rng.standard_normal((n_h1, n_h2)) * np.sqrt(2.0 / n_h1)
        self.b2 = np.zeros(n_h2)
        self.W3 = rng.standard_normal((n_h2, n_out)) * np.sqrt(2.0 / n_h2)
        self.b3 = np.zeros(n_out)

        # Adam optimizer moments
        self._adam_init()
        self.t = 0

    def _adam_init(self):
        self.mW1 = np.zeros_like(self.W1); self.vW1 = np.zeros_like(self.W1)
        self.mb1 = np.zeros_like(self.b1); self.vb1 = np.zeros_like(self.b1)
        self.mW2 = np.zeros_like(self.W2); self.vW2 = np.zeros_like(self.W2)
        self.mb2 = np.zeros_like(self.b2); self.vb2 = np.zeros_like(self.b2)
        self.mW3 = np.zeros_like(self.W3); self.vW3 = np.zeros_like(self.W3)
        self.mb3 = np.zeros_like(self.b3); self.vb3 = np.zeros_like(self.b3)

    @staticmethod
    def _relu(x: np.ndarray) -> np.ndarray:
        return np.maximum(0, x)

    @staticmethod
    def _relu_grad(x: np.ndarray) -> np.ndarray:
        return (x > 0).astype(float)

    def forward(self, x: np.ndarray) -> tuple[np.ndarray, dict]:
        """순전파. cache는 역전파에 필요한 중간값."""
        z1 = x @ self.W1 + self.b1
        a1 = self._relu(z1)
        z2 = a1 @ self.W2 + self.b2
        a2 = self._relu(z2)
        q  = a2 @ self.W3 + self.b3
        return q, {"x": x, "z1": z1, "a1": a1, "z2": z2, "a2": a2}

    def predict(self, x: np.ndarray) -> np.ndarray:
        q, _ = self.forward(x)
        return q

    def _adam_update(self, param, grad, m, v, β1=0.9, β2=0.999, ε=1e-8):
        self.t += 1
        m[:] = β1 * m + (1 - β1) * grad
        v[:] = β2 * v + (1 - β2) * grad ** 2
        m_hat = m / (1 - β1 ** self.t)
        v_hat = v / (1 - β2 ** self.t)
        param -= self.lr * m_hat / (np.sqrt(v_hat) + ε)

    def train_step(self, x: np.ndarray, target_q: np.ndarray) -> float:
        """
        배치 학습 1스텝. MSE loss, Adam optimizer.
        Returns: scalar loss
        """
        batch = x.shape[0]
        q, cache = self.forward(x)
        loss = np.mean((q - target_q) ** 2)

        # 역전파
        dq = 2.0 * (q - target_q) / batch                  # (B, 7)
        dW3 = cache["a2"].T @ dq
        db3 = dq.sum(axis=0)
        da2 = dq @ self.W3.T
        dz2 = da2 * self._relu_grad(cache["z2"])
        dW2 = cache["a1"].T @ dz2
        db2 = dz2.sum(axis=0)
        da1 = dz2 @ self.W2.T
        dz1 = da1 * self._relu_grad(cache["z1"])
        dW1 = cache["x"].T @ dz1
        db1 = dz1.sum(axis=0)

        self._adam_update(self.W3, dW3, self.mW3, self.vW3)
        self._adam_update(self.b3, db3, self.mb3, self.vb3)
        self._adam_update(self.W2, dW2, self.mW2, self.vW2)
        self._adam_update(self.b2, db2, self.mb2, self.vb2)
        self._adam_update(self.W1, dW1, self.mW1, self.vW1)
        self._adam_update(self.b1, db1, self.mb1, self.vb1)

        return float(loss)

    def copy_weights_from(self, other: "NumpyMLP"):
        """타깃 네트워크 업데이트 (하드 복사)"""
        self.W1 = other.W1.copy(); self.b1 = other.b1.copy()
        self.W2 = other.W2.copy(); self.b2 = other.b2.copy()
        self.W3 = other.W3.copy(); self.b3 = other.b3.copy()

    def to_dict(self) -> dict:
        return {
            "W1": self.W1.tolist(), "b1": self.b1.tolist(),
            "W2": self.W2.tolist(), "b2": self.b2.tolist(),
            "W3": self.W3.tolist(), "b3": self.b3.tolist(),
            "t":  self.t,
        }

    def from_dict(self, d: dict):
        self.W1 = np.array(d["W1"]); self.b1 = np.array(d["b1"])
        self.W2 = np.array(d["W2"]); self.b2 = np.array(d["b2"])
        self.W3 = np.array(d["W3"]); self.b3 = np.array(d["b3"])
        self.t  = d.get("t", 0)
        self._adam_init()


# ═══════════════════════════════════════════════════════════
# 상태 벡터 생성 헬퍼
# ═══════════════════════════════════════════════════════════

def build_state(
    vix: float,
    ma_alignment: str,
    macd_signal: str,
    vf_winrate: float,  vf_sharpe: float,
    tr_winrate: float,  tr_sharpe: float,
    sm_winrate: float,  sm_sharpe: float,
    portfolio_daily_return: float,
    portfolio_mdd: float,
    cash_ratio: float,
) -> np.ndarray:
    """
    12차원 상태 벡터 생성 (모두 -1 ~ 1 혹은 0 ~ 1 범위로 정규화)
    """
    ma_score = {"BULLISH": 1.0, "MIXED": 0.0, "BEARISH": -1.0,
                "UNKNOWN": 0.0, "INSUFFICIENT_DATA": 0.0}.get(ma_alignment, 0.0)
    macd_score = {
        "BULLISH_MOMENTUM": 1.0, "WEAKENING_BULL": 0.3,
        "WEAKENING_BEAR": -0.3,  "BEARISH_MOMENTUM": -1.0, "UNKNOWN": 0.0,
    }.get(macd_signal, 0.0)

    state = np.array([
        np.clip(vix / 50.0, 0.0, 1.0),                    # 0: VIX 정규화
        ma_score,                                          # 1: MA 배열
        macd_score,                                        # 2: MACD 모멘텀
        np.clip(vf_winrate, 0.0, 1.0),                    # 3: 밸류파인더 승률
        np.clip(vf_sharpe / 3.0, -1.0, 1.0),             # 4: 밸류파인더 샤프
        np.clip(tr_winrate, 0.0, 1.0),                    # 5: 트렌드라이더 승률
        np.clip(tr_sharpe / 3.0, -1.0, 1.0),             # 6: 트렌드라이더 샤프
        np.clip(sm_winrate, 0.0, 1.0),                    # 7: 스윙마스터 승률
        np.clip(sm_sharpe / 3.0, -1.0, 1.0),             # 8: 스윙마스터 샤프
        np.clip(portfolio_daily_return / 0.05, -1.0, 1.0),# 9: 일일 수익률
        np.clip(abs(portfolio_mdd) / 0.20, 0.0, 1.0),    # 10: MDD
        np.clip(cash_ratio, 0.0, 1.0),                    # 11: 현금 비율
    ], dtype=np.float32)
    return state


def compute_reward(
    daily_return: float,
    vix: float,
    hit_risk_limit: bool,
) -> float:
    """
    보상 함수 — 변동성 조정 수익률 + 위험 패널티
    reward = daily_return / max(vix_norm, 0.05) - risk_penalty
    """
    vix_norm = max(vix / 30.0, 0.05)
    base_reward = float(daily_return) / vix_norm        # 변동성 조정 수익
    risk_penalty = -2.0 if hit_risk_limit else 0.0     # 손실 한도 초과 페널티
    return float(np.clip(base_reward + risk_penalty, -3.0, 3.0))


# ═══════════════════════════════════════════════════════════
# DQN 에이전트 (비서실장 AI 코어)
# ═══════════════════════════════════════════════════════════

class DQNChief:
    """
    DQN 기반 비서실장.
    규칙 기반 시스템과 병행 운용 — DQN 모드 활성화 시 예산 배분에 우선 적용.
    """

    BUFFER_MAX      = 2000
    BATCH_SIZE      = 32
    GAMMA           = 0.75
    EPSILON_START   = 1.0
    EPSILON_MIN     = 0.10
    EPSILON_DECAY   = 0.98
    TARGET_UPDATE_FREQ = 20   # 20 스텝마다 타깃 네트워크 동기화

    def __init__(self, db_path: str = "quant_system.db"):
        self.db_path = db_path
        self.q_net      = NumpyMLP()
        self.target_net = NumpyMLP()
        self.target_net.copy_weights_from(self.q_net)
        self.epsilon    = self.EPSILON_START
        self.step_count = 0
        self._init_db()
        self._load_model()

    # ── DB 초기화 ───────────────────────────────────────────

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS dqn_replay_buffer (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    state_json  TEXT NOT NULL,
                    action      INTEGER NOT NULL,
                    reward      REAL NOT NULL,
                    next_state_json TEXT NOT NULL,
                    done        INTEGER NOT NULL DEFAULT 0,
                    recorded_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS dqn_model (
                    id         INTEGER PRIMARY KEY CHECK (id = 1),
                    weights_json TEXT NOT NULL,
                    epsilon    REAL NOT NULL DEFAULT 1.0,
                    step_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS dqn_training_log (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    episode    INTEGER NOT NULL,
                    loss       REAL NOT NULL,
                    avg_reward REAL NOT NULL,
                    epsilon    REAL NOT NULL,
                    buffer_size INTEGER NOT NULL,
                    trained_at TEXT NOT NULL
                );
            """)

    # ── 모델 저장/불러오기 ──────────────────────────────────

    def _save_model(self):
        weights = self.q_net.to_dict()
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO dqn_model
                   (id, weights_json, epsilon, step_count, updated_at)
                   VALUES (1, ?, ?, ?, ?)""",
                (json.dumps(weights), self.epsilon, self.step_count, now),
            )

    def _load_model(self):
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT * FROM dqn_model WHERE id=1").fetchone()
            if row:
                d = json.loads(row[1])
                self.q_net.from_dict(d)
                self.target_net.copy_weights_from(self.q_net)
                self.epsilon    = row[2]
                self.step_count = row[3]
                logger.info(f"[DQNChief] 모델 복원 완료 (ε={self.epsilon:.3f}, step={self.step_count})")
            else:
                logger.info("[DQNChief] 신규 모델 초기화")

    # ── 경험 리플레이 버퍼 ─────────────────────────────────

    def store_experience(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        next_state: np.ndarray,
        done: bool = False,
    ):
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM dqn_replay_buffer"
            ).fetchone()[0]
            if count >= self.BUFFER_MAX:
                conn.execute(
                    "DELETE FROM dqn_replay_buffer WHERE id IN "
                    "(SELECT id FROM dqn_replay_buffer ORDER BY id ASC LIMIT ?)",
                    (count - self.BUFFER_MAX + 1,),
                )
            conn.execute(
                """INSERT INTO dqn_replay_buffer
                   (state_json, action, reward, next_state_json, done, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    json.dumps(state.tolist()),
                    int(action),
                    float(reward),
                    json.dumps(next_state.tolist()),
                    1 if done else 0,
                    now,
                ),
            )

    def _sample_batch(self) -> Optional[list]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT state_json, action, reward, next_state_json, done "
                "FROM dqn_replay_buffer ORDER BY RANDOM() LIMIT ?",
                (self.BATCH_SIZE,),
            ).fetchall()
        if len(rows) < self.BATCH_SIZE:
            return None
        return rows

    def get_buffer_size(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM dqn_replay_buffer"
            ).fetchone()[0]

    # ── 행동 선택 (ε-greedy) ──────────────────────────────

    def select_action(self, state: np.ndarray, force_greedy: bool = False) -> int:
        """
        ε-greedy 탐색.
        force_greedy=True: 실제 거래 시 greedy 선택 강제
        """
        if not force_greedy and np.random.random() < self.epsilon:
            return int(np.random.randint(N_ACTIONS))
        q_vals = self.q_net.predict(state[np.newaxis, :])[0]
        return int(np.argmax(q_vals))

    def get_q_values(self, state: np.ndarray) -> np.ndarray:
        """현재 상태의 Q값 반환 (대시보드 시각화용)"""
        return self.q_net.predict(state[np.newaxis, :])[0]

    # ── 학습 (Experience Replay 배치) ─────────────────────

    def train_episode(self, n_batches: int = 10) -> dict:
        """
        경험 리플레이 배치로 신경망 학습.
        Returns: {episodes, avg_loss, avg_reward, epsilon, buffer_size}
        """
        buffer_size = self.get_buffer_size()
        if buffer_size < self.BATCH_SIZE:
            return {
                "episodes": 0, "avg_loss": None, "avg_reward": None,
                "epsilon": self.epsilon, "buffer_size": buffer_size,
                "msg": f"경험 부족 ({buffer_size}/{self.BATCH_SIZE}). 사이클 실행 후 재시도하세요.",
            }

        losses, rewards = [], []
        for _ in range(n_batches):
            batch = self._sample_batch()
            if batch is None:
                continue

            states      = np.array([json.loads(r[0]) for r in batch], dtype=np.float32)
            actions     = np.array([r[1] for r in batch], dtype=int)
            rewards_b   = np.array([r[2] for r in batch], dtype=np.float32)
            next_states = np.array([json.loads(r[3]) for r in batch], dtype=np.float32)
            dones       = np.array([r[4] for r in batch], dtype=np.float32)

            # 타깃 Q값 계산 (Bellman 방정식)
            q_next   = self.target_net.predict(next_states)                 # (B, 7)
            q_target = self.q_net.predict(states).copy()                    # (B, 7)

            for i in range(len(batch)):
                if dones[i]:
                    q_target[i, actions[i]] = rewards_b[i]
                else:
                    q_target[i, actions[i]] = rewards_b[i] + self.GAMMA * np.max(q_next[i])

            loss = self.q_net.train_step(states, q_target)
            losses.append(loss)
            rewards.extend(rewards_b.tolist())

        self.step_count += n_batches

        # 타깃 네트워크 동기화
        if self.step_count % self.TARGET_UPDATE_FREQ == 0:
            self.target_net.copy_weights_from(self.q_net)
            logger.info(f"[DQNChief] 타깃 네트워크 업데이트 (step={self.step_count})")

        # 탐색률 감소
        self.epsilon = max(self.EPSILON_MIN, self.epsilon * self.EPSILON_DECAY)

        avg_loss   = float(np.mean(losses)) if losses else 0.0
        avg_reward = float(np.mean(rewards)) if rewards else 0.0

        # 학습 이력 저장
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO dqn_training_log
                   (episode, loss, avg_reward, epsilon, buffer_size, trained_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (self.step_count, avg_loss, avg_reward, self.epsilon, buffer_size, now),
            )

        self._save_model()

        return {
            "episodes":   self.step_count,
            "avg_loss":   avg_loss,
            "avg_reward": avg_reward,
            "epsilon":    self.epsilon,
            "buffer_size": buffer_size,
            "msg": f"학습 완료 — loss={avg_loss:.4f} | ε={self.epsilon:.3f} | 버퍼={buffer_size}건",
        }

    def get_training_history(self, limit: int = 50) -> list[dict]:
        """학습 이력 조회 (차트용)"""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT episode, loss, avg_reward, epsilon, buffer_size, trained_at "
                "FROM dqn_training_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {"episode": r[0], "loss": r[1], "avg_reward": r[2],
             "epsilon": r[3], "buffer_size": r[4], "trained_at": r[5]}
            for r in reversed(rows)
        ]

    # ── 에이전트 성과 지표 계산 ────────────────────────────

    @staticmethod
    def compute_agent_metrics(trades: list[dict], agent_name: str) -> dict:
        """
        거래 이력에서 에이전트별 성과 지표 계산.
        Returns: {win_rate, avg_return, sharpe, mdd}
        """
        agent_sells = [
            t for t in trades
            if t.get("agent_name") == agent_name and t.get("action") == "SELL"
        ]
        if not agent_sells:
            return {"win_rate": 0.5, "avg_return": 0.0, "sharpe": 0.0, "mdd": 0.0}

        returns = []
        for t in agent_sells:
            amt = t.get("total_amount", 1) or 1
            pnl = t.get("realized_pnl", 0) or 0
            returns.append(float(pnl) / float(amt))

        arr     = np.array(returns)
        win_rate = float(np.mean(arr > 0))
        avg_ret  = float(np.mean(arr))
        std_ret  = float(np.std(arr)) if len(arr) > 1 else 1e-6
        sharpe   = avg_ret / max(std_ret, 1e-6)
        cumul    = np.cumprod(1 + arr) - 1
        peak     = np.maximum.accumulate(cumul)
        drawdown = float(np.min(cumul - peak)) if len(cumul) > 0 else 0.0

        return {
            "win_rate":   float(np.clip(win_rate, 0.0, 1.0)),
            "avg_return": avg_ret,
            "sharpe":     float(np.clip(sharpe, -5.0, 5.0)),
            "mdd":        drawdown,
        }

    # ── 추천 배분 → config.yaml 반영 ───────────────────────

    @staticmethod
    def action_to_allocation(action_id: int) -> dict:
        """행동 ID → 예산 배분 비중 딕셔너리"""
        a = ACTIONS[action_id]
        return {
            "value_finder": a["value_finder"],
            "trend_rider":  a["trend_rider"],
            "swing_master": a["swing_master"],
            "cash":         a["cash"],
        }
