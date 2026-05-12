import os
import re
import logging
import asyncio
import aiohttp
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

async def get_smart_money(chain, ca):
    # Heuristic: First buyers or holders with high balance and funding from known sources
    # For a real bot, this would use a database of known smart money or analyze PnL
    # Here we'll look for the first 5 buyers (First Buyers)
    params = [{
        "fromBlock": "0x0",
        "toAddress": ca,
        "category": ["external", "erc20"],
        "maxCount": "0x5",
        "order": "asc"
    }]
    data = await get_alchemy_data(chain, "alchemy_getAssetTransfers", params)
    smart_info = []
    if data and data.get("result", {}).get("transfers"):
        for t in data["result"]["transfers"]:
            addr = t.get("from")
            if addr and addr.lower() != ca.lower():
                smart_info.append({"address": addr, "type": "First Buyer"})
    
    # Check for Insider (funded by creator or same source as creator)
    sec_data = await get_token_security(chain, ca)
    creator = sec_data.get("creator_address", "").lower()
    creator_funder, _ = await get_funding_info(chain, creator)
    
    holders = sec_data.get("holders", [])[:10]
    for h in holders:
        addr = h.get("address")
        if addr.lower() == creator: continue
        funder, _ = await get_funding_info(chain, addr)
        if funder.lower() == creator or (funder.lower() == creator_funder.lower() and funder != "Unknown"):
            smart_info.append({"address": addr, "type": "Potential Insider"})
            
    return smart_info

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
        "📌 **Cara Penggunaan:**\n"
        "1. Kirimkan alamat kontrak (CA) token yang ingin dianalisis.\n"
        "2. Bot akan memberikan informasi harga, keamanan, dan kreator.\n"
        "3. Gunakan tombol menu untuk mengecek:\n"
        "   • **Bundling**: Deteksi holder dengan sumber dana sama.\n"
        "   • **Whale Tracker**: Lacak holder dengan saldo besar.\n"
        "   • **Smart/Insider**: Lacak pembeli pertama atau insider.\n\n"
        "💡 *Contoh: Kirim `0x1234...`*"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def get_token_info_text(chain_id, ca):
    sec_data = await get_token_security(chain_id, ca)
    if not sec_data or not sec_data.get("token_name"):
        return None, None, None

    token_data = await get_dex_data(ca)
    chain_name = "Ethereum" if chain_id == "1" else "Base"
    
    creator = sec_data.get("creator_address", "N/A")
    funder, fund_amt = await get_funding_info(chain_id, creator) if creator != "N/A" else ("N/A", 0)
    
    name, symbol = sec_data.get("token_name", "Unknown"), sec_data.get("token_symbol", "")
    price = token_data.get("priceUsd", "0") if token_data else "0"
    mc = token_data.get("fdv", 0) if token_data else 0
    liq = token_data.get("liquidity", {}).get("usd", 0) if token_data else 0
    
    response_text = (
        f"💎 **{name} ({symbol})** | {chain_name}\n"
        f"`{ca}`\n\n"
        f"💰 **Market Info**\n"
        f"• Price: ${price}\n"
        f"• Market Cap: ${mc:,.0f}\n"
        f"• Liquidity: ${liq:,.0f}\n\n"
        + format_security_info(sec_data) +
        f"\n👨‍💻 **Creator Info**\n"
        f"• Address: `{creator}`\n"
        f"• **Funding Source**: `{funder}`\n"
        f"• **Initial Funding**: {fund_amt:.4f} ETH\n\n"
        f"👥 **Holders**: {sec_data.get('holder_count', 'N/A')}\n"
    )
    
    keyboard = [
        [InlineKeyboardButton("🚀 Buy on AveSniper", url=f"https://t.me/AveSniperBot?start={ca}-zenoru18")],
        [InlineKeyboardButton("🔗 Bundling", callback_data=f"bundle_{chain_id}_{ca}_0"),
         InlineKeyboardButton("🐋 Whale", callback_data=f"whale_{chain_id}_{ca}_0")],
        [InlineKeyboardButton("🧠 Smart/Insider", callback_data=f"smart_{chain_id}_{ca}_0")],
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"mainrefresh_{chain_id}_{ca}_0")]
    ]
    return response_text, InlineKeyboardMarkup(keyboard), True

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text
    match = re.search(EVM_ADDRESS_REGEX, text)
    if not match: return

    ca = match.group(0).lower()
    status_msg = await update.message.reply_text(f"🔍 Menganalisis token: `{ca}`...", parse_mode="Markdown")

    chains = ["1", "8453"]
    for cid in chains:
        response_text, reply_markup, success = await get_token_info_text(cid, ca)
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
        response_text, reply_markup, success = await get_token_info_text(chain, ca)
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
        
        res = (
            f"⚠️ **Bundling Detected!** (Entitas {page + 1}/{total_pages})\n\n"
            f"👤 **Funder Entity**:\n`{funder}`\n\n"
            f"📱 **Wallets Funded** ({len(wallets)}):\n"
            + "\n".join([f"• `{w}`" for w in wallets])
        )
        
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
        response_text, reply_markup, success = await get_token_info_text(chain, ca)
        if success:
            await query.edit_message_text(response_text, reply_markup=reply_markup, parse_mode="Markdown", disable_web_page_preview=True)

    elif action == "whale" or action == "whalerefresh":
        await query.edit_message_text(f"⏳ Melacak whale untuk `{ca}`...", parse_mode="Markdown")
        whales = await check_whales(chain, ca)
        if whales:
            res = "🐋 **Whale Holders Found!**\nTop holder yang juga memiliki saldo besar di token lain/ETH:\n\n" + "\n".join([f"• `{addr}` ({bal:.2f} ETH)" for addr, bal in whales])
        else:
            res = "ℹ️ **No Major Whales Detected**\nTop holders tidak memiliki saldo ETH yang sangat besar (>5 ETH)."
        
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data=f"whalerefresh_{chain}_{ca}_0")],
            [InlineKeyboardButton("🔙 Back to Info", callback_data=f"back_{chain}_{ca}")]
        ]
        await query.edit_message_text(res, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif action == "smart" or action == "smartrefresh":
        await query.edit_message_text(f"⏳ Melacak Smart Money/Insider untuk `{ca}`...", parse_mode="Markdown")
        smart_money = await get_smart_money(chain, ca)
        if smart_money:
            res = "🧠 **Smart Money / Insider Found!**\n\n" + "\n".join([f"• `{s['address']}`\n  Type: **{s['type']}**" for s in smart_money])
        else:
            res = "ℹ️ **No Smart Money/Insider Detected**\nTidak ditemukan pembeli pertama atau insider yang mencurigakan."
        
        keyboard = [
            [InlineKeyboardButton("🔄 Refresh", callback_data=f"smartrefresh_{chain}_{ca}_0")],
            [InlineKeyboardButton("🔙 Back to Info", callback_data=f"back_{chain}_{ca}")]
        ]
        await query.edit_message_text(res, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

if __name__ == '__main__':
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not found.")
    else:
        app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
        app.add_handler(CallbackQueryHandler(handle_callback))
        print("Bot is running with Advanced Features...")
        app.run_polling()
