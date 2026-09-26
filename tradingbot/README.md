# TradingBot — บอทเทรดอัตโนมัติที่ใช้ TradingAgents ตัดสินใจ

`tradingagents` วิเคราะห์หุ้นด้วยทีมเอเจนต์ LLM (นักวิเคราะห์ 4 ฝ่าย → ดีเบต Bull/Bear → Trader → ทีมบริหารความเสี่ยง → Portfolio Manager)
แล้วให้คะแนน 5 ระดับ: **Buy / Overweight / Hold / Underweight / Sell** แต่ตัวมันเองไม่ส่งคำสั่งซื้อขาย

`tradingbot` คืออีกครึ่งหนึ่ง ในแต่ละรอบบอทจะ:

1. อ่านเงินสดและพอร์ตปัจจุบันจากโบรกเกอร์
2. ส่งพอร์ตนั้นให้เอเจนต์วิเคราะห์หุ้นแต่ละตัวใน watchlist (เอเจนต์รู้ว่าเราถืออะไรอยู่)
3. แปลงเรตติ้งเป็นขนาดออเดอร์ภายใต้ขีดจำกัดความเสี่ยงที่ตั้งไว้
4. ส่งคำสั่ง (หรือแค่จำลองถ้าใช้ `--dry-run`) แล้วบันทึกทุกอย่างลง journal

> ⚠️ นี่คือเครื่องมือวิจัย ผลของ LLM ไม่แน่นอนและอาจผิดพลาดได้ **ค่าเริ่มต้นคือ paper trading (เงินจำลอง)**
> ทดลองด้วยเงินจำลองนาน ๆ และดูผล backtest ก่อนเสมอ ไม่ใช่คำแนะนำการลงทุน

## ติดตั้ง

```bash
pip install .
cp .env.example .env    # ใส่ API key ของ LLM ที่ใช้ เช่น OPENAI_API_KEY หรือ ANTHROPIC_API_KEY
tradingbot init bot.json
```

แก้ `bot.json` ให้ตรงกับที่ต้องการ แล้วลองรันแบบไม่ส่งออเดอร์ก่อน:

```bash
tradingbot run -c bot.json --dry-run   # วิเคราะห์ + คำนวณขนาด แต่ไม่ซื้อขาย
tradingbot run -c bot.json             # เทรดจริงในบัญชี paper
tradingbot status -c bot.json          # ดูเงินสด / พอร์ต / กำไรขาดทุน
tradingbot history -c bot.json         # ดูประวัติการตัดสินใจและออเดอร์
tradingbot loop -c bot.json --at 16:30 # รันอัตโนมัติทุกวันทำการเวลา 16:30 (คริปโตใช้ --every-day)
```

จะใช้ cron แทน `loop` ก็ได้ เช่น `30 16 * * 1-5 cd /path && tradingbot run -c bot.json`
บอทจะไม่ตัดสินใจหุ้นตัวเดิมซ้ำในวันเดียวกัน (กันออเดอร์ซ้ำเวลา cron ยิงสองครั้ง) ยกเว้นใส่ `--force`

## เรตติ้งถูกแปลงเป็นออเดอร์อย่างไร

ขนาดเป้าหมาย = equity × `max_position_pct` × น้ำหนักของเรตติ้ง (`rating_weights`)

| เรตติ้ง | น้ำหนักเริ่มต้น | พฤติกรรม |
|---|---|---|
| Buy | 1.0 | ซื้อเพิ่มจนถึงเพดานเต็ม (เช่น 10% ของพอร์ต) |
| Overweight | 0.6 | ซื้อเพิ่มจนถึง 60% ของเพดาน |
| Hold | – | ไม่ทำอะไร |
| Underweight | 0.3 | ขายลดจนเหลือ 30% ของเพดาน |
| Sell | 0.0 | ขายออกทั้งหมด |
| REVIEW | – | เอเจนต์ไม่ได้ให้เรตติ้งที่อ่านได้ ไม่เทรด ต้องให้คนดู |

กฎความปลอดภัย:

