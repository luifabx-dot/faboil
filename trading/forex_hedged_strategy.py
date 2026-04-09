"""
Forex cheap-options strategy on price levels (long gamma).

Filosofia
---------
Non si usano indicatori tecnici per decidere l'ingresso. Si opera SOLO
comprando opzioni FX vanilla (call o put) a buon mercato quando il
prezzo spot raggiunge un livello strutturale individuato sulla sola
price action.

Regole operative
----------------
1. Individuazione dei livelli (pura price action):
   - Swing pivot strutturali in stile fractal: una barra e' un pivot-high
     se il suo high e' strettamente maggiore degli high delle N barre
     a sinistra e delle N barre a destra. Simmetrico per il pivot-low.
   - Nessun indicatore (no EMA, ADX, RSI, MACD, bollinger...).
   - I livelli restano "attivi" fino a quando non vengono usati per un
     trade o non sono spazzati via (close oltre il livello di X%).

2. Trigger di ingresso:
   - Quando lo spot e' entro `proximity_pct` da un pivot-high attivo
     -> candidato LONG CALL (bet: il livello viene rotto al rialzo).
   - Quando lo spot e' entro `proximity_pct` da un pivot-low attivo
     -> candidato LONG PUT  (bet: il livello viene rotto al ribasso).
   - Strike dell'opzione: oltre il livello di `otm_pct` nella direzione
     del breakout atteso (es. call con strike = pivot_high * (1 + 0.3%)).

3. Filtro "cheap":
   - (a) Premio stimato via Garman-Kohlhagen <= `cheap_premium_pct` * spot
         (es. <= 0.4% dello spot).
   - (b) Realized volatility corrente <= `cheap_vol_ratio` * media
         mobile della realized vol (il mercato "paga poco" la vol).
   - Se entrambi i filtri sono soddisfatti, si apre la posizione.

4. Money management:
   - Perdita massima nota a priori = premio pagato (rischio di un long
     premium puro, niente short options).
   - Budget di premio per trade = `risk_pct` dell'equity (default 0.5%).
   - Numero di contratti (unita' di nozionale) = budget / premio.

5. Exit:
   - Take profit: prezzo teorico dell'opzione >= entry_premium * `tp_mult`
     (default 2.5x).
   - Stop tempo:  chiudi se mancano <= `min_days_to_expiry` giorni.
   - Invalidazione: se lo spot chiude DAL LATO OPPOSTO del livello di
     almeno `invalidation_pct`, chiudi (falsa rottura confermata).
   - Naturale: alla scadenza il payoff intrinseco viene incassato.

Pricing opzioni FX
------------------
Modello Garman-Kohlhagen:

    d1 = [ln(S/K) + (rd - rf + sigma^2/2) * T] / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)
    C  = S * exp(-rf*T) * N(d1) - K * exp(-rd*T) * N(d2)
    P  = K * exp(-rd*T) * N(-d2) - S * exp(-rf*T) * N(-d1)

Note
----
- La realized volatility viene usata SOLO per stimare il fair value
  dell'opzione (input sigma del modello) e per definire il filtro di
  cheapness. NON e' un indicatore di timing.
- In produzione rimpiazzare la realized vol con la IV di mercato
  ottenuta dalla vol surface del broker.

Dipendenze: numpy, pandas.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    sigma: volatilita' annualizzata
    tau: tempo alla scadenza in anni
    """
    if tau <= 0 or sigma <= 0:
        return max(0.0, spot - strike) if kind == "call" else max(0.0, strike - spot)

    sqrt_t = sqrt(tau)
    d1 = (log(spot / strike) + (rd - rf + 0.5 * sigma * sigma) * tau) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t

    if kind == "call":
        return spot * exp(-rf * tau) * _norm_cdf(d1) - strike * exp(-rd * tau) * _norm_cdf(d2)
    return strike * exp(-rd * tau) * _norm_cdf(-d2) - spot * exp(-rf * tau) * _norm_cdf(-d1)


# ---------------------------------------------------------------------------
# Livelli strutturali (pura price action)
# ---------------------------------------------------------------------------

