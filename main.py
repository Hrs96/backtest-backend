from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from SmartApi import SmartConnect
import pyotp, os, pandas as pd, backtrader as bt
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()

app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

def get_angel_session():
    obj = SmartConnect(api_key=os.getenv("ANGEL_API_KEY"))
    totp = pyotp.TOTP(os.getenv("ANGEL_TOTP_SECRET")).now()
    obj.generateSession(os.getenv("ANGEL_CLIENT_ID"),
                        os.getenv("ANGEL_PASSWORD"), totp)
    return obj

@app.get("/api/backtest")
def run_backtest(symbol: str, token: str, fromdate: str,
                 todate: str, interval: str = "ONE_DAY",
                 strategy: str = "ema_crossover"):

    obj = get_angel_session()
    params = {"exchange":"NSE","symboltoken":token,
              "interval":interval,"fromdate":fromdate,
              "todate":todate}
    data = obj.getCandleData(params)["data"]
    df = pd.DataFrame(data, columns=["datetime","open","high","low","close","volume"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    df.set_index("datetime", inplace=True)

    # Run backtrader
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.0003)  # 0.03% brokerage

    feed = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(feed)

    if strategy == "ema_crossover":
        cerebro.addstrategy(EMACrossover)

    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")

    results = cerebro.run()
    strat = results[0]

    final_val = cerebro.broker.getvalue()
    trade_analysis = strat.analyzers.trades.get_analysis()
    dd = strat.analyzers.drawdown.get_analysis()

    return {
        "initial_capital": 100000,
        "final_value": round(final_val, 2),
        "net_pnl": round(final_val - 100000, 2),
        "returns_pct": round((final_val - 100000) / 100000 * 100, 2),
        "max_drawdown_pct": round(dd.max.drawdown, 2),
        "total_trades": trade_analysis.get("total", {}).get("total", 0),
        "winning_trades": trade_analysis.get("won", {}).get("total", 0),
        "losing_trades": trade_analysis.get("lost", {}).get("total", 0),
    }

class EMACrossover(bt.Strategy):
    params = (("fast", 9), ("slow", 21),)
    def __init__(self):
        self.ema_fast = bt.indicators.EMA(period=self.p.fast)
        self.ema_slow = bt.indicators.EMA(period=self.p.slow)
        self.crossover = bt.indicators.CrossOver(self.ema_fast, self.ema_slow)
    def next(self):
        if not self.position:
            if self.crossover > 0:
                self.buy()
        elif self.crossover < 0:
            self.sell()