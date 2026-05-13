# EVM Token Analyzer Bot (ETH & Base) - Whale & Smart Wallet Edition

Bot Telegram canggih untuk menganalisis token di jaringan Ethereum dan Base, kini dilengkapi dengan fitur pelacakan whale dan pencarian dompet pintar.

## Fitur Unggulan
- **🐋 New Whale Token Analysis**: Deteksi token baru yang dibuat oleh whale (saldo > 10 ETH) di Ethereum Mainnet menggunakan Alchemy API.
- **🧠 Smart Wallet Finder**: Mencari dompet dengan PnL di atas 89% dari riwayat transaksi lama hingga baru.
- **🛡️ Security Check**: Deteksi Honeypot, Tax, Open Source, dan deteksi Bundling (holder dengan sumber dana sama).
- **📊 Market Data**: Harga real-time, Market Cap, dan Likuiditas via DexScreener.
- **🔗 Socials & Creator Info**: Link media sosial otomatis dan detail pendanaan awal kreator.

## Cara Penggunaan
1. **Analisis Token**: Kirimkan alamat kontrak (CA) token ke bot.
2. **Cari Token Whale**: Gunakan perintah `/new_whale` untuk melihat daftar token terbaru dari whale.
3. **Smart Wallet**: Klik tombol "Smart Wallet Finder" pada hasil analisis token untuk melihat trader paling profit.

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

## Kontribusi
Silakan buka issue atau pull request untuk fitur tambahan!