def find_swing_pivots(
    df: pd.DataFrame, left: int = 5, right: int = 5
) -> list[tuple[pd.Timestamp, float, str]]:
    """Ritorna tutti i pivot fractal confermati.

    Un pivot-high alla barra i richiede:
        high[i] > max(high[i-left : i]) AND high[i] > max(high[i+1 : i+right+1])
    Simmetrico per il pivot-low.

    I pivot sono noti solo dopo `right` barre (look-ahead gestito dal backtest).
    """
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    idx = df.index
    n = len(df)
    out: list[tuple[pd.Timestamp, float, str]] = []

    for i in range(left, n - right):
        window_h = highs[i - left : i + right + 1]
        window_l = lows[i - left : i + right + 1]
        if highs[i] == window_h.max() and (window_h == highs[i]).sum() == 1:
            out.append((idx[i], float(highs[i]), "high"))
        if lows[i] == window_l.min() and (window_l == lows[i]).sum() == 1:
            out.append((idx[i], float(lows[i]), "low"))
    return out


# ---------------------------------------------------------------------------
# Configurazione
# ---------------------------------------------------------------------------

@dataclass
class StrategyConfig:
    # Livelli
    pivot_left: int = 5
    pivot_right: int = 5
    proximity_pct: float = 0.0015        # 0.15% di distanza dallo spot per armare il trigger
    invalidation_pct: float = 0.004      # 0.4% di chiusura dal lato sbagliato annulla il trade
    max_active_levels: int = 20          # livelli massimi tenuti in memoria

    # Opzioni
    otm_pct: float = 0.003               # strike 0.3% oltre il livello
    tenor_days: int = 14                 # scadenza breve: molta gamma
    rd: float = 0.045                    # USD
    rf: float = 0.035                    # EUR
    rv_window: int = 20                  # finestra realized vol
    rv_sma_window: int = 60              # media mobile della realized vol

    # Cheapness
    cheap_premium_pct: float = 0.004     # premio <= 0.4% dello spot
    cheap_vol_ratio: float = 0.95        # rv corrente <= 95% della sua media

    # Money management
    capital: float = 100_000.0
    risk_pct: float = 0.005              # 0.5% di equity come premio massimo per trade
    max_concurrent: int = 3              # posizioni contemporaneamente aperte

    # Exit
    tp_mult: float = 2.5                 # take profit: prezzo teorico >= entry * tp_mult
    min_days_to_expiry: int = 3          # chiusura forzata se mancano <= N giorni


# ---------------------------------------------------------------------------
# Stato posizioni
# ---------------------------------------------------------------------------

@dataclass
class OptionPosition:
    entry_date: pd.Timestamp
    expiry: pd.Timestamp
    level: float
    level_kind: Literal["high", "low"]
    kind: Literal["call", "put"]
    strike: float
    entry_spot: float
    entry_premium: float
    units: float                         # contratti / nozionali
    sigma_at_entry: float


@dataclass
class Trade:
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    kind: str
    level: float
    strike: float
    entry_spot: float
    exit_spot: float
    entry_premium: float
    exit_premium: float
    units: float
    pnl: float
    reason: str


# ---------------------------------------------------------------------------
# Strategia
# ---------------------------------------------------------------------------

