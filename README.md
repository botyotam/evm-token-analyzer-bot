# EVM Token Analyzer Bot (ETH & Base)

Bot Telegram untuk menganalisis token di jaringan Ethereum dan Base secara otomatis hanya dengan mengirimkan alamat kontrak (CA).

## Fitur
- **Deteksi Otomatis**: Cukup kirim CA, bot akan mendeteksi apakah token ada di ETH atau Base.
- **Analisis Keamanan**: Cek Honeypot, Buy/Sell Tax, Open Source, Proxy, dan Mintable (via GoPlus API).
- **Data Pasar**: Harga real-time, Market Cap (FDV), dan Likuiditas (via DexScreener API).
- **Info Creator**: Alamat creator dan saldo pendanaan (via Alchemy API).
- **Social Media**: Link otomatis ke Website, Twitter, dan Telegram token.
- **Quick Buy**: Link langsung ke AveSniperBot dengan referral Anda.

## Cara Install & Jalankan

### 1. Persiapan API Key
Dapatkan API Key berikut:
- **Telegram Bot Token**: Dari [@BotFather](https://t.me/BotFather).
- **Alchemy API Key**: Dari [Alchemy Dashboard](https://dashboard.alchemy.com/).

### 2. Environment Variables
Buat file `.env` dan isi:
```env
TELEGRAM_BOT_TOKEN=your_bot_token
ALCHEMY_API_KEY=your_alchemy_key
```

### 3. Jalankan Lokal
```bash
pip install -r requirements.txt
python bot.py
```

### 4. Deployment
- **Railway/Render**: Gunakan `Dockerfile` atau `Procfile` yang sudah disediakan.
- **VPS**: Gunakan Docker atau jalankan langsung dengan `nohup` atau `pm2`.

## Kontribusi
Silakan buka issue atau pull request untuk fitur tambahan!
