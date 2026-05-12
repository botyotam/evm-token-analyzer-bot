import os
import re
import logging
import asyncio
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
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

async def get_alchemy_balance(chain, address):
    if not ALCHEMY_API_KEY: return 0
    network_map = {
        "1": "eth-mainnet",
        "8453": "base-mainnet"
    }
    network = network_map.get(chain, "eth-mainnet")
    url = f"https://{network}.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getBalance",
        "params": [address, "latest"]
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    hex_bal = data.get("result", "0x0")
                    return int(hex_bal, 16) / 10**18
    except:
        pass
    return 0

def format_security_info(sec):
    if not sec: return "N/A"
    
    is_honeypot = "🔴 YES" if sec.get("is_honeypot") == "1" else "🟢 NO"
    buy_tax = f"{float(sec.get('buy_tax', 0)) * 100:.1f}%" if sec.get("buy_tax") else "0%"
    sell_tax = f"{float(sec.get('sell_tax', 0)) * 100:.1f}%" if sec.get("sell_tax") else "0%"
    is_open_source = "✅ YES" if sec.get("is_open_source") == "1" else "❌ NO"
    is_proxy = "⚠️ YES" if sec.get("is_proxy") == "1" else "✅ NO"
    is_mintable = "⚠️ YES" if sec.get("is_mintable") == "1" else "✅ NO"
    
    return (
        f"🛡 **Security Status**\n"
        f"• Honeypot: {is_honeypot}\n"
        f"• Buy/Sell Tax: {buy_tax} / {sell_tax}\n"
        f"• Open Source: {is_open_source}\n"
        f"• Proxy: {is_proxy}\n"
        f"• Mintable: {is_mintable}\n"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
        
    text = update.message.text
    match = re.search(EVM_ADDRESS_REGEX, text)
    
    if not match:
        return

    ca = match.group(0)
    status_msg = await update.message.reply_text(f"🔍 Menganalisis token: `{ca}`...", parse_mode="Markdown")

    # Try ETH first, then Base
    chains = [("1", "Ethereum"), ("8453", "Base")]
    token_data = None
    sec_data = None
    chain_name = ""
    chain_id = ""

    for cid, cname in chains:
        sec_data = await get_token_security(cid, ca)
        if sec_data and sec_data.get("token_name"):
            token_data = await get_dex_data(ca)
            chain_name = cname
            chain_id = cid
            break

    if not sec_data or not sec_data.get("token_name"):
        await status_msg.edit_text("❌ Token tidak ditemukan di Ethereum atau Base.")
        return

    # Extract info
    name = sec_data.get("token_name", "Unknown")
    symbol = sec_data.get("token_symbol", "")
    price = token_data.get("priceUsd", "0") if token_data else "0"
    mc = token_data.get("fdv", 0) if token_data else 0
    liq = token_data.get("liquidity", {}).get("usd", 0) if token_data else 0
    
    creator = sec_data.get("creator_address", "N/A")
    creator_bal = await get_alchemy_balance(chain_id, creator) if creator != "N/A" else 0
    
    socials = token_data.get("info", {}) if token_data else {}
    websites = socials.get("websites", [])
    social_links = socials.get("socials", [])
    
    web_text = websites[0].get("url") if websites else "N/A"
    twitter = next((s.get("url") for s in social_links if s.get("type") == "twitter"), "N/A")
    telegram = next((s.get("url") for s in social_links if s.get("type") == "telegram"), "N/A")

    # Holder Tracker
    holder_count = sec_data.get("holder_count", "N/A")
    
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
        f"• Funding Balance: {creator_bal:.4f} ETH\n\n"
        f"👥 **Holders**: {holder_count}\n\n"
        f"🌐 **Links**\n"
        f"• Website: {web_text}\n"
        f"• Twitter: {twitter}\n"
        f"• Telegram: {telegram}\n"
    )

    buy_link = f"https://t.me/AveSniperBot?start={ca}-zenoru18"
    keyboard = [[InlineKeyboardButton("🚀 Buy on AveSniper", url=buy_link)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await status_msg.edit_text(response_text, reply_markup=reply_markup, parse_mode="Markdown", disable_web_page_preview=True)

if __name__ == '__main__':
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not found.")
    else:
        app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
        print("Bot is running...")
        app.run_polling()
