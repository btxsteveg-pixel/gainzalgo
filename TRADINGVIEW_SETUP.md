# TradingView Setup

Paste one of these blocks near the bottom of your Pine script after your `buy_condition` and `sell_condition`.

Replace `CHANGE_ME` with the same secret you put in `.env`.

## Lotto

```pine
tv_secret = "CHANGE_ME"
trade_style = "LOTTO"

if buy_condition
    alert('{"secret":"' + tv_secret + '","trade_style":"' + trade_style + '","symbol":"' + syminfo.ticker + '","timeframe":"' + timeframe.period + '","side":"BUY","price":' + str.tostring(close) + ',"confidence":' + str.tostring(system_confidence) + ',"take_profit":' + str.tostring(high + tp_points) + ',"stop_loss":' + str.tostring(low - sl_points) + ',"signal_id":"' + syminfo.ticker + '-LOTTO-' + timeframe.period + '-' + str.tostring(time) + '","message":"GainzAlgo LOTTO BUY"}', alert.freq_once_per_bar_close)

if sell_condition
    alert('{"secret":"' + tv_secret + '","trade_style":"' + trade_style + '","symbol":"' + syminfo.ticker + '","timeframe":"' + timeframe.period + '","side":"SELL","price":' + str.tostring(close) + ',"confidence":' + str.tostring(system_confidence) + ',"take_profit":' + str.tostring(low - tp_points) + ',"stop_loss":' + str.tostring(high + sl_points) + ',"signal_id":"' + syminfo.ticker + '-LOTTO-' + timeframe.period + '-' + str.tostring(time) + '","message":"GainzAlgo LOTTO SELL"}', alert.freq_once_per_bar_close)
```

## Swing

```pine
tv_secret = "CHANGE_ME"
trade_style = "SWING"

if buy_condition
    alert('{"secret":"' + tv_secret + '","trade_style":"' + trade_style + '","symbol":"' + syminfo.ticker + '","timeframe":"' + timeframe.period + '","side":"BUY","price":' + str.tostring(close) + ',"confidence":' + str.tostring(system_confidence) + ',"take_profit":' + str.tostring(high + tp_points) + ',"stop_loss":' + str.tostring(low - sl_points) + ',"signal_id":"' + syminfo.ticker + '-SWING-' + timeframe.period + '-' + str.tostring(time) + '","message":"GainzAlgo SWING BUY"}', alert.freq_once_per_bar_close)

if sell_condition
    alert('{"secret":"' + tv_secret + '","trade_style":"' + trade_style + '","symbol":"' + syminfo.ticker + '","timeframe":"' + timeframe.period + '","side":"SELL","price":' + str.tostring(close) + ',"confidence":' + str.tostring(system_confidence) + ',"take_profit":' + str.tostring(low - tp_points) + ',"stop_loss":' + str.tostring(high + sl_points) + ',"signal_id":"' + syminfo.ticker + '-SWING-' + timeframe.period + '-' + str.tostring(time) + '","message":"GainzAlgo SWING SELL"}', alert.freq_once_per_bar_close)
```

## TradingView Alert

- Condition: your indicator
- Trigger: `Any alert() function call`
- Webhook URL:

```text
http://YOUR_SERVER_IP:8787/webhook/tradingview
```
