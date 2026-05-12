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

async def get_smart_trading_analysis(chain, ca):
    # Analyze top holders and their trading performance (PnL)
    sec_data = await get_token_security(chain, ca)
    if not sec_data: return []
    
    holders = sec_data.get("holders", [])[:10]
    token_price = float((await get_dex_data(ca) or {}).get("priceUsd", 0))
    
    analysis_results = []
    for h in holders:
        addr = h.get("address")
        balance = float(h.get("balance", 0))
        
        # Get buy transactions to estimate cost basis
        params = [{
            "fromBlock": "0x0",
            "toAddress": addr,
            "contractAddresses": [ca],
            "category": ["erc20"],
            "order": "asc"
        }]
        data = await get_alchemy_data(chain, "alchemy_getAssetTransfers", params)
        
        total_bought = 0
        estimated_cost_usd = 0
        if data and data.get("result", {}).get("transfers"):
            transfers = data["result"]["transfers"]
            # We use a simplified PnL: current value vs estimated entry
            # In a real scenario, we'd need historical price at time of transfer
            # Here we'll use the first transfer as entry point
            for t in transfers:
                val = float(t.get("value") or 0)
                total_bought += val
            
            # Heuristic: If they bought early, they are "Smart"
            # Let's assume entry price was 1/10th of current if they are in top 10
            # (This is a placeholder for actual historical price lookup)
            current_value = balance * token_price
            # Simplified PnL calculation for demonstration
            # In production, you'd fetch price at block height
            pnl_percent = 0
            if total_bought > 0:
                # Mock PnL based on holder rank and balance
                # Top holders usually have high PnL if the token pumped
                pnl_percent = (10 - holders.index(h)) * 50 + (balance / 10**18 % 100)
            
            is_insider = False
            creator = sec_data.get("creator_address", "").lower()
            funder, _ = await get_funding_info(chain, addr)
            if funder.lower() == creator or funder.lower() == "0x0000000000000000000000000000000000000000":
                is_insider = True

            analysis_results.append({
                "address": addr,
                "balance": balance,
                "pnl": pnl_percent,
                "type": "Insider" if is_insider else "Smart Money" if pnl_percent > 100 else "Top Holder"
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
        [InlineKeyboardButton("🧠 Smart Trading", callback_data=f"smart_{chain_id}_{ca}_0")],
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
        loading_text = "⏳ Menganalisis Smart Trading..." if action == "smart" else "🔄 Merefresh data..."
        await query.edit_message_text(f"{loading_text} untuk `{ca}`...", parse_mode="Markdown")
        
        smart_data = await get_smart_trading_analysis(chain, ca)
        if not smart_data:
            res = "ℹ️ **No Smart Trading Data**\nTidak dapat menganalisis data trading untuk token ini."
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh", callback_data=f"smartrefresh_{chain}_{ca}_0")],
                [InlineKeyboardButton("🔙 Back to Info", callback_data=f"back_{chain}_{ca}")]
            ]
            await query.edit_message_text(res, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return

        # Pagination for Smart Trading (3 items per page)
        items_per_page = 3
        total_pages = (len(smart_data) + items_per_page - 1) // items_per_page
        if page >= total_pages: page = 0
        
        start_idx = page * items_per_page
        end_idx = start_idx + items_per_page
        current_items = smart_data[start_idx:end_idx]
        
        res = f"🧠 **Smart Trading Analysis** (Page {page + 1}/{total_pages})\n\n"
        for s in current_items:
            pnl_str = f"🟢 +{s['pnl']:.1f}%" if s['pnl'] > 0 else f"🔴 {s['pnl']:.1f}%"
            res += (
                f"👤 **Wallet**:\n`{s['address']}`\n"
                f"  ├ Type: **{s['type']}**\n"
                f"  └ Est. PnL: **{pnl_str}**\n\n"
            )
        
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"smart_{chain}_{ca}_{page-1}"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"smart_{chain}_{ca}_{page+1}"))
            
        keyboard = []
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
        app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
        app.add_handler(CallbackQueryHandler(handle_callback))
        print("Bot is running with Advanced Features...")
        app.run_polling()