class CheapOptionsLevelsStrategy:
    """Long-gamma su livelli strutturali con filtro di cheapness."""

    def __init__(self, config: StrategyConfig | None = None) -> None:
        self.cfg = config or StrategyConfig()

    # ---- utility ---------------------------------------------------------
    def _realized_vol(self, close: pd.Series) -> tuple[pd.Series, pd.Series]:
        log_ret = np.log(close / close.shift(1))
        rv = log_ret.rolling(self.cfg.rv_window).std() * sqrt(252)
        rv_sma = rv.rolling(self.cfg.rv_sma_window).mean()
        return rv, rv_sma

    def _price_option(
        self, spot: float, strike: float, sigma: float, days: int, kind: str
    ) -> float:
        c = self.cfg
        return gk_price(spot, strike, c.rd, c.rf, sigma, days / 365.0, kind)  # type: ignore[arg-type]

    # ---- backtest --------------------------------------------------------
    def backtest(self, df: pd.DataFrame) -> dict:
        """Backtest su OHLC daily. Atteso DataFrame con open/high/low/close."""
        c = self.cfg
        required = {"open", "high", "low", "close"}
        if not required.issubset(df.columns):
            raise ValueError(f"df must have columns {required}")

        rv, rv_sma = self._realized_vol(df["close"])

        # Pre-calcola pivot (saranno "visti" dal backtest solo dopo right barre)
        all_pivots = find_swing_pivots(df, c.pivot_left, c.pivot_right)
        pivots_by_idx: dict[int, list[tuple[float, str]]] = {}
        idx_pos = {ts: i for i, ts in enumerate(df.index)}
        for ts, level, kind in all_pivots:
            # Disponibile dopo `right` barre
            confirmation_i = idx_pos[ts] + c.pivot_right
            if confirmation_i < len(df):
                pivots_by_idx.setdefault(confirmation_i, []).append((level, kind))

        equity = c.capital
        equity_curve: list[tuple[pd.Timestamp, float]] = []
        trades: list[Trade] = []
        open_positions: list[OptionPosition] = []
        active_levels: list[tuple[float, str]] = []   # (level, "high"|"low")

        for i, (date, row) in enumerate(df.iterrows()):
            spot = float(row["close"])
            high = float(row["high"])
            low = float(row["low"])
            sigma = float(rv.iloc[i]) if not np.isnan(rv.iloc[i]) else np.nan
            sigma_avg = float(rv_sma.iloc[i]) if not np.isnan(rv_sma.iloc[i]) else np.nan

            # --- 1. Aggiungi pivot confermati in questa barra ---------------
            for level, kind in pivots_by_idx.get(i, []):
                active_levels.append((level, kind))
            if len(active_levels) > c.max_active_levels:
                active_levels = active_levels[-c.max_active_levels :]

            # --- 2. Gestione posizioni aperte -------------------------------
            still_open: list[OptionPosition] = []
            for pos in open_positions:
                days_left = max(0, (pos.expiry - date).days)
                current_sigma = sigma if not np.isnan(sigma) else pos.sigma_at_entry
                theo = self._price_option(spot, pos.strike, current_sigma, days_left, pos.kind)

                # invalidazione: prezzo tornato nettamente dall'altro lato del livello
                invalidated = False
                if pos.level_kind == "high" and spot < pos.level * (1 - c.invalidation_pct):
                    invalidated = True
                if pos.level_kind == "low" and spot > pos.level * (1 + c.invalidation_pct):
                    invalidated = True

                tp_hit = theo >= pos.entry_premium * c.tp_mult
                time_stop = days_left <= c.min_days_to_expiry
                expired = days_left == 0

                if tp_hit or time_stop or invalidated or expired:
                    exit_premium = (
                        max(0.0, spot - pos.strike)
                        if pos.kind == "call"
                        else max(0.0, pos.strike - spot)
                    ) if expired else theo
                    pnl = (exit_premium - pos.entry_premium) * pos.units
                    equity += pnl
                    reason = (
                        "take_profit" if tp_hit else
                        "invalidation" if invalidated else
                        "expired" if expired else
                        "time_stop"
                    )
                    trades.append(
                        Trade(
                            entry_date=pos.entry_date,
                            exit_date=date,
                            kind=pos.kind,
                            level=pos.level,
                            strike=pos.strike,
                            entry_spot=pos.entry_spot,
                            exit_spot=spot,
                            entry_premium=pos.entry_premium,
                            exit_premium=exit_premium,
                            units=pos.units,
                            pnl=pnl,
                            reason=reason,
                        )
                    )
                else:
                    still_open.append(pos)
            open_positions = still_open

            # --- 3. Apertura nuove posizioni --------------------------------
            if (
                not np.isnan(sigma)
                and not np.isnan(sigma_avg)
                and sigma <= sigma_avg * c.cheap_vol_ratio
                and len(open_positions) < c.max_concurrent
            ):
                remaining_levels: list[tuple[float, str]] = []
                for level, kind in active_levels:
                    triggered = False
                    # Usa high/low della barra: il livello e' stato toccato?
                    if kind == "high" and abs(high - level) / level <= c.proximity_pct and high <= level * (1 + c.invalidation_pct):
                        direction: Literal["call", "put"] = "call"
                        strike = level * (1 + c.otm_pct)
                        triggered = True
                    elif kind == "low" and abs(low - level) / level <= c.proximity_pct and low >= level * (1 - c.invalidation_pct):
                        direction = "put"
                        strike = level * (1 - c.otm_pct)
                        triggered = True

                    if not triggered:
                        remaining_levels.append((level, kind))
                        continue

                    premium = self._price_option(spot, strike, sigma, c.tenor_days, direction)
                    cheap = premium <= spot * c.cheap_premium_pct and premium > 0

                    if cheap and len(open_positions) < c.max_concurrent:
                        budget = equity * c.risk_pct
                        units = budget / premium if premium > 0 else 0.0
                        if units > 0:
                            open_positions.append(
                                OptionPosition(
                                    entry_date=date,
                                    expiry=date + pd.Timedelta(days=c.tenor_days),
                                    level=level,
                                    level_kind=kind,  # type: ignore[arg-type]
                                    kind=direction,
                                    strike=strike,
                                    entry_spot=spot,
                                    entry_premium=premium,
                                    units=units,
                                    sigma_at_entry=sigma,
                                )
                            )
                        # livello consumato: non rientra in remaining_levels
                    else:
                        # livello ancora valido se non era cheap
                        remaining_levels.append((level, kind))
                active_levels = remaining_levels

            equity_curve.append((date, equity))

        curve = pd.DataFrame(equity_curve, columns=["date", "equity"]).set_index("date")
        wins = [t for t in trades if t.pnl > 0]
        return {
            "trades": trades,
            "equity_curve": curve,
            "final_equity": equity,
            "return_pct": (equity / c.capital - 1) * 100,
            "n_trades": len(trades),
            "win_rate": len(wins) / len(trades) * 100 if trades else 0.0,
            "avg_win": float(np.mean([t.pnl for t in wins])) if wins else 0.0,
            "avg_loss": float(np.mean([t.pnl for t in trades if t.pnl <= 0])) if any(t.pnl <= 0 for t in trades) else 0.0,
            "gross_profit": sum(t.pnl for t in trades if t.pnl > 0),
            "gross_loss": sum(t.pnl for t in trades if t.pnl < 0),
        }


