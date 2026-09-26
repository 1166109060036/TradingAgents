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

## ติดตั้งบน Windows แบบง่าย (แนะนำ)

1. ดาวน์โหลดโค้ด: เปิดหน้า repo บน GitHub เลือก branch ที่มีบอท แล้วกด **Code → Download ZIP** จากนั้นแตกไฟล์ไว้ เช่น `C:\TradingBot`
2. เปิด **MetaTrader 5 ของ Exness** แล้วล็อกอินบัญชี **Demo**
   ใน MT5 ไปที่ *Tools → Options → Expert Advisors* แล้วติ๊ก **Allow algorithmic trading**
3. เข้าโฟลเดอร์ `scripts\windows` แล้วดับเบิลคลิก **`install.bat`**
   - ถ้ายังไม่มี Python สคริปต์จะติดตั้งให้ แล้วบอกให้ดับเบิลคลิก `install.bat` อีกรอบ
   - จะมีคำถามให้ตอบ: ประเภทบัญชี Exness, เหรียญที่จะเทรด, ผู้ให้บริการ AI, API key, ภาษา, ขนาดต่อเหรียญ, จะเปิด short หรือไม่
   - เสร็จแล้วจะเช็กให้ว่า API key, การต่อ MT5 และเหรียญแต่ละตัวใช้งานได้ (`OK` / `FAIL`)
4. ใช้งานด้วยการดับเบิลคลิกไฟล์ในโฟลเดอร์เดียวกัน:

| ไฟล์ | ทำอะไร |
|---|---|
| `dry-run.bat` | วิเคราะห์และบอกว่าจะซื้อขายอะไร แต่ยังไม่ส่งออเดอร์ (ลองอันนี้ก่อน) |
| `run-now.bat` | วิเคราะห์และส่งออเดอร์ทันที 1 รอบ |
| `status.bat` | ดูยอดเงิน สถานะที่ถือ และประวัติการตัดสินใจ |
| `schedule.bat` | ตั้งให้บอทรันเองทุกวันตามเวลาที่กำหนด (ผ่าน Windows Task Scheduler) |
| `unschedule.bat` | ยกเลิกการรันอัตโนมัติ |
| `bot.bat` | ใช้คำสั่ง `tradingbot` อื่น ๆ เช่น `bot.bat history -c bot.json -n 50` |

ถ้ารันอัตโนมัติ: คอมต้องเปิดอยู่ ล็อกอิน Windows อยู่ และ MT5 ต้องเปิดและล็อกอินค้างไว้ตอนถึงเวลา
(ถ้าไม่อยากเปิดคอมทิ้งไว้ ใช้ Windows VPS ได้) ผลการรันแต่ละวันอยู่ในโฟลเดอร์ `logs`
การตั้งค่าอยู่ใน `bot.json` และ API key อยู่ใน `.env` แก้ด้วย Notepad ได้ ถ้าอยากตั้งค่าใหม่ทั้งหมด ลบ `bot.json` แล้วดับเบิลคลิก `install.bat` อีกครั้ง

## เทรดคริปโตกับ Exness (MetaTrader 5)

บอทส่งออเดอร์ CFD คริปโตเข้าบัญชี Exness ผ่านโปรแกรม MT5 ได้โดยตรง

**สิ่งที่ต้องมี:** คอมพิวเตอร์หรือ VPS ที่เป็น **Windows** ติดตั้งโปรแกรม MetaTrader 5 ของ Exness และเปิดค้างไว้ขณะบอททำงาน
(ไลบรารี `MetaTrader5` ของ Python ใช้ได้เฉพาะบน Windows)

1. ติดตั้ง Python 3.10 ขึ้นไป แล้วติดตั้งบอท
   ```bash
   pip install ".[mt5]"
   ```
2. เปิด MT5 แล้วล็อกอินบัญชี **Demo** ของ Exness ก่อน
   จากนั้นเปิด *Tools → Options → Expert Advisors* แล้วติ๊ก **Allow algorithmic trading**
3. ดูชื่อสัญลักษณ์ใน Market Watch ว่าลงท้ายด้วยอะไร
   - บัญชี Standard: `BTCUSDm` → `"symbol_suffix": "m"` (ค่าเริ่มต้นของ preset)
   - บัญชี Standard Cent: `BTCUSDc` → `"symbol_suffix": "c"`
   - บัญชี Pro / Raw Spread / Zero: `BTCUSD` → `"symbol_suffix": ""`
   - ถ้าชื่อไม่ตรงรูปแบบนี้ ให้กำหนดเองทีละตัว: `"symbol_map": {"BTC-USD": "BTCUSDm"}`
4. สร้าง config แล้วลองรัน
   ```bash
   tradingbot init bot.json --preset exness-crypto
   tradingbot status -c bot.json            # ต่อ MT5 ได้ไหม เห็นยอดเงินไหม
   tradingbot run -c bot.json --dry-run     # วิเคราะห์และคำนวณขนาด ยังไม่ส่งออเดอร์
   tradingbot run -c bot.json               # ส่งออเดอร์จริงเข้าบัญชี Demo
   tradingbot loop -c bot.json --at 08:00 --every-day   # คริปโตเทรดทุกวัน รวมเสาร์อาทิตย์
   ```

ถ้าไม่ได้ตั้ง `MT5_LOGIN` บอทจะใช้บัญชีที่ล็อกอินอยู่ใน MT5 ขณะนั้น
หรือจะกำหนดใน `.env` ก็ได้: `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` (เช่น `Exness-MT5Trial7` ดูชื่อได้ตอนล็อกอิน)