- เรตติ้งฝั่งบวก **ซื้ออย่างเดียว** ไม่ขาย และเรตติ้งฝั่งลบ **ขายอย่างเดียว** ไม่เปิดสถานะใหม่
- Long-only: ไม่มีการ short
- เก็บเงินสดขั้นต่ำ `min_cash_pct` ไว้เสมอ, ข้ามออเดอร์ที่เล็กกว่า `min_order_value`, จำกัดจำนวนออเดอร์ต่อรอบด้วย `max_orders_per_run`
- ปัดจำนวนหุ้นลงตาม `lot_sizes` (หุ้นไทยซื้อขายทีละ 100 หุ้น: `{"PTT.BK": 100}`) หรือเปิด `fractional` สำหรับคริปโต
- หุ้นตัวหนึ่ง error ไม่ทำให้ตัวอื่นหยุด

## ตั้งค่า (`bot.json`)

| คีย์ | ความหมาย |
|---|---|
| `watchlist` | ticker แบบ Yahoo Finance เช่น `NVDA`, `PTT.BK`, `BTC-USD` |
| `broker` | `paper` (จำลอง, ค่าเริ่มต้น) หรือ `alpaca` |
| `live` | `true` = ใช้เงินจริง (ต้องใส่ `--live` ตอนรันด้วย) |
| `analysts` | นักวิเคราะห์ที่ใช้: `market`, `social`, `news`, `fundamentals` (ลดเพื่อประหยัดค่า LLM) |
| `currency`, `starting_cash`, `commission_pct` | สกุลเงิน, เงินตั้งต้น และค่าคอมมิชชันของบัญชี paper |
| `tradingagents` | ค่าที่ส่งต่อให้ TradingAgents เช่น `llm_provider`, `deep_think_llm`, `quick_think_llm`, `max_debate_rounds`, `output_language` |
| `state_dir` | ที่เก็บบัญชี paper และ journal (ค่าเริ่มต้น `~/.tradingagents/bot`) |

**หนึ่งบัญชีคือหนึ่งสกุลเงิน**: บัญชี paper ถือว่าราคาทุกตัวเป็นสกุลเดียวกับบัญชี
ถ้าจะเทรดหุ้นไทย ให้ตั้ง `"currency": "THB"` และใส่แต่หุ้น `.BK` ในไฟล์นั้น แยกไฟล์ config และ `state_dir` สำหรับหุ้นสหรัฐฯ

ตัวอย่างหุ้นไทย ใช้ Claude:

```json
{
  "watchlist": ["PTT.BK", "CPALL.BK", "AOT.BK"],
  "currency": "THB",
  "starting_cash": 1000000,
  "lot_sizes": {"PTT.BK": 100, "CPALL.BK": 100, "AOT.BK": 100},
  "state_dir": "~/.tradingagents/bot-th",
  "tradingagents": {"llm_provider": "anthropic", "output_language": "Thai"}
}
```

## ใช้บัญชีจริง (Alpaca: หุ้นสหรัฐฯ และคริปโต)

1. สมัคร [Alpaca](https://alpaca.markets) แล้วเอา API key ของบัญชี **paper** มาก่อน
2. ใส่ใน `.env`: `ALPACA_API_KEY_ID=...` และ `ALPACA_API_SECRET_KEY=...`
3. ตั้ง `"broker": "alpaca"` แล้วรันตามปกติ ออเดอร์จะไปที่ paper-api ของ Alpaca
4. เมื่อมั่นใจแล้วเท่านั้น: เปลี่ยนเป็น key บัญชีจริง, ตั้ง `"live": true` และรันด้วย `--live`
   (ถ้าขาดอย่างใดอย่างหนึ่ง บอทจะปฏิเสธไม่ยอมรัน)

ราคาที่ใช้คำนวณขนาดมาจากราคาปิดล่าสุดของ Yahoo Finance ส่วนออเดอร์เป็น market order จึงอาจเข้าที่ราคาต่างไปเล็กน้อย

## เพิ่มโบรกเกอร์อื่น

สืบทอด `tradingbot.brokers.base.Broker` แล้วเขียน 4 เมธอด: `account()`, `holdings()`, `price()`, `submit()`
จากนั้นเพิ่มใน `make_broker` (`tradingbot/brokers/__init__.py`) เช่น Binance, Interactive Brokers หรือโบรกไทยที่มี API (Settrade Open API)

## ก่อนใช้เงินจริง

ใช้ backtest ของ TradingAgents ดูว่าเรตติ้งในอดีตทำกำไรเทียบ benchmark ได้จริงหรือไม่:

```bash
tradingagents backtest NVDA,AAPL --start 2026-06-01 --end 2026-08-01 --every 7
```
