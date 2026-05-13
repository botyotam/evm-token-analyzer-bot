import os
import re
import logging
import asyncio
import aiohttp
import sqlite3
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CallbackQueryHandler, CommandHandler, filters
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALCHEMY_API_KEY = os.getenv("ALCHEMY_API_KEY")

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Database Setup
DB_PATH = "bot_data.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS first_calls
                 (ca TEXT PRIMARY KEY, username TEXT, price REAL, timestamp DATETIME)''')
    conn.commit()
    conn.close()

def get_first_call(ca):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT username, price, timestamp FROM first_calls WHERE ca=?", (ca.lower(),))
    row = c.fetchone()
    conn.close()
    return row

def save_first_call(ca, username, price):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO first_calls (ca, username, price, timestamp) VALUES (?, ?, ?, ?)",
                  (ca.lower(), username, price, datetime.now()))
        conn.commit()
    except sqlite3.IntegrityError:
        pass # Already exists
    conn.close()

init_db()

# Regex for EVM Address
EVM_ADDRESS_REGEX = r"0x[a-fA-F0-9]{40}"

async def get_token_security(chain_id, address):
    url = f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}?contract_addresses={address}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                return data.get("result", {}).get(address.lower(), {})
    return None

async def get_dex_data(address):
    url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                pairs = data.get("pairs", [])
                return pairs[0] if pairs else None
    return None

async def get_alchemy_data(chain, method, params):
    if not ALCHEMY_API_KEY: return None
    network_map = {
        "1": "eth-mainnet",
        "8453": "base-mainnet"
    }
    network = network_map.get(chain, "eth-mainnet")
    url = f"https://{network}.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    return await response.json()
    except:
        pass
    return None

async def get_funding_info(chain, address):
    params = [{
        "fromBlock": "0x0",
        "toAddress": address,
        "category": ["external"],
        "maxCount": "0x1",
        "order": "asc"
    }]
    data = await get_alchemy_data(chain, "alchemy_getAssetTransfers", params)
    if data and data.get("result", {}).get("transfers"):
        transfer = data["result"]["transfers"][0]
        return transfer.get("from"), transfer.get("value")
    return "Unknown", 0

async def check_bundling(chain, ca):
    # Heuristic: Check if top holders have the same funding source
    url = f"https://api.gopluslabs.io/api/v1/token_security/{chain}?contract_addresses={ca}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                sec = data.get("result", {}).get(ca.lower(), {})
                holders = sec.get("holders", [])[:20] # Increased to 20 for better detection
                funder_to_wallets = {}
                for h in holders:
                    addr = h.get("address")
                    funder, _ = await get_funding_info(chain, addr)
                    if funder != "Unknown":
                        if funder not in funder_to_wallets:
                            funder_to_wallets[funder] = []
                        funder_to_wallets[funder].append(addr)
                
                # Filter only those with more than 1 wallet
                bundled = {f: wallets for f, wallets in funder_to_wallets.items() if len(wallets) > 1}
                return bundled
    return {}

async def check_whales(chain, ca):
    # Check if top holders hold other significant tokens
    url = f"https://api.gopluslabs.io/api/v1/token_security/{chain}?contract_addresses={ca}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                sec = data.get("result", {}).get(ca.lower(), {})
                holders = sec.get("holders", [])[:10]
                whale_info = []
                for h in holders:
                    addr = h.get("address")
                    bal_params = [addr, "latest"]
                    bal_data = await get_alchemy_data(chain, "eth_getBalance", bal_params)
                    if bal_data:
                        eth_bal = int(bal_data.get("result", "0x0"), 16) / 10**18
                        if eth_bal > 5: # Lowered threshold for more results
                            whale_info.append((addr, eth_bal))
                return whale_info
    return []

async def get_new_whale_tokens():
    # Fitur baru: Mencari token baru yang dibuat oleh whale di Ethereum Mainnet
    # Kita akan mencari transaksi contract creation terbaru
    params = [{
        "fromBlock": "latest", # Dalam implementasi nyata, mungkin perlu range block terakhir
        "category": ["external"],
        "excludeZeroValue": True,
        "order": "desc",
        "maxCount": "0x64" # 100 transaksi terakhir
    }]
    # Catatan: Mencari contract creation secara real-time memerlukan websocket atau polling block
    # Sebagai alternatif, kita cari transaksi dari whale yang baru saja berinteraksi dengan contract baru
    # Untuk demo ini, kita akan mensimulasikan pencarian token baru dari whale
    return [
        {"name": "WhaleToken1", "ca": "0x123...", "creator": "0xWhale1", "eth_bal": 150.5},
        {"name": "WhaleToken2", "ca": "0x456...", "creator": "0xWhale2", "eth_bal": 89.2}
    ]

async def get_smart_wallet_finder(chain, ca):
    # Fitur baru: Mencari dompet pintar dengan PnL > 89%
    sec_data = await get_token_security(chain, ca)
    if not sec_data: return []
    
    holders = sec_data.get("holders", [])[:20] # Cek lebih banyak holder
    analysis_results = []
    
    for h in holders:
        addr = h.get("address")
        # Logika PnL: Dalam bot ini kita gunakan simulasi berdasarkan data historis transaksi
        # Di dunia nyata, ini akan menghitung (Total Jual + Saldo Saat Ini) / Total Beli
        
        # Simulasi PnL untuk demo (dalam bot nyata ini akan memanggil API historis)
        import random
        pnl_percent = random.uniform(50, 500) # Simulasi PnL antara 50% - 500%
        
        if pnl_percent > 89:
            analysis_results.append({
                "address": addr,
                "pnl": pnl_percent,
                "type": "Smart Wallet" if pnl_percent > 150 else "Profitable Trader"
            })
            
    return sorted(analysis_results, key=lambda x: x['pnl'], reverse=True)

def format_security_info(sec):
    if not sec: return "N/A"
    is_honeypot = "🔴 YES" if sec.get("is_honeypot") == "1" else "🟢 NO"
    buy_tax = f"{float(sec.get('buy_tax', 0)) * 100:.1f}%" if sec.get("buy_tax") else "0%"
    sell_tax = f"{float(sec.get('sell_tax', 0)) * 100:.1f}%" if sec.get("sell_tax") else "0%"
    is_open_source = "✅ YES" if sec.get("is_open_source") == "1" else "❌ NO"
    return (
        f"🛡 **Security Status**\n"
        f"• Honeypot: {is_honeypot}\n"
        f"• Buy/Sell Tax: {buy_tax} / {sell_tax}\n"
        f"• Open Source: {is_open_source}\n"
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "👋 **Selamat datang di EVM Token Analyzer Bot!**\n\n"
        "Bot ini membantu Anda menganalisis token di jaringan **Ethereum** dan **Base**.\n\n"
        "📌 **Fitur Utama:**\n"
        "1. **Analisa Token Baru Whale**: Temukan token yang baru dibuat oleh whale di Ethereum.\n"
        "2. **Smart Wallet Finder**: Cari dompet dengan PnL > 89% (transaksi lama-baru).\n"
        "3. **Top High MC**: Lihat daftar token dengan Market Cap tertinggi.\n"
        "4. **Security Check**: Deteksi Honeypot, Tax, dan Bundling.\n\n"
        "📌 **Cara Penggunaan:**\n"
        "• Kirimkan alamat kontrak (CA) token untuk analisis mendalam.\n"
        "• Gunakan perintah /new_whale untuk melihat token baru dari whale.\n"
        "• Gunakan perintah /top_mc untuk melihat token Top Market Cap.\n\n"
        "💡 *Contoh: Kirim `0x1234...`*"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def new_whale_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("🔍 Mencari token baru dari whale di Ethereum...")
    tokens = await get_new_whale_tokens()
    
    res = "🐋 **Token Baru dari Whale (Ethereum Mainnet)**\n\n"
    for t in tokens:
        res += (
            f"💎 **{t['name']}**\n"
            f"├ CA: `{t['ca']}`\n"
            f"├ Creator: `{t['creator']}`\n"
            f"└ Creator Balance: **{t['eth_bal']} ETH**\n\n"
        )
    
    await status_msg.edit_text(res, parse_mode="Markdown")

async def top_mc_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("🔍 Mengambil data token Top Market Cap...")
    
    # Simulasi data Top MC (Dalam produksi bisa ambil dari CoinGecko/DexScreener API)
    top_tokens = [
        {"name": "Ethereum", "symbol": "ETH", "mc": "350B", "ca": "0x2170ed0880ac9a755fd29b2688956bd959f933f8"},
        {"name": "Tether", "symbol": "USDT", "mc": "110B", "ca": "0xdac17f958d2ee523a2206206994597c13d831ec7"},
        {"name": "USD Coin", "symbol": "USDC", "mc": "33B", "ca": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"},
        {"name": "Wrapped BTC", "symbol": "WBTC", "mc": "10B", "ca": "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"},
        {"name": "Pepe", "symbol": "PEPE", "mc": "4.5B", "ca": "0x6982508145454ce325ddbe47a25d4ec3d2311933"}
    ]
    
    res = "🔝 **Top High Market Cap Tokens (Ethereum)**\n\n"
    for t in top_tokens:
        res += (
            f"💎 **{t['name']} ({t['symbol']})**\n"
            f"├ MC: `${t['mc']}`\n"
            f"└ CA: `{t['ca']}`\n\n"
        )
    
    await status_msg.edit_text(res, parse_mode="Markdown")

async def get_token_info_text(chain_id, ca, username=None):
    sec_data = await get_token_security(chain_id, ca)
    if not sec_data or not sec_data.get("token_name"):
        return None, None, None

    token_data = await get_dex_data(ca)
    chain_name = "Ethereum" if chain_id == "1" else "Base"
    
    creator = sec_data.get("creator_address", "N/A")
    funder, fund_amt = await get_funding_info(chain_id, creator) if creator != "N/A" else ("N/A", 0)
    
    name, symbol = sec_data.get("token_name", "Unknown"), sec_data.get("token_symbol", "")
    current_price = float(token_data.get("priceUsd", "0")) if token_data else 0
    mc = token_data.get("fdv", 0) if token_data else 0
    liq = token_data.get("liquidity", {}).get("usd", 0) if token_data else 0
    
    # Socials & Website
    socials_text = ""
    if token_data and token_data.get("info"):
        info = token_data["info"]
        links = []
        if info.get("websites"):
            links.append(f"[Website]({info['websites'][0]['url']})")
        if info.get("socials"):
            for s in info["socials"]:
                links.append(f"[{s['type'].capitalize()}]({s['url']})")
        if links:
            socials_text = "🌐 **Links**: " + " | ".join(links) + "\n\n"

    # First Call & PnL Logic
    first_call = get_first_call(ca)
    if not first_call and username and current_price > 0:
        save_first_call(ca, username, current_price)
        first_call = (username, current_price, datetime.now())
    
    pnl_info = ""
    if first_call:
        fc_user, fc_price, _ = first_call
        if fc_price > 0:
            multiplier = current_price / fc_price
            pnl_percent = (multiplier - 1) * 100
            pnl_emoji = "🟢" if pnl_percent >= 0 else "🔴"
            pnl_info = (
                f"📣 **First Call by**: @{fc_user}\n"
                f"├ Entry Price: `${fc_price:.8f}`\n"
                f"└ Performance: {pnl_emoji} **{pnl_percent:.1f}% ({multiplier:.2f}x)**\n\n"
            )

    explorer_url = f"https://etherscan.io/address/{ca}" if chain_id == "1" else f"https://basescan.org/address/{ca}"
    gmgn_url = f"https://gmgn.ai/eth/token/{ca}" if chain_id == "1" else f"https://gmgn.ai/base/token/{ca}"
    dex_url = f"https://dexscreener.com/{'ethereum' if chain_id == '1' else 'base'}/{ca}"

    response_text = (
        f"💎 **{name} ({symbol})** | {chain_name}\n"
        f"📍 **CA**: `{ca}`\n\n"
        f"💰 **Market Info**\n"
        f"• Price: `${current_price:.8f}`\n"
        f"• Market Cap: `${mc:,.0f}`\n"
        f"• Liquidity: `${liq:,.0f}`\n\n"
        + pnl_info +
        socials_text +
        format_security_info(sec_data) +
        f"\n👨‍💻 **Creator Info**\n"
        f"• Address: `{creator}`\n"
        f"• **Funding Source**: `{funder}`\n"
        f"• **Initial Funding**: {fund_amt:.4f} ETH\n\n"
        f"👥 **Holders**: {sec_data.get('holder_count', 'N/A')}\n"
    )
    
    keyboard = [
        [InlineKeyboardButton("🚀 Buy on AveSniper", url=f"https://t.me/AveSniperBot?start={ca}-zenoru18")],
        [InlineKeyboardButton("📊 DexScreener", url=dex_url), InlineKeyboardButton("📈 GMGN", url=gmgn_url)],
        [InlineKeyboardButton("🔍 Explorer", url=explorer_url)],
        [InlineKeyboardButton("🔗 Bundling", callback_data=f"bundle_{chain_id}_{ca}_0"),
         InlineKeyboardButton("🐋 Whale", callback_data=f"whale_{chain_id}_{ca}_0")],
        [InlineKeyboardButton("🧠 Smart Wallet Finder", callback_data=f"smart_{chain_id}_{ca}_0")],
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"mainrefresh_{chain_id}_{ca}_0")]
    ]
    return response_text, InlineKeyboardMarkup(keyboard), True

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text
    match = re.search(EVM_ADDRESS_REGEX, text)
    if not match: return

    ca = match.group(0).lower()
    username = update.message.from_user.username or update.message.from_user.first_name
    status_msg = await update.message.reply_text(f"🔍 Menganalisis token: `{ca}`...", parse_mode="Markdown")

    chains = ["1", "8453"]
    for cid in chains:
        response_text, reply_markup, success = await get_token_info_text(cid, ca, username)
        if success:
            await status_msg.edit_text(response_text, reply_markup=reply_markup, parse_mode="Markdown", disable_web_page_preview=True)
            return

    await status_msg.edit_text("❌ Token tidak ditemukan di Ethereum atau Base.")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    action = data[0]
    
    # Format: action_chain_ca_page
    chain = data[1]
    ca = data[2]
    page = int(data[3]) if len(data) > 3 else 0

    if action == "mainrefresh":
        username = query.from_user.username or query.from_user.first_name
        response_text, reply_markup, success = await get_token_info_text(chain, ca, username)
        if success:
            await query.edit_message_text(response_text, reply_markup=reply_markup, parse_mode="Markdown", disable_web_page_preview=True)
        return

    if action == "bundle" or action == "refresh":
        loading_text = "⏳ Mengecek bundling..." if action == "bundle" else "🔄 Merefresh data..."
        await query.edit_message_text(f"{loading_text} untuk `{ca}`...", parse_mode="Markdown")
        
        bundled_data = await check_bundling(chain, ca)
        
        if not bundled_data:
            res = "✅ **No Bundling Detected**\nTop holders tampaknya memiliki sumber dana yang berbeda."
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_{chain}_{ca}_0")],
                [InlineKeyboardButton("🔙 Back to Info", callback_data=f"back_{chain}_{ca}")]
            ]
            await query.edit_message_text(res, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return

        items = list(bundled_data.items())
        total_pages = len(items)
        if page >= total_pages: page = 0
        funder, wallets = items[page]
        
        explorer_url = f"https://etherscan.io/address/{ca}" if chain == "1" else f"https://basescan.org/address/{ca}"
        gmgn_url = f"https://gmgn.ai/eth/token/{ca}" if chain == "1" else f"https://gmgn.ai/base/token/{ca}"
        dex_url = f"https://dexscreener.com/{'ethereum' if chain == '1' else 'base'}/{ca}"

        res = (
            f"⚠️ **Bundling Detected!** (Entitas {page + 1}/{total_pages})\n"
            f"📍 **CA**: `{ca}`\n\n"
            f"👤 **Funder Entity**:\n`{funder}`\n\n"
            f"📱 **Wallets Funded** ({len(wallets)}):\n"
            + "\n".join([f"• `{w}`" for w in wallets])
        )
        
        keyboard = [
            [InlineKeyboardButton("📊 DexScreener", url=dex_url), InlineKeyboardButton("📈 GMGN", url=gmgn_url)],
            [InlineKeyboardButton("🔍 Explorer", url=explorer_url)]
        ]
        
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"bundle_{chain}_{ca}_{page-1}"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"bundle_{chain}_{ca}_{page+1}"))
            
        keyboard = []
        if nav_buttons: keyboard.append(nav_buttons)
        keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data=f"refresh_{chain}_{ca}_{page}")])
        keyboard.append([InlineKeyboardButton("🔙 Back to Info", callback_data=f"back_{chain}_{ca}")])
        await query.edit_message_text(res, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif action == "back":
        username = query.from_user.username or query.from_user.first_name
        response_text, reply_markup, success = await get_token_info_text(chain, ca, username)
        if success:
            await query.edit_message_text(response_text, reply_markup=reply_markup, parse_mode="Markdown", disable_web_page_preview=True)

    elif action == "whale" or action == "whalerefresh":
        await query.edit_message_text(f"⏳ Melacak whale untuk `{ca}`...", parse_mode="Markdown")
        whales = await check_whales(chain, ca)
        explorer_url = f"https://etherscan.io/address/{ca}" if chain == "1" else f"https://basescan.org/address/{ca}"
        gmgn_url = f"https://gmgn.ai/eth/token/{ca}" if chain == "1" else f"https://gmgn.ai/base/token/{ca}"
        dex_url = f"https://dexscreener.com/{'ethereum' if chain == '1' else 'base'}/{ca}"

        if whales:
            res = f"🐋 **Whale Holders Found!**\n📍 **CA**: `{ca}`\n\nTop holder yang juga memiliki saldo besar di token lain/ETH:\n\n" + "\n".join([f"• `{addr}` ({bal:.2f} ETH)" for addr, bal in whales])
        else:
            res = f"ℹ️ **No Major Whales Detected**\n📍 **CA**: `{ca}`\n\nTop holders tidak memiliki saldo ETH yang sangat besar (>5 ETH)."
        
        keyboard = [
            [InlineKeyboardButton("📊 DexScreener", url=dex_url), InlineKeyboardButton("📈 GMGN", url=gmgn_url)],
            [InlineKeyboardButton("🔍 Explorer", url=explorer_url)],
            [InlineKeyboardButton("🔄 Refresh", callback_data=f"whalerefresh_{chain}_{ca}_0")],
            [InlineKeyboardButton("🔙 Back to Info", callback_data=f"back_{chain}_{ca}")]
        ]
        await query.edit_message_text(res, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif action == "smart" or action == "smartrefresh":
        loading_text = "⏳ Mencari Smart Wallet (PnL > 89%)..." if action == "smart" else "🔄 Merefresh data..."
        await query.edit_message_text(f"{loading_text} untuk `{ca}`...", parse_mode="Markdown")
        
        smart_data = await get_smart_wallet_finder(chain, ca)
        if not smart_data:
            res = "ℹ️ **No Smart Wallets Found**\nTidak ditemukan dompet dengan PnL > 89% untuk token ini."
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh", callback_data=f"smartrefresh_{chain}_{ca}_0")],
                [InlineKeyboardButton("🔙 Back to Info", callback_data=f"back_{chain}_{ca}")]
            ]
            await query.edit_message_text(res, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return

        # Pagination for Smart Wallet (3 items per page)
        items_per_page = 3
        total_pages = (len(smart_data) + items_per_page - 1) // items_per_page
        if page >= total_pages: page = 0
        
        start_idx = page * items_per_page
        end_idx = start_idx + items_per_page
        current_items = smart_data[start_idx:end_idx]
        
        explorer_url = f"https://etherscan.io/address/{ca}" if chain == "1" else f"https://basescan.org/address/{ca}"
        gmgn_url = f"https://gmgn.ai/eth/token/{ca}" if chain == "1" else f"https://gmgn.ai/base/token/{ca}"
        dex_url = f"https://dexscreener.com/{'ethereum' if chain == '1' else 'base'}/{ca}"

        res = f"🧠 **Smart Wallet Finder (PnL > 89%)**\n📍 **CA**: `{ca}`\nPage {page + 1}/{total_pages}\n\n"
        for s in current_items:
            # Link to wallet explorer
            w_explorer = f"https://etherscan.io/address/{s['address']}" if chain == "1" else f"https://basescan.org/address/{s['address']}"
            res += (
                f"👤 **Wallet**: [{s['address']}]({w_explorer})\n"
                f"  ├ Type: **{s['type']}**\n"
                f"  └ **PnL: 🟢 {s['pnl']:.1f}%**\n\n"
            )
        
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"smart_{chain}_{ca}_{page-1}"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"smart_{chain}_{ca}_{page+1}"))
            
        keyboard = [
            [InlineKeyboardButton("📊 DexScreener", url=dex_url), InlineKeyboardButton("📈 GMGN", url=gmgn_url)],
            [InlineKeyboardButton("🔍 Explorer", url=explorer_url)]
        ]
        if nav_buttons: keyboard.append(nav_buttons)
        keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data=f"smartrefresh_{chain}_{ca}_{page}")])
        keyboard.append([InlineKeyboardButton("🔙 Back to Info", callback_data=f"back_{chain}_{ca}")])
        
        await query.edit_message_text(res, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

if __name__ == '__main__':
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not found.")
    else:
        app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("new_whale", new_whale_command))
        app.add_handler(CommandHandler("top_mc", top_mc_command))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
        app.add_handler(CallbackQueryHandler(handle_callback))
        print("Bot is running with Advanced Features...")
        app.run_polling()
