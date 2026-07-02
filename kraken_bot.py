from pandas import DataFrame
import talib.abstract as ta
from freqtrade.strategy import IStrategy, DecimalParameter, IntParameter
from technical import qtpylib

class TrendStrategy(IStrategy):
    """
    Trend following strategy using EMA crossover + RSI filter.
    Only trades when market is in a clear uptrend.
    Sits in cash during downtrends.
    """
    INTERFACE_VERSION = 3
    timeframe = "1h"
    can_short = False

    # Take profit tiers
    minimal_roi = {
        "0": 0.08,
        "120": 0.04,
        "240": 0.02,
        "480": 0.01
    }

    stoploss = -0.08
    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.04
    trailing_only_offset_is_reached = True

    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    startup_candle_count = 50

    # Hyperoptable parameters
    buy_ema_short = IntParameter(5, 20, default=9, space="buy")
    buy_ema_long = IntParameter(21, 100, default=50, space="buy")
    buy_rsi_min = IntParameter(30, 60, default=50, space="buy")

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False
    }

    order_time_in_force = {
        "entry": "GTC",
        "exit": "GTC"
    }

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # EMAs
        for val in self.buy_ema_short.range:
            dataframe[f"ema_{val}"] = ta.EMA(dataframe, timeperiod=val)
        for val in self.buy_ema_long.range:
            dataframe[f"ema_{val}"] = ta.EMA(dataframe, timeperiod=val)

        # RSI
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)

        # Volume check
        dataframe["volume_mean"] = dataframe["volume"].rolling(20).mean()

        # MACD for trend confirmation
        macd = ta.MACD(dataframe)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # Short EMA above long EMA = uptrend
                (dataframe[f"ema_{self.buy_ema_short.value}"] > dataframe[f"ema_{self.buy_ema_long.value}"]) &
                # EMA crossover happening now
                (qtpylib.crossed_above(dataframe[f"ema_{self.buy_ema_short.value}"], dataframe[f"ema_{self.buy_ema_long.value}"])) &
                # RSI showing momentum but not overbought
                (dataframe["rsi"] > self.buy_rsi_min.value) &
                (dataframe["rsi"] < 75) &
                # MACD positive
                (dataframe["macd"] > dataframe["macdsignal"]) &
                # Volume above average
                (dataframe["volume"] > dataframe["volume_mean"]) &
                (dataframe["volume"] > 0)
            ),
            "enter_long"
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                # Short EMA crosses below long EMA = downtrend starting
                (qtpylib.crossed_below(dataframe[f"ema_{self.buy_ema_short.value}"], dataframe[f"ema_{self.buy_ema_long.value}"])) &
                (dataframe["volume"] > 0)
            ),
            "exit_long"
        ] = 1
        return dataframe
