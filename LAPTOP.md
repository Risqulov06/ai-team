# Shaxsiy noutbukda: avto-start va avto-ulanish

Bot noutbukingizda **fon xizmati** bo'lib ishlaydi. Server kerak emas.

| Nima bo'ladi | Qanday |
|---|---|
| Noutbuk yoqilganda | Bot o'zi ishga tushadi, oyna ochilmaydi |
| Internet uzilsa | Bot kutib turadi. Internet qaytganda o'zi qayta ulanadi |
| Noutbuk uyqudan uyg'onsa | Bot yangi ulanish bilan qayta ishga tushadi |
| Bot xato bilan to'xtasa | 10 soniya – 5 daqiqa ichida o'zi qayta yoqiladi |
| `.env` ni o'zgartirsangiz | Bot yangi sozlamalar bilan o'zi qayta yoqiladi |
| `.env` hali to'ldirilmagan bo'lsa | Xizmat kutadi. Tokenni yozishingiz bilan **paketlarni o'zi o'rnatadi** va botni ishga tushiradi |
| `git pull` dan keyin paketlar o'zgarsa | O'zi qayta o'rnatadi |

Hammasini `tgbot/service.py` boshqaradi. Paketlar loyiha ichidagi `.venv` papkasiga o'rnatiladi, kompyuteringizdagi boshqa dasturlarga tegmaydi.

## O'rnatish (bir marta)

Avval loyihani yuklab oling: GitHub'da **Code → Download ZIP** ni bosib, ochib qo'ying. Yoki `git clone https://github.com/Risqulov06/ai-team` qiling.

### Windows

1. **`install.bat`** faylini ikki marta bosing.
2. Python bo'lmasa, o'zi o'rnatadi. Shundan keyin `install.bat` ni yana bir marta bosing.
3. Bot tokenini so'raydi (@BotFather → `/newbot`). Tokenni qo'yib, Enter bosing.
4. Tayyor. Bot Windows'ga kirganingizda o'zi ishga tushadi (Task Scheduler → "AI Team Bot").

Holatni ko'rish: **`status.bat`**. O'chirish: **`uninstall.bat`**.

### macOS / Linux

Terminalda loyiha papkasida:

```bash
bash install.sh
```

Holat:

```bash
python3 tgbot/service.py --status
```

O'chirish:

```bash
bash uninstall.sh
```

macOS'da LaunchAgent, Linux'da systemd user service o'rnatiladi. Linux'da bot tizimga kirmasangiz ham ishga tushadi.

## O'rnatgandan keyin

1. Telegramda botingizga `/whoami` yozing.
2. Kelgan ID ni `.env` → `ALLOWED_USER_IDS=` ga yozib saqlang. Bot o'zi qayta yoqiladi, endi uni faqat siz boshqarasiz.
3. `/here` yozing: ertalabki reja shu chatga keladi. Vaqtini o'zgartirish: `/settime 08:00`.
4. AI agent uchun (botga oddiy matn → Claude Code) Claude Code'ni o'rnating va bir marta `claude` buyrug'i bilan kiring. O'rnatuvchi buyruqni ko'rsatadi.
5. O'z Telegramingizni ulash (`/ai` buyruqlari uchun): `.env` ga `TG_API_ID` va `TG_API_HASH` ni yozing (my.telegram.org). Keyin bir marta login qiling:
   - Windows: `.venv\Scripts\python tgbot\userbot.py login`
   - macOS / Linux: `.venv/bin/python tgbot/userbot.py login`

## Loglar

- `out/logs/service.log`: xizmat nima qildi (ishga tushdi, internet uzildi va qaytdi, qayta yoqildi)
- `out/logs/bot.log`: botning o'z xabarlari va xatolari

Ikkala fayl ham 5 MB dan oshsa, eskisi `.1` ga ko'chiriladi.

## Muhim

- **Bitta token — bitta bot.** Bot telefonda (Termux) yoki Render'da ham ishlayotgan bo'lsa, uni o'sha yerda to'xtating. Aks holda Telegram "Conflict" xatosini beradi. Noutbukdagi eski `tmux` usulini `install.sh` o'zi to'xtatadi.
- Noutbuk **o'chiq yoki uyquda** bo'lsa, bot ishlamaydi. Ertalabki xabar o'z vaqtida kelishi uchun noutbuk yoqiq bo'lishi kerak. Windows'da: Sozlamalar → Tizim → Quvvat → "Uyqu" ni "Hech qachon" (zaryadda) qiling.
