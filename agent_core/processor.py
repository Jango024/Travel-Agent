"""Data processing utilities for the travel agent."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Dict, Iterable, List, Optional

import pandas as pd

from .config import AgentConfig
from .scraper import RawOffer


@dataclass
class ProcessedOffer:
    """Normalised representation of an offer ready for reporting."""

    provider: str
    destination: str
    price: float
    url: str
    nights: int
    board: str
    star_rating: Optional[float] = None
    recommendation_score: Optional[float] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "provider": self.provider,
            "destination": self.destination,
            "price": self.price,
            "url": self.url,
            "nights": self.nights,
            "board": self.board,
            "star_rating": self.star_rating,
            "recommendation_score": self.recommendation_score,
        }


def offers_to_dataframe(offers: Iterable[RawOffer], config: AgentConfig) -> pd.DataFrame:
    """Convert scraped offers into a normalised :class:`~pandas.DataFrame`."""

    records: List[Dict[str, object]] = []
    for offer in offers:
        destination = offer.metadata.get("destination") or config.destinations[0]
        price = offer.price if offer.price is not None else math.nan
        records.append(
            {
                "provider": offer.provider,
                "title": offer.title,
                "destination": destination,
                "price": price,
                "url": offer.url,
                "nights": offer.metadata.get("nights", 7),
                "board": offer.metadata.get("board", "Unbekannt"),
                "star_rating": offer.metadata.get("star_rating"),
                "recommendation_score": offer.metadata.get("recommendation_score")
            }
        )
    return pd.DataFrame.from_records(records)


def filter_by_budget(df: pd.DataFrame, config: AgentConfig) -> pd.DataFrame:
    """Filter offers according to the configured budget."""

    if config.budget is None or df.empty:
        return df
    return df[df["price"].fillna(float("inf")) <= config.budget]


def filter_by_star_rating(df: pd.DataFrame, config: AgentConfig) -> pd.DataFrame:
    """Filter offers according to the minimum star rating."""

    if config.min_star_rating is None or df.empty:
        return df
    return df[df["star_rating"].fillna(0) >= config.min_star_rating]


def filter_by_recommendation(df: pd.DataFrame, config: AgentConfig) -> pd.DataFrame:
    """Filter offers according to the minimum recommendation score."""

    if config.min_recommendation_score is None or df.empty:
        return df
    return df[df["recommendation_score"].fillna(0) >= config.min_recommendation_score]


def deduplicate_offers(df: pd.DataFrame) -> pd.DataFrame:
    """Remove duplicate offers based on provider and title."""

    if df.empty:
        return df
    return df.drop_duplicates(subset=["provider", "title"])  # type: ignore[return-value]


def prepare_offers(offers: Iterable[RawOffer], config: AgentConfig) -> List[ProcessedOffer]:
    """Full processing pipeline returning processed offers."""

    df = offers_to_dataframe(offers, config)
    df = deduplicate_offers(df)
    df = filter_by_budget(df, config)
    df = filter_by_star_rating(df, config)
    df = filter_by_recommendation(df, config)
    if not df.empty:
        df = df.dropna(subset=["price"])
        
    processed: List[ProcessedOffer] = []
    if df.empty:
        return processed

    for row in df.to_dict("records"):
        processed.append(
            ProcessedOffer(
                provider=str(row["provider"]),
                destination=str(row["destination"]),
                price=float(row["price"]),
                url=str(row["url"]),
                nights=int(row.get("nights", 0) or 0),
                board=str(row.get("board", "")),
                star_rating=(
                    float(row["star_rating"])
                    if row.get("star_rating") is not None and not math.isnan(row["star_rating"])
                    else None
                ),
                recommendation_score=(
                    float(row["recommendation_score"])
                    if row.get("recommendation_score") is not None
                    and not math.isnan(row["recommendation_score"])
                    else None
                ),
            )
        )
    return processed


def summarise_offers(offers: List[ProcessedOffer]) -> Dict[str, float]:
    """Return simple statistics across all processed offers."""

    valid_prices = [
        offer.price
        for offer in offers
        if offer.price is not None and not math.isnan(float(offer.price))
    ]
    
    if not valid_prices:
        return {"count": 0, "average_price": 0.0, "min_price": 0.0}

    count = len(valid_prices)
    total = sum(valid_prices)
    minimum = min(valid_prices)

    return {
        "count": count,
        "average_price": float(total / count),
        "min_price": float(minimum),
    }