# ---------------------------------------------------------------------------
# Demo con dati sintetici
# ---------------------------------------------------------------------------

def _demo() -> None:
    rng = np.random.default_rng(7)
    n = 750
    dates = pd.date_range("2022-01-01", periods=n, freq="B")

    # random walk con regimi di volatilita' alternati e qualche "break" brusco
    base_vol = 0.005
    vol_regime = np.where((np.arange(n) // 80) % 2 == 0, base_vol, base_vol * 1.8)
    shocks = rng.normal(0, vol_regime)
    # iniezione di 5 break bruschi
    for k in rng.integers(100, n - 10, 5):
        shocks[k] += rng.choice([-1, 1]) * 0.012
    log_px = np.cumsum(0.00005 + shocks)
    close = 1.10 * np.exp(log_px)
    noise_h = rng.uniform(0, 0.0025, n)
    noise_l = rng.uniform(0, 0.0025, n)
    high = close * (1 + noise_h)
    low = close * (1 - noise_l)
    open_ = np.concatenate([[close[0]], close[:-1]])

    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close},
        index=dates,
    )

    strat = CheapOptionsLevelsStrategy()
    res = strat.backtest(df)

    print(f"Trades:       {res['n_trades']}")
    print(f"Win rate:     {res['win_rate']:.1f}%")
    print(f"Avg win:      {res['avg_win']:+,.2f}")
    print(f"Avg loss:     {res['avg_loss']:+,.2f}")
    print(f"Gross profit: {res['gross_profit']:+,.2f}")
    print(f"Gross loss:   {res['gross_loss']:+,.2f}")
    print(f"Final equity: {res['final_equity']:,.2f}")
    print(f"Return:       {res['return_pct']:+.2f}%")
    if res["trades"]:
        print("\nUltimi 5 trade:")
        for t in res["trades"][-5:]:
            print(
                f"  {t.entry_date.date()} -> {t.exit_date.date()} "
                f"{t.kind:4s} K={t.strike:.5f} "
                f"prem {t.entry_premium:.5f}->{t.exit_premium:.5f} "
                f"pnl={t.pnl:+.2f} ({t.reason})"
            )


if __name__ == "__main__":
    _demo()
