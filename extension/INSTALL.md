# Chrome Extension — Install Guide

## Steps

1. Open Chrome and go to `chrome://extensions`
2. Enable **Developer mode** (toggle, top-right)
3. Click **Load unpacked**
4. Select this folder: `C:\Users\z_shi\Desktop\N8NPROJECTS\Analyst App\extension`
5. The extension installs immediately — no restart needed

## How to use

1. Make sure the Analyst App is running (`python app.py` in the Analyst App folder)
2. Make sure you're **logged into the Analyst App** at `http://localhost:5051` in Chrome
3. Go to `https://www.tradingview.com` — your chart loads as normal with all your indicators
4. A **TRADE** tab appears on the right edge of the screen
5. Click it — the trade panel slides in
6. Symbol auto-fills from the current chart; live price appears immediately
7. Select LONG/SHORT, fill SL/TP, click **FIRE**

## After updating the extension code

Go to `chrome://extensions`, find "Analyst Trade Panel", click the **refresh** icon (↻).

## Notes

- The panel reads the current symbol from the TradingView URL automatically
- When you navigate to a different chart on TradingView, the symbol updates
- All trading and Discord posting goes through the Analyst App backend
- The extension stores nothing locally — all credentials stay in the Analyst App
