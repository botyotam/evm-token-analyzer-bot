import os
import re
import logging
import asyncio
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CallbackQueryHandler, filters
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
    # This is a simplified version for the bot
    url = f"https://api.gopluslabs.io/api/v1/token_security/{chain}?contract_addresses={ca}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                sec = data.get("result", {}).get(ca.lower(), {})
                holders = sec.get("holders", [])[:10]
                funders = {}
                for h in holders:
                    addr = h.get("address")
                    funder, _ = await get_funding_info(chain, addr)
                    if funder != "Unknown":
                        funders[funder] = funders.get(funder, 0) + 1
                
                bundled = [f for f, count in funders.items() if count > 1]
                return bundled
    return []

async def check_whales(chain, ca):
    # Check if top holders hold other significant tokens
    url = f"https://api.gopluslabs.io/api/v1/token_security/{chain}?contract_addresses={ca}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                sec = data.get("result", {}).get(ca.lower(), {})
                holders = sec.get("holders", [])[:5]
                whale_info = []
                for h in holders:
                    addr = h.get("address")
                    # Check balance of other tokens (simplified: check ETH balance)
                    bal_params = [addr, "latest"]
                    bal_data = await get_alchemy_data(chain, "eth_getBalance", bal_params)
                    if bal_data:
                        eth_bal = int(bal_data.get("result", "0x0"), 16) / 10**18
                        if eth_bal > 10: # Whale threshold: 10 ETH
                            whale_info.append((addr, eth_bal))
                return whale_info
    return []

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

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text
    match = re.search(EVM_ADDRESS_REGEX, text)
    if not match: return

    ca = match.group(0).lower()
    status_msg = await update.message.reply_text(f"🔍 Menganalisis token: `{ca}`...", parse_mode="Markdown")

    chains = [("1", "Ethereum"), ("8453", "Base")]
    token_data, sec_data, chain_name, chain_id = None, None, "", ""

    for cid, cname in chains:
        sec_data = await get_token_security(cid, ca)
        if sec_data and sec_data.get("token_name"):
            token_data = await get_dex_data(ca)
            chain_name, chain_id = cname, cid
            break

    if not sec_data:
        await status_msg.edit_text("❌ Token tidak ditemukan di Ethereum atau Base.")
        return

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
        [InlineKeyboardButton("🔗 Check Bundling", callback_data=f"bundle_{chain_id}_{ca}"),
         InlineKeyboardButton("🐋 Whale Tracker", callback_data=f"whale_{chain_id}_{ca}")]
    ]
    await status_msg.edit_text(response_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown", disable_web_page_preview=True)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("_")
    action, chain, ca = data[0], data[1], data[2]

    if action == "bundle":
        await query.edit_message_text(f"⏳ Mengecek bundling untuk `{ca}`...", parse_mode="Markdown")
        bundled = await check_bundling(chain, ca)
        if bundled:
            res = "⚠️ **Bundling Detected!**\nBeberapa holder didanai oleh sumber yang sama:\n" + "\n".join([f"`{f}`" for f in bundled])
        else:
            res = "✅ **No Bundling Detected**\nTop holders tampaknya memiliki sumber dana yang berbeda."
        await query.edit_message_text(res, parse_mode="Markdown")

    elif action == "whale":
        await query.edit_message_text(f"⏳ Melacak whale untuk `{ca}`...", parse_mode="Markdown")
        whales = await check_whales(chain, ca)
        if whales:
            res = "🐋 **Whale Holders Found!**\nTop holder yang juga memiliki saldo besar di token lain/ETH:\n" + "\n".join([f"`{addr[:10]}...` ({bal:.2f} ETH)" for addr, bal in whales])
        else:
            res = "ℹ️ **No Major Whales Detected**\nTop holders tidak memiliki saldo ETH yang sangat besar (>10 ETH)."
        await query.edit_message_text(res, parse_mode="Markdown")

if __name__ == '__main__':
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not found.")
    else:
        app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
        app.add_handler(CallbackQueryHandler(handle_callback))
        print("Bot is running with Advanced Features...")
        app.run_polling()
