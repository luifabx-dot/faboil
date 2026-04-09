"""
Forex trend-following strategy with options hedging.

Strategia
---------
Trend-following giornaliero su coppia FX (default EUR/USD) con copertura
del rischio di coda tramite opzioni FX vanilla (modello Garman-Kohlhagen).

Regole operative
----------------
1. Indicatori su barre daily:
   - EMA veloce (20) e EMA lenta (50)
   - ADX (14) come filtro di forza del trend
   - ATR (14) per volatilita' e stop dinamici
2. Segnale di ingresso:
   - LONG  quando EMA_fast incrocia sopra EMA_slow e ADX > adx_threshold
   - SHORT quando EMA_fast incrocia sotto EMA_slow e ADX > adx_threshold
3. Copertura (hedge) all'ingresso:
   - LONG  -> acquisto di una put OTM ~2% (scadenza ~30 giorni)
   - SHORT -> acquisto di una call OTM ~2% (scadenza ~30 giorni)
   - Opzionale "collar": finanziamento parziale vendendo un'opzione
     piu' OTM (4%) sul lato opposto
4. Money management:
   - Rischio per trade = risk_pct del capitale (default 1%)
   - Size dello spot basata sulla distanza spot-stop + premio netto
5. Stop / Take profit:
   - Stop loss   = entry -/+ 2 * ATR(14)
   - Take profit = entry +/- 4 * ATR(14)
   - Uscita anche su inversione del trend (cross inverso delle EMA)

Pricing opzioni
---------------
Usa il modello di Garman-Kohlhagen (estensione Black-Scholes per FX):

    d1 = [ln(S/K) + (rd - rf + sigma^2/2) * T] / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)
    C  = S * exp(-rf*T) * N(d1) - K * exp(-rd*T) * N(d2)
    P  = K * exp(-rd*T) * N(-d2) - S * exp(-rf*T) * N(-d1)

dove S = spot, K = strike, rd = tasso domestico, rf = tasso estero,
sigma = volatilita' implicita annua, T = tempo alla scadenza in anni.

Dipendenze
----------
numpy, pandas.  I dati di prezzo possono arrivare da qualunque provider;
questo file non include il download, ma offre un backtest su DataFrame OHLC.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import erf, exp, log, sqrt
from typing import Literal

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Opzioni FX: Garman-Kohlhagen
# ---------------------------------------------------------------------------

def _norm_cdf(x: float) -> float:
    """CDF della normale standard senza scipy."""
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def gk_price(
    spot: float,
    strike: float,
    rd: float,
    rf: float,
    sigma: float,
    tau: float,
    kind: Literal["call", "put"],
) -> float:
    """Prezzo di un'opzione FX vanilla (Garman-Kohlhagen).

    rd: tasso risk-free domestico (quote currency, es. USD)
    rf: tasso risk-free estero    (base currency,  es. EUR)
    sigma: volatilita' implicita annualizzata (es. 0.08 = 8%)
    tau: tempo alla scadenza in anni (es. 30/365)
    """
    if tau <= 0 or sigma <= 0:
        intrinsic = max(0.0, spot - strike) if kind == "call" else max(0.0, strike - spot)
        return intrinsic

    sqrt_t = sqrt(tau)
    d1 = (log(spot / strike) + (rd - rf + 0.5 * sigma * sigma) * tau) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t

    if kind == "call":
        return spot * exp(-rf * tau) * _norm_cdf(d1) - strike * exp(-rd * tau) * _norm_cdf(d2)
    return strike * exp(-rd * tau) * _norm_cdf(-d2) - spot * exp(-rf * tau) * _norm_cdf(-d1)


# ---------------------------------------------------------------------------
# Indicatori tecnici
# ---------------------------------------------------------------------------

def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = pd.concat(
        [(high - low).abs(),
         (high - close.shift()).abs(),
         (low - close.shift()).abs()],
        axis=1,
    ).max(axis=1)

    atr_ = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr_
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean().fillna(0)


# ---------------------------------------------------------------------------
# Configurazione e stato
# ---------------------------------------------------------------------------

@dataclass
class StrategyConfig:
    # Segnale
    ema_fast: int = 20
    ema_slow: int = 50
    adx_period: int = 14
    adx_threshold: float = 25.0
    atr_period: int = 14
    atr_stop_mult: float = 2.0
    atr_take_mult: float = 4.0

    # Money management
    capital: float = 100_000.0
    risk_pct: float = 0.01  # 1% per trade

    # Copertura
    hedge_enabled: bool = True
    hedge_otm_pct: float = 0.02          # strike 2% OTM
    hedge_tenor_days: int = 30
    hedge_iv: float = 0.08               # vol implicita annua
    rd: float = 0.045                    # USD
    rf: float = 0.035                    # EUR
    use_collar: bool = False
    collar_short_otm_pct: float = 0.04   # gamba short del collar 4% OTM


@dataclass
class Position:
    side: Literal["long", "short"]
    entry_date: pd.Timestamp
    entry_spot: float
    units: float
    stop: float
    take: float
    hedge_strike: float = 0.0
    hedge_kind: Literal["call", "put", "none"] = "none"
    hedge_premium_paid: float = 0.0
    hedge_expiry: pd.Timestamp | None = None
    collar_strike: float = 0.0
    collar_kind: Literal["call", "put", "none"] = "none"
    collar_premium_received: float = 0.0


@dataclass
class Trade:
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    side: str
    entry_spot: float
    exit_spot: float
    units: float
    spot_pnl: float
    hedge_pnl: float
    net_pnl: float
    reason: str


# ---------------------------------------------------------------------------
# Core strategy
# ---------------------------------------------------------------------------

class ForexHedgedStrategy:
    """Strategia forex trend-following con copertura da opzioni."""

    def __init__(self, config: StrategyConfig | None = None) -> None:
        self.cfg = config or StrategyConfig()

    # ---- segnali ---------------------------------------------------------
    def build_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        c = self.cfg
        out = df.copy()
        out["ema_fast"] = ema(out["close"], c.ema_fast)
        out["ema_slow"] = ema(out["close"], c.ema_slow)
        out["adx"] = adx(out, c.adx_period)
        out["atr"] = atr(out, c.atr_period)

        cross_up = (out["ema_fast"] > out["ema_slow"]) & (
            out["ema_fast"].shift(1) <= out["ema_slow"].shift(1)
        )
        cross_dn = (out["ema_fast"] < out["ema_slow"]) & (
            out["ema_fast"].shift(1) >= out["ema_slow"].shift(1)
        )
        strong = out["adx"] > c.adx_threshold

        out["signal"] = 0
        out.loc[cross_up & strong, "signal"] = 1
        out.loc[cross_dn & strong, "signal"] = -1
        return out

    # ---- hedge sizing ----------------------------------------------------
    def _open_hedge(self, side: str, spot: float, date: pd.Timestamp) -> dict:
        c = self.cfg
        tau = c.hedge_tenor_days / 365.0

        if side == "long":
            hedge_kind: Literal["call", "put"] = "put"
            strike = spot * (1 - c.hedge_otm_pct)
            collar_kind: Literal["call", "put"] = "call"
            collar_strike = spot * (1 + c.collar_short_otm_pct)
        else:
            hedge_kind = "call"
            strike = spot * (1 + c.hedge_otm_pct)
            collar_kind = "put"
            collar_strike = spot * (1 - c.collar_short_otm_pct)

        premium = gk_price(spot, strike, c.rd, c.rf, c.hedge_iv, tau, hedge_kind)
        collar_premium = 0.0
        if c.use_collar:
            collar_premium = gk_price(
                spot, collar_strike, c.rd, c.rf, c.hedge_iv, tau, collar_kind
            )

        return {
            "hedge_kind": hedge_kind,
            "hedge_strike": strike,
            "hedge_premium": premium,
            "hedge_expiry": date + pd.Timedelta(days=c.hedge_tenor_days),
            "collar_kind": collar_kind if c.use_collar else "none",
            "collar_strike": collar_strike if c.use_collar else 0.0,
            "collar_premium": collar_premium,
        }

    def _size_position(self, spot: float, stop: float, hedge_net_cost: float) -> float:
        c = self.cfg
        risk_budget = c.capital * c.risk_pct
        unit_risk = abs(spot - stop) + max(hedge_net_cost, 0.0)
        if unit_risk <= 0:
            return 0.0
        return risk_budget / unit_risk

    # ---- exit value of the hedge ----------------------------------------
    def _hedge_exit_value(self, pos: Position, spot: float, date: pd.Timestamp) -> float:
        if not pos.hedge_kind or pos.hedge_kind == "none":
            return 0.0
        c = self.cfg
        tau = max(0.0, (pos.hedge_expiry - date).days / 365.0) if pos.hedge_expiry else 0.0
        long_leg = gk_price(spot, pos.hedge_strike, c.rd, c.rf, c.hedge_iv, tau, pos.hedge_kind)
        short_leg = 0.0
        if pos.collar_kind != "none":
            short_leg = gk_price(
                spot, pos.collar_strike, c.rd, c.rf, c.hedge_iv, tau, pos.collar_kind
            )
        return long_leg - short_leg

    # ---- backtest --------------------------------------------------------
    def backtest(self, df: pd.DataFrame) -> dict:
        """Backtest su DataFrame con colonne: open, high, low, close (indice datetime)."""
        c = self.cfg
        sig = self.build_signals(df).dropna()
        equity = c.capital
        equity_curve: list[tuple[pd.Timestamp, float]] = []
        trades: list[Trade] = []
        pos: Position | None = None

        for date, row in sig.iterrows():
            spot = float(row["close"])

            # Gestione posizione aperta
            if pos is not None:
                hit_stop = (pos.side == "long" and row["low"] <= pos.stop) or (
                    pos.side == "short" and row["high"] >= pos.stop
                )
                hit_take = (pos.side == "long" and row["high"] >= pos.take) or (
                    pos.side == "short" and row["low"] <= pos.take
                )
                reverse = (pos.side == "long" and row["signal"] == -1) or (
                    pos.side == "short" and row["signal"] == 1
                )

                if hit_stop or hit_take or reverse:
                    exit_spot = (
                        pos.stop if hit_stop else (pos.take if hit_take else spot)
                    )
                    direction = 1 if pos.side == "long" else -1
                    spot_pnl = direction * (exit_spot - pos.entry_spot) * pos.units
                    hedge_value = self._hedge_exit_value(pos, exit_spot, date)
                    net_premium = pos.hedge_premium_paid - pos.collar_premium_received
                    hedge_pnl = (hedge_value - net_premium) * pos.units
                    net_pnl = spot_pnl + hedge_pnl
                    equity += net_pnl

                    trades.append(
                        Trade(
                            entry_date=pos.entry_date,
                            exit_date=date,
                            side=pos.side,
                            entry_spot=pos.entry_spot,
                            exit_spot=exit_spot,
                            units=pos.units,
                            spot_pnl=spot_pnl,
                            hedge_pnl=hedge_pnl,
                            net_pnl=net_pnl,
                            reason="stop" if hit_stop else ("take" if hit_take else "reverse"),
                        )
                    )
                    pos = None

            # Apertura nuova posizione
            if pos is None and row["signal"] != 0:
                side = "long" if row["signal"] == 1 else "short"
                atr_v = float(row["atr"])
                if side == "long":
                    stop = spot - c.atr_stop_mult * atr_v
                    take = spot + c.atr_take_mult * atr_v
                else:
                    stop = spot + c.atr_stop_mult * atr_v
                    take = spot - c.atr_take_mult * atr_v

                hedge = (
                    self._open_hedge(side, spot, date)
                    if c.hedge_enabled
                    else {
                        "hedge_kind": "none",
                        "hedge_strike": 0.0,
                        "hedge_premium": 0.0,
                        "hedge_expiry": None,
                        "collar_kind": "none",
                        "collar_strike": 0.0,
                        "collar_premium": 0.0,
                    }
                )
                net_cost = hedge["hedge_premium"] - hedge["collar_premium"]
                units = self._size_position(spot, stop, net_cost)
                if units > 0:
                    pos = Position(
                        side=side,
                        entry_date=date,
                        entry_spot=spot,
                        units=units,
                        stop=stop,
                        take=take,
                        hedge_strike=hedge["hedge_strike"],
                        hedge_kind=hedge["hedge_kind"],
                        hedge_premium_paid=hedge["hedge_premium"],
                        hedge_expiry=hedge["hedge_expiry"],
                        collar_strike=hedge["collar_strike"],
                        collar_kind=hedge["collar_kind"],
                        collar_premium_received=hedge["collar_premium"],
                    )

            equity_curve.append((date, equity))

        curve = pd.DataFrame(equity_curve, columns=["date", "equity"]).set_index("date")
        return {
            "trades": trades,
            "equity_curve": curve,
            "final_equity": equity,
            "return_pct": (equity / c.capital - 1) * 100,
            "n_trades": len(trades),
            "win_rate": (
                sum(1 for t in trades if t.net_pnl > 0) / len(trades) * 100
                if trades
                else 0.0
            ),
        }


# ---------------------------------------------------------------------------
# Esempio d'uso con dati sintetici
# ---------------------------------------------------------------------------

def _demo() -> None:
    rng = np.random.default_rng(42)
    n = 500
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    # random walk con drift debole + cicli
    drift = 0.00015
    shocks = rng.normal(0, 0.005, n)
    cycle = 0.01 * np.sin(np.linspace(0, 12 * np.pi, n))
    log_px = np.cumsum(drift + shocks) + cycle
    close = 1.08 * np.exp(log_px)
    high = close * (1 + rng.uniform(0, 0.003, n))
    low = close * (1 - rng.uniform(0, 0.003, n))
    open_ = np.roll(close, 1)
    open_[0] = close[0]

    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close},
        index=dates,
    )

    strat = ForexHedgedStrategy(StrategyConfig(use_collar=True))
    res = strat.backtest(df)

    print(f"Trades:     {res['n_trades']}")
    print(f"Win rate:   {res['win_rate']:.1f}%")
    print(f"Final eq.:  {res['final_equity']:,.2f}")
    print(f"Return:     {res['return_pct']:.2f}%")
    if res["trades"]:
        print("\nUltimi 5 trade:")
        for t in res["trades"][-5:]:
            print(
                f"  {t.entry_date.date()} -> {t.exit_date.date()} "
                f"{t.side:5s} spot_pnl={t.spot_pnl:+.2f} "
                f"hedge_pnl={t.hedge_pnl:+.2f} net={t.net_pnl:+.2f} "
                f"({t.reason})"
            )


if __name__ == "__main__":
    _demo()
