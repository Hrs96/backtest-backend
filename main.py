from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from SmartApi import SmartConnect
import pyotp
import os
import pandas as pd
import backtrader as bt
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_angel_session():
    obj = SmartConnect(api_key=os.getenv("ANGEL_API_KEY"))

    totp = pyotp.TOTP(
        os.getenv("ANGEL_TOTP_SECRET")
    ).now()

    obj.generateSession(
        os.getenv("ANGEL_CLIENT_ID"),
        os.getenv("ANGEL_PASSWORD"),
        totp,
    )

    return obj


class EMACrossover(bt.Strategy):

    params = (
        ("fast", 9),
        ("slow", 21),
    )

    def __init__(self):
        self.ema_fast = bt.indicators.EMA(
            self.datas[0],
            period=self.p.fast,
        )

        self.ema_slow = bt.indicators.EMA(
            self.datas[0],
            period=self.p.slow,
        )

        self.crossover = bt.indicators.CrossOver(
            self.ema_fast,
            self.ema_slow,
        )

    def next(self):

        if not self.position:

            if self.crossover > 0:
                self.buy()

        elif self.crossover < 0:
            self.close()


@app.get("/")
def root():
    return {"status": "running"}


@app.get("/api/backtest")
def run_backtest(
    symbol: str,
    token: str,
    fromdate: str,
    todate: str,
    interval: str = "ONE_DAY",
    strategy: str = "ema_cross",
    capital: float = 100000,
):

    try:

        obj = get_angel_session()

        params = {
            "exchange": "NSE",
            "symboltoken": token,
            "interval": interval,
            "fromdate": fromdate,
            "todate": todate,
        }

        response = obj.getCandleData(params)

        if not response.get("data"):
            return {
                "success": False,
                "error": "No candle data returned"
            }

        data = response["data"]

        df = pd.DataFrame(data)

        df = df.iloc[:, :6]

        df.columns = [
            "datetime",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]

        df["datetime"] = pd.to_datetime(
            df["datetime"]
        )

        for col in [
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]:
            df[col] = pd.to_numeric(
                df[col],
                errors="coerce"
            )

        df.dropna(inplace=True)

        df.set_index("datetime", inplace=True)

        cerebro = bt.Cerebro()

        cerebro.broker.setcash(capital)

        cerebro.broker.setcommission(
            commission=0.0003
        )

        feed = bt.feeds.PandasData(
            dataname=df
        )

        cerebro.adddata(feed)

        if strategy == "ema_cross":
            cerebro.addstrategy(
                EMACrossover
            )
        else:
            cerebro.addstrategy(
                EMACrossover
            )

        cerebro.addanalyzer(
            bt.analyzers.TradeAnalyzer,
            _name="trades"
        )

        cerebro.addanalyzer(
            bt.analyzers.DrawDown,
            _name="drawdown"
        )

        results = cerebro.run()

        strat = results[0]

        trade_analysis = (
            strat.analyzers.trades
            .get_analysis()
        )

        drawdown_analysis = (
            strat.analyzers.drawdown
            .get_analysis()
        )

        final_value = (
            cerebro.broker.getvalue()
        )

        total_trades = (
            trade_analysis.get(
                "total", {}
            ).get(
                "total", 0
            )
        )

        winning_trades = (
            trade_analysis.get(
                "won", {}
            ).get(
                "total", 0
            )
        )

        losing_trades = (
            trade_analysis.get(
                "lost", {}
            ).get(
                "total", 0
            )
        )

        win_rate = (
            round(
                (winning_trades /
                 total_trades) * 100,
                2,
            )
            if total_trades > 0
            else 0
        )

        return {
            "success": True,
            "symbol": symbol,
            "initial_capital": capital,
            "final_value": round(
                final_value,
                2
            ),
            "net_pnl": round(
                final_value - capital,
                2
            ),
            "returns_pct": round(
                (
                    (final_value - capital)
                    / capital
                )
                * 100,
                2,
            ),
            "max_drawdown_pct": round(
                drawdown_analysis.max.drawdown,
                2,
            ),
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate_pct": win_rate,

            # frontend compatibility
            "best_trade": 0,
            "worst_trade": 0,
            "equity_curve": [],
            "trades": [],
        }

    except Exception as e:

        return {
            "success": False,
            "error": str(e)
        }
