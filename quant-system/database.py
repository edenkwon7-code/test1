"""
데이터베이스 관리 모듈 (SQLite 기반)
포트폴리오, 거래 내역, 레짐 히스토리 관리
"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class QuantDatabase:
    def __init__(self, db_path: str = "quant_system.db"):
        self.db_path = db_path
        self._init_db()
        # 추가 컬럼 마이그레이션 (기존 DB 호환성 보장)
        try:
            self.migrate_kakao_columns()
        except Exception:
            pass
        try:
            self.migrate_trading_features()
        except Exception:
            pass

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS portfolio (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mode TEXT NOT NULL DEFAULT 'paper',
                    total_capital REAL NOT NULL,
                    cash REAL NOT NULL,
                    invested REAL NOT NULL,
                    total_pnl REAL DEFAULT 0,
                    daily_pnl REAL DEFAULT 0,
                    daily_pnl_pct REAL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mode TEXT NOT NULL DEFAULT 'paper',
                    ticker TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    avg_cost REAL NOT NULL,
                    current_price REAL,
                    market_value REAL,
                    unrealized_pnl REAL DEFAULT 0,
                    unrealized_pnl_pct REAL DEFAULT 0,
                    opened_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(mode, ticker, agent_name)
                );

                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mode TEXT NOT NULL DEFAULT 'paper',
                    ticker TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    action TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    price REAL NOT NULL,
                    commission REAL DEFAULT 0,
                    total_amount REAL NOT NULL,
                    reason TEXT,
                    regime TEXT,
                    executed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS regime_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    regime TEXT NOT NULL,
                    vix REAL,
                    vix_signal TEXT,
                    ma_alignment TEXT,
                    macd_signal TEXT,
                    confidence REAL,
                    notes TEXT,
                    recorded_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS daily_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mode TEXT NOT NULL DEFAULT 'paper',
                    date TEXT NOT NULL,
                    total_value REAL NOT NULL,
                    daily_return REAL DEFAULT 0,
                    cumulative_return REAL DEFAULT 0,
                    drawdown REAL DEFAULT 0,
                    benchmark_return REAL DEFAULT 0,
                    UNIQUE(mode, date)
                );

                CREATE TABLE IF NOT EXISTS system_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT NOT NULL,
                    module TEXT,
                    message TEXT NOT NULL,
                    logged_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS system_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    emergency_stop INTEGER NOT NULL DEFAULT 0,
                    kill_switch_reason TEXT DEFAULT '',
                    daily_loss_pct REAL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                INSERT OR IGNORE INTO system_state (id, emergency_stop, kill_switch_reason, updated_at)
                VALUES (1, 0, '', datetime('now'));

                CREATE TABLE IF NOT EXISTS users (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    email               TEXT NOT NULL UNIQUE,
                    password_hash       TEXT NOT NULL DEFAULT '',
                    name                TEXT NOT NULL DEFAULT '투자자',
                    target_return       REAL NOT NULL DEFAULT 0.15,
                    risk_profile        TEXT NOT NULL DEFAULT 'balanced',
                    initial_capital     REAL NOT NULL DEFAULT 100000000,
                    is_admin            INTEGER NOT NULL DEFAULT 0,
                    emergency_stop      INTEGER NOT NULL DEFAULT 0,
                    created_at          TEXT NOT NULL,
                    kakao_id            TEXT UNIQUE,
                    kakao_access_token  TEXT DEFAULT '',
                    kakao_notify        INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS backtest_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    strategy_name TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    initial_capital REAL NOT NULL,
                    final_capital REAL NOT NULL,
                    total_return REAL NOT NULL,
                    annual_return REAL NOT NULL,
                    sharpe_ratio REAL NOT NULL,
                    sortino_ratio REAL NOT NULL,
                    max_drawdown REAL NOT NULL,
                    win_rate REAL NOT NULL,
                    total_trades INTEGER NOT NULL,
                    winning_trades INTEGER NOT NULL,
                    losing_trades INTEGER NOT NULL,
                    avg_win REAL NOT NULL,
                    avg_loss REAL NOT NULL,
                    profit_factor REAL NOT NULL,
                    benchmark_return REAL NOT NULL,
                    alpha REAL NOT NULL,
                    equity_curve_json TEXT,
                    ran_at TEXT NOT NULL
                );
                """
            )
        logger.info(f"[DB] 데이터베이스 초기화 완료: {self.db_path}")

    def upsert_portfolio(
        self,
        total_capital: float,
        cash: float,
        invested: float,
        total_pnl: float,
        daily_pnl: float,
        daily_pnl_pct: float,
        mode: str = "paper",
    ):
        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT id FROM portfolio WHERE mode = ?", (mode,)
            ).fetchone()
            now = datetime.now().isoformat()
            if existing:
                conn.execute(
                    """UPDATE portfolio SET total_capital=?, cash=?, invested=?,
                    total_pnl=?, daily_pnl=?, daily_pnl_pct=?, updated_at=?
                    WHERE mode=?""",
                    (total_capital, cash, invested, total_pnl, daily_pnl, daily_pnl_pct, now, mode),
                )
            else:
                conn.execute(
                    """INSERT INTO portfolio (mode, total_capital, cash, invested,
                    total_pnl, daily_pnl, daily_pnl_pct, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (mode, total_capital, cash, invested, total_pnl, daily_pnl, daily_pnl_pct, now),
                )

    def get_portfolio(self, mode: str = "paper") -> dict:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM portfolio WHERE mode = ?", (mode,)
            ).fetchone()
            if row:
                return dict(row)
            return {
                "total_capital": 100_000_000,
                "cash": 100_000_000,
                "invested": 0,
                "total_pnl": 0,
                "daily_pnl": 0,
                "daily_pnl_pct": 0,
            }

    def upsert_position(
        self,
        ticker: str,
        agent_name: str,
        quantity: float,
        avg_cost: float,
        current_price: float,
        mode: str = "paper",
    ):
        market_value = quantity * current_price
        unrealized_pnl = (current_price - avg_cost) * quantity
        unrealized_pnl_pct = (current_price - avg_cost) / avg_cost if avg_cost > 0 else 0
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO positions (mode, ticker, agent_name, quantity, avg_cost,
                current_price, market_value, unrealized_pnl, unrealized_pnl_pct,
                opened_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mode, ticker, agent_name) DO UPDATE SET
                quantity=excluded.quantity, avg_cost=excluded.avg_cost,
                current_price=excluded.current_price, market_value=excluded.market_value,
                unrealized_pnl=excluded.unrealized_pnl,
                unrealized_pnl_pct=excluded.unrealized_pnl_pct,
                updated_at=excluded.updated_at""",
                (
                    mode, ticker, agent_name, quantity, avg_cost,
                    current_price, market_value, unrealized_pnl, unrealized_pnl_pct,
                    now, now,
                ),
            )

    def remove_position(self, ticker: str, agent_name: str, mode: str = "paper"):
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM positions WHERE mode=? AND ticker=? AND agent_name=?",
                (mode, ticker, agent_name),
            )

    def get_positions(self, mode: str = "paper") -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM positions WHERE mode=? ORDER BY market_value DESC",
                (mode,),
            ).fetchall()
            return [dict(r) for r in rows]

    def record_trade(
        self,
        ticker: str,
        agent_name: str,
        action: str,
        quantity: float,
        price: float,
        commission: float,
        total_amount: float,
        reason: str = "",
        regime: str = "",
        mode: str = "paper",
    ):
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO trades (mode, ticker, agent_name, action, quantity,
                price, commission, total_amount, reason, regime, executed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    mode, ticker, agent_name, action, quantity, price,
                    commission, total_amount, reason, regime,
                    datetime.now().isoformat(),
                ),
            )

    def get_trades(self, mode: str = "paper", limit: int = 100) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM trades WHERE mode=? ORDER BY executed_at DESC LIMIT ?",
                (mode, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def record_regime(self, regime_signal) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO regime_history (regime, vix, vix_signal, ma_alignment,
                macd_signal, confidence, notes, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    regime_signal.regime.value,
                    regime_signal.vix,
                    regime_signal.vix_signal,
                    regime_signal.ma_alignment,
                    regime_signal.macd_signal,
                    regime_signal.confidence,
                    regime_signal.notes,
                    datetime.now().isoformat(),
                ),
            )

    def get_regime_history(self, limit: int = 50) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM regime_history ORDER BY recorded_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def record_daily_performance(
        self,
        total_value: float,
        daily_return: float,
        cumulative_return: float,
        drawdown: float,
        benchmark_return: float = 0.0,
        mode: str = "paper",
    ):
        date = datetime.now().strftime("%Y-%m-%d")
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO daily_performance (mode, date, total_value, daily_return,
                cumulative_return, drawdown, benchmark_return)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mode, date) DO UPDATE SET
                total_value=excluded.total_value,
                daily_return=excluded.daily_return,
                cumulative_return=excluded.cumulative_return,
                drawdown=excluded.drawdown,
                benchmark_return=excluded.benchmark_return""",
                (mode, date, total_value, daily_return, cumulative_return, drawdown, benchmark_return),
            )

    def get_performance_history(self, mode: str = "paper", days: int = 90) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM daily_performance WHERE mode=?
                ORDER BY date DESC LIMIT ?""",
                (mode, days),
            ).fetchall()
            return [dict(r) for r in reversed(rows)]

    def log_system_event(self, level: str, module: str, message: str):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO system_log (level, module, message, logged_at) VALUES (?, ?, ?, ?)",
                (level, module, message, datetime.now().isoformat()),
            )

    # ── 킬스위치 / 비상정지 상태 관리 ──────────────────────────

    def set_kill_switch(self, active: bool, reason: str = "", daily_loss_pct: float = 0.0):
        """DB에 Emergency_Stop 상태를 영구 저장"""
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE system_state
                   SET emergency_stop=?, kill_switch_reason=?, daily_loss_pct=?, updated_at=?
                   WHERE id=1""",
                (1 if active else 0, reason, daily_loss_pct, datetime.now().isoformat()),
            )
        status = "🔴 발동" if active else "🟢 해제"
        logger.info(f"[DB] Emergency_Stop={active} ({status}) | 사유: {reason}")

    def get_kill_switch(self) -> dict:
        """현재 Emergency_Stop 상태 조회"""
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM system_state WHERE id=1").fetchone()
            if row:
                d = dict(row)
                d["emergency_stop"] = bool(d["emergency_stop"])
                return d
        return {"emergency_stop": False, "kill_switch_reason": "", "daily_loss_pct": 0.0}

    def get_system_logs(self, limit: int = 200) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM system_log ORDER BY logged_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def save_backtest_result(self, run_id: str, report) -> None:
        """백테스트 결과를 DB에 저장"""
        import json
        equity_json = None
        if hasattr(report, "equity_curve") and not report.equity_curve.empty:
            ec = report.equity_curve
            equity_json = json.dumps({
                "dates": [str(d) for d in ec.index],
                "values": [float(v) for v in ec.values],
            })
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO backtest_results (
                    run_id, strategy_name, start_date, end_date,
                    initial_capital, final_capital, total_return, annual_return,
                    sharpe_ratio, sortino_ratio, max_drawdown, win_rate,
                    total_trades, winning_trades, losing_trades,
                    avg_win, avg_loss, profit_factor, benchmark_return, alpha,
                    equity_curve_json, ran_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id, report.strategy_name, report.start_date, report.end_date,
                    report.initial_capital, report.final_capital,
                    report.total_return, report.annual_return,
                    report.sharpe_ratio, report.sortino_ratio, report.max_drawdown,
                    report.win_rate, report.total_trades, report.winning_trades,
                    report.losing_trades, report.avg_win, report.avg_loss,
                    report.profit_factor, report.benchmark_return, report.alpha,
                    equity_json, datetime.now().isoformat(),
                ),
            )

    def get_latest_backtest_results(self) -> list[dict]:
        """가장 최근 백테스트 run_id의 모든 전략 결과 반환"""
        import json
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT run_id FROM backtest_results ORDER BY ran_at DESC LIMIT 1"
            ).fetchone()
            if not row:
                return []
            latest_run_id = row["run_id"]
            rows = conn.execute(
                "SELECT * FROM backtest_results WHERE run_id = ? ORDER BY id ASC",
                (latest_run_id,),
            ).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                if d.get("equity_curve_json"):
                    ec_data = json.loads(d["equity_curve_json"])
                    d["equity_dates"] = ec_data.get("dates", [])
                    d["equity_values"] = ec_data.get("values", [])
                else:
                    d["equity_dates"] = []
                    d["equity_values"] = []
                del d["equity_curve_json"]
                results.append(d)
            return results

    def get_backtest_run_ids(self, limit: int = 10) -> list[str]:
        """최근 백테스트 실행 ID 목록"""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT run_id, MAX(ran_at) as ran_at FROM backtest_results GROUP BY run_id ORDER BY ran_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [r["run_id"] for r in rows]

    # ═══════════════════════════════════════════════════════════
    # 다중 사용자 (Multi-tenant) — Users CRUD
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def user_mode(user_id: int) -> str:
        """사용자별 데이터 파티션 키. admin(id=1)은 'paper' 유지."""
        return "paper" if user_id == 1 else f"u{user_id}"

    def create_user(
        self,
        email: str,
        password_hash: str,
        name: str = "투자자",
        target_return: float = 0.15,
        risk_profile: str = "balanced",
        initial_capital: float = 100_000_000,
        is_admin: bool = False,
    ) -> dict:
        """신규 사용자 생성. 이미 존재하면 ValueError."""
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT id FROM users WHERE email=?", (email.lower().strip(),)
            ).fetchone()
            if existing:
                raise ValueError(f"이미 가입된 이메일: {email}")
            conn.execute(
                """INSERT INTO users
                   (email, password_hash, name, target_return, risk_profile,
                    initial_capital, is_admin, emergency_stop, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                (
                    email.lower().strip(), password_hash, name,
                    target_return, risk_profile, initial_capital,
                    1 if is_admin else 0, now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM users WHERE email=?", (email.lower().strip(),)
            ).fetchone()
            return dict(row)

    def get_user_by_email(self, email: str) -> dict | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email=?", (email.lower().strip(),)
            ).fetchone()
            return dict(row) if row else None

    def get_user_by_id(self, user_id: int) -> dict | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE id=?", (user_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_all_users(self) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT id, email, name, target_return, risk_profile, "
                "initial_capital, is_admin, emergency_stop, created_at "
                "FROM users ORDER BY id ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def update_user_settings(
        self,
        user_id: int,
        name: str | None = None,
        target_return: float | None = None,
        risk_profile: str | None = None,
        initial_capital: float | None = None,
        emergency_stop: bool | None = None,
    ):
        """사용자 설정 부분 업데이트"""
        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError(f"사용자 없음: {user_id}")
        new_name      = name if name is not None else user["name"]
        new_target    = target_return if target_return is not None else user["target_return"]
        new_risk      = risk_profile if risk_profile is not None else user["risk_profile"]
        new_capital   = initial_capital if initial_capital is not None else user["initial_capital"]
        new_stop      = (1 if emergency_stop else 0) if emergency_stop is not None else user["emergency_stop"]
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE users SET name=?, target_return=?, risk_profile=?,
                   initial_capital=?, emergency_stop=? WHERE id=?""",
                (new_name, new_target, new_risk, new_capital, new_stop, user_id),
            )

    def update_user_password(self, user_id: int, new_hash: str):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET password_hash=? WHERE id=?", (new_hash, user_id)
            )

    def count_users(self) -> int:
        with self._get_conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    # ── 카카오 OAuth ──────────────────────────────────────────

    def migrate_trading_features(self):
        """Daily Take Profit + Manual Override 컬럼 마이그레이션 (안전한 ALTER TABLE).
        기존 DB가 있을 때 새 컬럼이 없으면 추가한다."""
        with self._get_conn() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}

            if "daily_target_profit" not in cols:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN daily_target_profit REAL NOT NULL DEFAULT 0.03"
                )
            if "allocation_mode" not in cols:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN allocation_mode TEXT NOT NULL DEFAULT 'auto'"
                )
            if "budget_value_pct" not in cols:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN budget_value_pct REAL DEFAULT 0.35"
                )
            if "budget_trend_pct" not in cols:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN budget_trend_pct REAL DEFAULT 0.35"
                )
            if "budget_swing_pct" not in cols:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN budget_swing_pct REAL DEFAULT 0.20"
                )
            if "budget_sniper_pct" not in cols:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN budget_sniper_pct REAL DEFAULT 0.10"
                )
            # ── 에이전트별 개별 목표 수익률 컬럼 ──────────────
            if "target_profit_value" not in cols:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN target_profit_value REAL DEFAULT 0.15"
                )
            if "target_profit_trend" not in cols:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN target_profit_trend REAL DEFAULT 0.10"
                )
            if "target_profit_swing" not in cols:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN target_profit_swing REAL DEFAULT 0.05"
                )
            if "target_profit_sniper" not in cols:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN target_profit_sniper REAL DEFAULT 0.03"
                )
            # ── 스나이퍼 정액제 컬럼 ───────────────────────────
            if "sniper_fixed_budget" not in cols:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN sniper_fixed_budget REAL DEFAULT 5000000"
                )
        logger.info("[DB] migrate_trading_features 완료")

    def update_user_trading_settings(
        self,
        user_id: int,
        daily_target_profit: float | None = None,
        allocation_mode: str | None = None,
        budget_value_pct: float | None = None,
        budget_trend_pct: float | None = None,
        budget_swing_pct: float | None = None,
        budget_sniper_pct: float | None = None,
        target_profit_value: float | None = None,
        target_profit_trend: float | None = None,
        target_profit_swing: float | None = None,
        target_profit_sniper: float | None = None,
        sniper_fixed_budget: float | None = None,
    ):
        """Daily TP + Manual Override + 에이전트별 개별 목표 수익 + 스나이퍼 정액 업데이트"""
        user = self.get_user_by_id(user_id)
        if not user:
            raise ValueError(f"사용자 없음: {user_id}")
        def _v(key, new_val, default):
            return new_val if new_val is not None else user.get(key, default)
        vals = {
            "daily_target_profit":  _v("daily_target_profit",  daily_target_profit,  0.03),
            "allocation_mode":      _v("allocation_mode",       allocation_mode,      "auto"),
            "budget_value_pct":     _v("budget_value_pct",      budget_value_pct,     0.35),
            "budget_trend_pct":     _v("budget_trend_pct",      budget_trend_pct,     0.35),
            "budget_swing_pct":     _v("budget_swing_pct",      budget_swing_pct,     0.20),
            "budget_sniper_pct":    _v("budget_sniper_pct",     budget_sniper_pct,    0.10),
            "target_profit_value":  _v("target_profit_value",   target_profit_value,  0.15),
            "target_profit_trend":  _v("target_profit_trend",   target_profit_trend,  0.10),
            "target_profit_swing":  _v("target_profit_swing",   target_profit_swing,  0.05),
            "target_profit_sniper": _v("target_profit_sniper",  target_profit_sniper, 0.03),
            "sniper_fixed_budget":  _v("sniper_fixed_budget",   sniper_fixed_budget,  5_000_000),
        }
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE users SET
                    daily_target_profit=?, allocation_mode=?,
                    budget_value_pct=?, budget_trend_pct=?,
                    budget_swing_pct=?, budget_sniper_pct=?,
                    target_profit_value=?, target_profit_trend=?,
                    target_profit_swing=?, target_profit_sniper=?,
                    sniper_fixed_budget=?
                   WHERE id=?""",
                (
                    vals["daily_target_profit"], vals["allocation_mode"],
                    vals["budget_value_pct"],    vals["budget_trend_pct"],
                    vals["budget_swing_pct"],    vals["budget_sniper_pct"],
                    vals["target_profit_value"], vals["target_profit_trend"],
                    vals["target_profit_swing"], vals["target_profit_sniper"],
                    vals["sniper_fixed_budget"],
                    user_id,
                ),
            )

    def migrate_kakao_columns(self):
        """기존 DB에 카카오 컬럼이 없으면 추가 (안전한 마이그레이션).
        SQLite는 ALTER TABLE ADD COLUMN에 UNIQUE를 지원하지 않으므로
        컬럼 추가 후 별도 UNIQUE INDEX로 처리한다."""
        with self._get_conn() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
            if "kakao_id" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN kakao_id TEXT")
                conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_kakao_id ON users(kakao_id)"
                )
            if "kakao_access_token" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN kakao_access_token TEXT DEFAULT ''")
            if "kakao_notify" not in cols:
                conn.execute("ALTER TABLE users ADD COLUMN kakao_notify INTEGER NOT NULL DEFAULT 1")

    def get_user_by_kakao_id(self, kakao_id: str) -> dict | None:
        """카카오 고유 ID로 사용자 조회"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE kakao_id=?", (kakao_id,)
            ).fetchone()
            return dict(row) if row else None

    def upsert_kakao_user(
        self,
        kakao_id: str,
        email: str,
        name: str,
        access_token: str,
    ) -> dict:
        """
        카카오 로그인 시 사용자 생성 또는 업데이트.
        - kakao_id 로 먼저 조회
        - 없으면 email 로 조회 (기존 이메일 계정 연결)
        - 그것도 없으면 신규 생성 (첫 번째 = 관리자)
        항상 access_token 최신화.
        """
        now = datetime.now().isoformat()
        self.migrate_kakao_columns()

        with self._get_conn() as conn:
            # 1) kakao_id 로 찾기
            row = conn.execute(
                "SELECT * FROM users WHERE kakao_id=?", (kakao_id,)
            ).fetchone()

            if row:
                conn.execute(
                    "UPDATE users SET kakao_access_token=?, name=? WHERE kakao_id=?",
                    (access_token, name, kakao_id),
                )
                row = conn.execute(
                    "SELECT * FROM users WHERE kakao_id=?", (kakao_id,)
                ).fetchone()
                return dict(row)

            # 2) email 로 찾기 (기존 계정 연결)
            row = conn.execute(
                "SELECT * FROM users WHERE email=?", (email.lower().strip(),)
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE users SET kakao_id=?, kakao_access_token=?, name=? WHERE email=?",
                    (kakao_id, access_token, name, email.lower().strip()),
                )
                row = conn.execute(
                    "SELECT * FROM users WHERE email=?", (email.lower().strip(),)
                ).fetchone()
                return dict(row)

            # 3) 신규 생성
            is_first = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
            conn.execute(
                """INSERT INTO users
                   (email, password_hash, name, target_return, risk_profile,
                    initial_capital, is_admin, emergency_stop, created_at,
                    kakao_id, kakao_access_token, kakao_notify)
                   VALUES (?,?,?,?,?,?,?,0,?,?,?,1)""",
                (
                    email.lower().strip(), "", name,
                    0.15, "balanced", 100_000_000,
                    1 if is_first else 0, now,
                    kakao_id, access_token,
                ),
            )
            row = conn.execute(
                "SELECT * FROM users WHERE kakao_id=?", (kakao_id,)
            ).fetchone()
            return dict(row)

    def update_kakao_token(self, user_id: int, access_token: str):
        """access_token 갱신"""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET kakao_access_token=? WHERE id=?",
                (access_token, user_id),
            )

    def set_kakao_notify(self, user_id: int, enabled: bool):
        """카카오톡 알림 ON/OFF"""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE users SET kakao_notify=? WHERE id=?",
                (1 if enabled else 0, user_id),
            )

    def get_kakao_notify_users(self) -> list[dict]:
        """kakao_notify=1이고 access_token이 있는 모든 사용자 — TradingEngine 멀티유저 발송용"""
        try:
            with self._get_conn() as conn:
                rows = conn.execute(
                    "SELECT id, name, kakao_access_token FROM users "
                    "WHERE kakao_notify=1 "
                    "AND kakao_access_token IS NOT NULL "
                    "AND kakao_access_token != ''",
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            return []