**ความปลอดภัยเฉพาะ MT5**
- ถ้าบัญชีที่ล็อกอินอยู่เป็น **บัญชีเงินจริง** บอทจะไม่ยอมเทรด จนกว่าจะตั้ง `"live": true` และรันด้วย `--live`
- บอทติดป้าย magic number ให้ออเดอร์ของตัวเอง และจะปิดหรือแก้เฉพาะออเดอร์ของบอทเท่านั้น ออเดอร์ที่คุณเปิดเองจะไม่ถูกแตะ (แต่ยังนับรวมในความเสี่ยงของพอร์ต)
- **บอทไม่ใช้เลเวอเรจ**: มูลค่าสถานะรวมทุกตัวจะไม่เกิน equity ของบัญชี ถึง Exness จะให้เลเวอเรจสูงแค่ไหนก็ตาม
- ขนาดออเดอร์ปัดลงตาม lot ขั้นต่ำและ step ของแต่ละสัญลักษณ์ (เช่น BTC 0.01 lot) ถ้าเงินน้อยจนไม่ถึง lot ขั้นต่ำ บอทจะข้ามไป
- ถ้าบัญชีไม่มีสัญลักษณ์ที่ตั้งไว้ บอทจะแจ้ง error ก่อนเริ่มวิเคราะห์ จึงไม่เสียค่า LLM ไปฟรี ๆ

### เปิด Short (ทำกำไรขาลง)

CFD เปิดสถานะขายได้ ค่าเริ่มต้นปิดไว้ (Sell = ขายของที่ถือออกหมด) ถ้าจะเปิด:

```json
"allow_short": true,
"rating_weights": {"Buy": 1.0, "Overweight": 0.5, "Underweight": 0.0, "Sell": -0.5}
```

แบบนี้ Sell จะเปิด short ขนาด 50% ของเพดาน ส่วน Underweight จะปิดสถานะ long ที่ถืออยู่ แต่จะไม่เปิด short
น้ำหนักติดลบใช้ได้เฉพาะเรตติ้งฝั่งลบ และต้องตั้ง `allow_short` ก่อน

> คริปโต CFD ผันผวนสูงและมีค่า swap ข้ามคืน ทั้งสองอย่างกินกำไรเมื่อถือนาน ให้ทดลองกับบัญชี Demo สักระยะก่อนเสมอ

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
| Sell | 0.0 | ขายออกทั้งหมด (ตั้งติดลบ + `allow_short` เพื่อเปิด short) |
| REVIEW | – | เอเจนต์ไม่ได้ให้เรตติ้งที่อ่านได้ ไม่เทรด ต้องให้คนดู |

กฎความปลอดภัย:

- เรตติ้งฝั่งบวก **ซื้ออย่างเดียว** ไม่ขาย และเรตติ้งฝั่งลบ **ขายอย่างเดียว** ไม่เปิดสถานะใหม่
- ไม่ short ยกเว้นเปิด `allow_short` และไม่ใช้เลเวอเรจ (มูลค่าสถานะรวมไม่เกิน equity)
- เก็บเงินสดขั้นต่ำ `min_cash_pct` ไว้เสมอ, ข้ามออเดอร์ที่เล็กกว่า `min_order_value`, จำกัดจำนวนออเดอร์ต่อรอบด้วย `max_orders_per_run`
- ปัดจำนวนหุ้นลงตาม `lot_sizes` (หุ้นไทยซื้อขายทีละ 100 หุ้น: `{"PTT.BK": 100}`) หรือเปิด `fractional` สำหรับคริปโต
- หุ้นตัวหนึ่ง error ไม่ทำให้ตัวอื่นหยุด

## ตั้งค่า (`bot.json`)

| คีย์ | ความหมาย |
|---|---|
| `watchlist` | ticker แบบ Yahoo Finance เช่น `NVDA`, `PTT.BK`, `BTC-USD` |
| `broker` | `paper` (จำลอง, ค่าเริ่มต้น), `alpaca` หรือ `mt5` (Exness และโบรก MT5 อื่น) |
| `live` | `true` = ใช้เงินจริง (ต้องใส่ `--live` ตอนรันด้วย) |
| `analysts` | นักวิเคราะห์ที่ใช้: `market`, `social`, `news`, `fundamentals` (ลดเพื่อประหยัดค่า LLM) |
| `currency`, `starting_cash`, `commission_pct` | สกุลเงิน, เงินตั้งต้น และค่าคอมมิชชันของบัญชี paper |
| `tradingagents` | ค่าที่ส่งต่อให้ TradingAgents เช่น `llm_provider`, `deep_think_llm`, `quick_think_llm`, `max_debate_rounds`, `output_language` |
| `allow_short` | อนุญาตให้น้ำหนักติดลบเปิด short (บัญชี CFD หรือ paper) |
| `mt5` | `symbol_suffix`, `symbol_map`, `magic`, `deviation` (slippage สูงสุดเป็น point) |
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
จากนั้นเพิ่มใน `make_broker` (`tradingbot/brokers/__init__.py`) เช่น Binance, OANDA หรือ Interactive Brokers

## ก่อนใช้เงินจริง

ใช้ backtest ของ TradingAgents ดูว่าเรตติ้งในอดีตทำกำไรเทียบ benchmark ได้จริงหรือไม่:

```bash
tradingagents backtest NVDA,AAPL --start 2026-06-01 --end 2026-08-01 --every 7
```
