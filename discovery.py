import aiohttp
import logging

logger = logging.getLogger(__name__)

SUBGRAPH_URLS = {
    "ethereum": "https://api.thegraph.com/subgraphs/name/0xsplits/splits-ethereum-mainnet",
    "polygon": "https://api.thegraph.com/subgraphs/name/0xsplits/splits-polygon-mainnet",
    "optimism": "https://api.thegraph.com/subgraphs/name/0xsplits/splits-optimism-mainnet",
    "arbitrum": "https://api.thegraph.com/subgraphs/name/0xsplits/splits-arbitrum-mainnet",
    "base": "https://api.thegraph.com/subgraphs/name/0xsplits/splits-base-mainnet",
}

async def get_active_splits(chain_name):
    url = SUBGRAPH_URLS.get(chain_name)
    if not url:
        return []

    query = """
    {
      splits(first: 100, where: {distributorFee_gt: 0}) {
        id
        distributorFee
      }
    }
    """
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json={'query': query}) as response:
                if response.status == 200:
                    data = await response.json()
                    return [s['id'] for s in data['data']['splits']]
    except Exception as e:
        logger.error(f"Gagal mengambil data dari subgraph {chain_name}: {e}")
    
    return []
