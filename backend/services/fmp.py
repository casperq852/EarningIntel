"""
Financial Modeling Prep (FMP) async API client.
Base URL: https://financialmodelingprep.com/api/v3
Rate limit awareness: 300 req/min → ~0.2s sleep between bulk calls.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"
FMP_STABLE_URL = "https://financialmodelingprep.com/stable"
_FMP_API_KEY = os.getenv("FMP_API_KEY", "")


class FMPClient:
    """Async FMP API client."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or _FMP_API_KEY
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=FMP_BASE_URL,
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        client = await self._get_client()
        merged_params: Dict[str, Any] = {"apikey": self.api_key}
        if params:
            merged_params.update(params)
        response = await client.get(path, params=merged_params)
        response.raise_for_status()
        return response.json()

    async def _get_stable(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """GET against the /stable endpoint (newer FMP API)."""
        merged_params: Dict[str, Any] = {"apikey": self.api_key}
        if params:
            merged_params.update(params)
        async with httpx.AsyncClient(base_url=FMP_STABLE_URL, timeout=30.0) as client:
            response = await client.get(path, params=merged_params)
            response.raise_for_status()
            return response.json()

    # -----------------------------------------------------------------------
    # Public API methods
    # -----------------------------------------------------------------------

    async def get_earnings_calendar(
        self,
        from_date: str,
        to_date: str,
    ) -> List[Dict[str, Any]]:
        """
        Fetch upcoming earnings calendar.
        Tries /stable/earnings-calendar first (current endpoint), falls back to /api/v3.
        """
        # Try stable endpoint first
        try:
            data = await self._get_stable(
                "/earnings-calendar",
                params={"from": from_date, "to": to_date},
            )
            if isinstance(data, list) and data:
                return data
        except Exception:
            pass
        # Fall back to v3
        try:
            data = await self._get(
                "/earning_calendar",
                params={"from": from_date, "to": to_date},
            )
            return data if isinstance(data, list) else []
        except Exception:
            return []

    async def get_historical_calendar(
        self, fmp_symbol: str
    ) -> List[Dict[str, Any]]:
        """
        Fetch historical earnings dates for a symbol.
        GET /historical/earning_calendar/{symbol}
        """
        await asyncio.sleep(0.2)
        data = await self._get(f"/historical/earning_calendar/{fmp_symbol}")
        return data if isinstance(data, list) else []

    async def get_earnings_surprises(
        self, fmp_symbol: str
    ) -> List[Dict[str, Any]]:
        """
        Fetch earnings surprises (actual vs estimate).
        GET /earnings-surprises/{symbol}
        """
        await asyncio.sleep(0.2)
        data = await self._get(f"/earnings-surprises/{fmp_symbol}")
        return data if isinstance(data, list) else []

    async def get_analyst_estimates(
        self, fmp_symbol: str
    ) -> List[Dict[str, Any]]:
        """
        Fetch analyst consensus estimates.
        GET /analyst-estimates/{symbol}
        """
        await asyncio.sleep(0.2)
        data = await self._get(f"/analyst-estimates/{fmp_symbol}")
        return data if isinstance(data, list) else []

    async def get_income_statement(
        self, fmp_symbol: str
    ) -> List[Dict[str, Any]]:
        """
        Fetch quarterly income statements (last 8 quarters).
        GET /income-statement/{symbol}?period=quarter&limit=8
        """
        await asyncio.sleep(0.2)
        data = await self._get(
            f"/income-statement/{fmp_symbol}",
            params={"period": "quarter", "limit": 8},
        )
        return data if isinstance(data, list) else []

    async def get_transcript(
        self,
        fmp_symbol: str,
        quarter: int,
        year: int,
    ) -> List[Dict[str, Any]]:
        """
        Fetch earnings call transcript.
        GET /earning_call_transcript/{symbol}?quarter={Q}&year={YYYY}
        """
        await asyncio.sleep(0.2)
        data = await self._get(
            f"/earning_call_transcript/{fmp_symbol}",
            params={"quarter": quarter, "year": year},
        )
        return data if isinstance(data, list) else []

    async def search_symbol(
        self,
        query: str,
        exchange: str = "",
    ) -> List[Dict[str, Any]]:
        """
        Search for ticker symbols.
        GET /search?query={}&exchange={}
        """
        params: Dict[str, Any] = {"query": query, "limit": 10}
        if exchange:
            params["exchange"] = exchange
        data = await self._get("/search", params=params)
        return data if isinstance(data, list) else []

    # -----------------------------------------------------------------------
    # Convenience helpers
    # -----------------------------------------------------------------------

    async def get_latest_earnings_data(
        self, fmp_symbol: str
    ) -> Dict[str, Any]:
        """
        Fetch a bundle of data needed for brief synthesis:
        income statements, analyst estimates, surprises.
        """
        income = await self.get_income_statement(fmp_symbol)
        estimates = await self.get_analyst_estimates(fmp_symbol)
        surprises = await self.get_earnings_surprises(fmp_symbol)

        latest_income = income[0] if income else {}
        latest_estimate = estimates[0] if estimates else {}
        latest_surprise = surprises[0] if surprises else {}

        return {
            "income_statements": income,
            "analyst_estimates": estimates,
            "earnings_surprises": surprises,
            "latest_income": latest_income,
            "latest_estimate": latest_estimate,
            "latest_surprise": latest_surprise,
        }

    async def get_latest_transcript(
        self, fmp_symbol: str
    ) -> Optional[str]:
        """
        Attempt to get the most recent transcript.
        Tries the current and previous quarter.
        Returns the transcript content string or None.
        """
        from datetime import datetime

        now = datetime.utcnow()
        year = now.year
        month = now.month

        # Determine current and previous fiscal quarter
        current_q = (month - 1) // 3 + 1
        prev_q = current_q - 1 if current_q > 1 else 4
        prev_year = year if current_q > 1 else year - 1

        for q, y in [(current_q, year), (prev_q, prev_year), (prev_q - 1 if prev_q > 1 else 4, prev_year)]:
            if q < 1:
                q = 4
                y -= 1
            try:
                result = await self.get_transcript(fmp_symbol, q, y)
                if result and isinstance(result, list) and result[0].get("content"):
                    return result[0]["content"]
            except Exception:
                pass
        return None


# Module-level singleton
fmp_client = FMPClient()
