import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Config
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Wallet Config
PRIVATE_KEY = os.getenv("PRIVATE_KEY")

# RPC Config (Contoh untuk beberapa chain)
RPC_URLS = {
    "ethereum": os.getenv("ETH_RPC_URL", "https://eth-mainnet.g.alchemy.com/v2/your-api-key"),
    "optimism": os.getenv("OP_RPC_URL", "https://opt-mainnet.g.alchemy.com/v2/your-api-key"),
    "base": os.getenv("BASE_RPC_URL", "https://base-mainnet.g.alchemy.com/v2/your-api-key"),
    "polygon": os.getenv("POLYGON_RPC_URL", "https://polygon-mainnet.g.alchemy.com/v2/your-api-key"),
    "arbitrum": os.getenv("ARB_RPC_URL", "https://arb-mainnet.g.alchemy.com/v2/your-api-key"),
}

# Splits Protocol Addresses (V1 SplitMain)
SPLIT_MAIN_ADDRESSES = {
    "ethereum": "0x2ed6c4b5da6378c7897ac67ba9e43102feb694ee",
    "optimism": "0x2ed6c4b5da6378c7897ac67ba9e43102feb694ee",
    "base": "0x2ed6c4b5da6378c7897ac67ba9e43102feb694ee",
    "polygon": "0x2ed6c4b5da6378c7897ac67ba9e43102feb694ee",
    "arbitrum": "0x2ed6c4b5da6378c7897ac67ba9e43102feb694ee",
}

# Splits Protocol V2 Addresses (Warehouse)
WAREHOUSE_ADDRESSES = {
    "ethereum": "0x2ed6c4b5da6378c7897ac67ba9e43102feb694ee", # Perlu verifikasi alamat V2 yang tepat
}
