# ABI minimal untuk interaksi dengan Splits Protocol

SPLIT_MAIN_V1_ABI = [
    {
        "inputs": [
            {"internalType": "address", "name": "split", "type": "address"},
            {"internalType": "address", "name": "token", "type": "address"},
            {"internalType": "address", "name": "distributorAddress", "type": "address"}
        ],
        "name": "distributeToken",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "address", "name": "split", "type": "address"},
            {"internalType": "address", "name": "token", "type": "address"}
        ],
        "name": "getSplitBalance",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "address", "name": "split", "type": "address"}],
        "name": "getDistributorFee",
        "outputs": [{"internalType": "uint32", "name": "", "type": "uint32"}],
        "stateMutability": "view",
        "type": "function"
    }
]

ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function"
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function"
    }
]
