"""
polymarket_client.py — Read-only client untuk Polymarket CLOB API.

Untuk versi awal: READ-ONLY (tidak submit order) sampai paper trading
divalidasi. Pakai py-clob-client (official SDK) untuk orderbook data.

Catatan: find_active_5m_market() perlu riset endpoint Gamma API terbaru
sebelum implementasi final — struktur query bisa berubah.
"""
import httpx
import logging

logger = logging.getLogger("polymarket_client")

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


class PolymarketClient:
    def __init__(self, timeout: float = 10.0):
        self.client = httpx.AsyncClient(timeout=timeout)

    async def get_market_odds(self, token_id: str) -> dict:
        """
        Get orderbook + implied probability untuk binary market.
        token_id = token ID dari outcome YES/UP di Polymarket.
        Mid price = implied probability untuk binary market.

        Cara dapat token_id:
          1. Panggil find_active_5m_market() untuk auto-discover
          2. Atau manual dari URL Polymarket (token_id ada di URL)
        """
        resp = await self.client.get(
            f"{CLOB_API}/book",
            params={"token_id": token_id},
        )
        resp.raise_for_status()
        data = resp.json()

        bids = data.get("bids", [])
        asks = data.get("asks", [])

        best_bid = float(bids[0]["price"]) if bids else None
        best_ask = float(asks[0]["price"]) if asks else None
        mid = (best_bid + best_ask) / 2 if best_bid is not None and best_ask is not None else None

        bid_size = sum(float(b.get("size", 0)) for b in bids[:5])
        ask_size = sum(float(a.get("size", 0)) for a in asks[:5])

        return {
            "implied_probability_up": mid,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": round(best_ask - best_bid, 4) if (best_bid is not None and best_ask is not None) else None,
            "bid_depth_5": bid_size,
            "ask_depth_5": ask_size,
            "total_bids": len(bids),
            "total_asks": len(asks),
        }

    async def find_active_markets(
        self, query: str = "Bitcoin", limit: int = 10
    ) -> list[dict]:
        """
        Search active markets via Gamma API.
        Return list of markets matching query with their condition_ids and token_ids.

        NOTE: Struktur response Gamma API bisa berubah — cek
        https://docs.polymarket.com sebelum hardcode field names.
        """
        resp = await self.client.get(
            f"{GAMMA_API}/markets",
            params={
                "active": True,
                "closed": False,
                "limit": limit,
                "_q": query,
            },
        )
        resp.raise_for_status()
        markets = resp.json()

        results = []
        for m in markets:
            tokens = m.get("clobTokenIds", [])
            outcomes = m.get("outcomes", [])
            results.append({
                "condition_id": m.get("conditionId", ""),
                "question": m.get("question", ""),
                "outcomes": outcomes,
                "token_ids": tokens,
                "end_date": m.get("endDate", ""),
                "volume": float(m.get("volume", 0)),
                "liquidity": float(m.get("liquidity", 0)),
            })
        return results

    async def get_event_markets(self, event_id: str) -> list[dict]:
        """Get all markets under a specific event (e.g., 'Will BTC be above X at Y time')."""
        resp = await self.client.get(f"{GAMMA_API}/events/{event_id}")
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self.client.aclose()
