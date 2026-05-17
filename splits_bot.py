import asyncio
import logging
from web3 import Web3
from telegram import Bot
from config import PRIVATE_KEY, RPC_URLS, SPLIT_MAIN_ADDRESSES, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from abis import SPLIT_MAIN_V1_ABI, ERC20_ABI

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SplitsDistributorBot:
    def __init__(self, chain_name):
        self.chain_name = chain_name
        self.rpc_url = RPC_URLS.get(chain_name)
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        self.account = self.w3.eth.account.from_key(PRIVATE_KEY)
        self.split_main_addr = SPLIT_MAIN_ADDRESSES.get(chain_name)
        self.split_main = self.w3.eth.contract(address=Web3.to_checksum_address(self.split_main_addr), abi=SPLIT_MAIN_V1_ABI)
        self.tg_bot = Bot(token=TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None

    async def send_telegram_notification(self, message):
        if self.tg_bot and TELEGRAM_CHAT_ID:
            try:
                await self.tg_bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='Markdown')
            except Exception as e:
                logger.error(f"Gagal mengirim notifikasi Telegram: {e}")

    def get_wallet_info(self):
        balance = self.w3.eth.get_balance(self.account.address)
        return {
            "address": self.account.address,
            "balance": self.w3.from_hex(balance) if isinstance(balance, str) else self.w3.from_wei(balance, 'ether')
        }

    def check_profitability(self, split_address, token_address):
        try:
            # Get Split Balance
            balance = self.split_main.functions.getSplitBalance(
                Web3.to_checksum_address(split_address),
                Web3.to_checksum_address(token_address)
            ).call()
            
            if balance == 0:
                return False, 0, 0

            # Get Distributor Fee (in scale of 1e6, e.g., 10% = 100,000)
            fee_raw = self.split_main.functions.getDistributorFee(Web3.to_checksum_address(split_address)).call()
            reward = (balance * fee_raw) // 1_000_000
            
            # Estimate Gas
            gas_estimate = self.split_main.functions.distributeToken(
                Web3.to_checksum_address(split_address),
                Web3.to_checksum_address(token_address),
                self.account.address
            ).estimate_gas({'from': self.account.address})
            
            gas_price = self.w3.eth.gas_price
            gas_cost = gas_estimate * gas_price
            
            # Note: This assumes reward is in the same token as gas (ETH) for simplicity.
            # In reality, we need to convert token reward to ETH value.
            if token_address == "0x0000000000000000000000000000000000000000": # ETH
                is_profitable = reward > gas_cost
            else:
                # For ERC20, we'd need a price oracle. For now, let's log it.
                is_profitable = False # Placeholder
                logger.info(f"Token reward detected: {reward} for {token_address}. Oracle needed for profit check.")

            return is_profitable, reward, gas_cost
        except Exception as e:
            logger.error(f"Error checking profitability for {split_address}: {e}")
            return False, 0, 0

    async def execute_distribution(self, split_address, token_address):
        is_profitable, reward, gas_cost = self.check_profitability(split_address, token_address)
        
        if is_profitable:
            logger.info(f"Profit terdeteksi! Reward: {reward}, Gas: {gas_cost}. Mengeksekusi...")
            
            nonce = self.w3.eth.get_transaction_count(self.account.address)
            txn = self.split_main.functions.distributeToken(
                Web3.to_checksum_address(split_address),
                Web3.to_checksum_address(token_address),
                self.account.address
            ).build_transaction({
                'chainId': self.w3.eth.chain_id,
                'gas': 200000, # Buffer gas
                'gasPrice': self.w3.eth.gas_price,
                'nonce': nonce,
            })
            
            signed_txn = self.w3.eth.account.sign_transaction(txn, private_key=PRIVATE_KEY)
            tx_hash = self.w3.eth.send_raw_transaction(signed_txn.rawTransaction)
            
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
            
            if receipt.status == 1:
                wallet = self.get_wallet_info()
                msg = (
                    f"✅ **Distribusi Berhasil!**\n\n"
                    f"🔗 **Chain**: {self.chain_name}\n"
                    f"📄 **Split**: `{split_address}`\n"
                    f"💰 **Reward**: {self.w3.from_wei(reward, 'ether')} ETH\n"
                    f"⛽ **Gas Cost**: {self.w3.from_wei(gas_cost, 'ether')} ETH\n"
                    f"🚀 **TX**: [Etherscan](https://etherscan.io/tx/{tx_hash.hex()})\n\n"
                    f"👛 **Wallet**: `{wallet['address']}`\n"
                    f"📉 **Balance**: {wallet['balance']} ETH"
                )
                await self.send_telegram_notification(msg)
            else:
                logger.error(f"Transaksi gagal: {tx_hash.hex()}")

    async def run_scanner(self, split_addresses, token_addresses):
        logger.info(f"Memulai scanner di {self.chain_name}...")
        while True:
            for split in split_addresses:
                for token in token_addresses:
                    await self.execute_distribution(split, token)
            await asyncio.sleep(60) # Scan setiap 1 menit

from discovery import get_active_splits

async def main():
    import sys
    chain = sys.argv[1] if len(sys.argv) > 1 else "ethereum"
    
    if chain not in RPC_URLS:
        print(f"Chain {chain} tidak didukung.")
        return

    bot = SplitsDistributorBot(chain)
    
    # Ambil daftar split aktif dengan fee > 0
    split_list = await get_active_splits(chain)
    logger.info(f"Ditemukan {len(split_list)} kontrak Split dengan fee di {chain}")
    
    # Token yang akan di-scan (ETH secara default)
    token_list = ["0x0000000000000000000000000000000000000000"]
    
    await bot.run_scanner(split_list, token_list)

if __name__ == "__main__":
    asyncio.run(main())
