"""Configuration helpers for the travel agent core logic."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional

_DATE_FORMATS = ["%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d.%m.%y"]


@dataclass
class AgentConfig:
    """Canonical configuration used by the agent workflow."""

    destinations: List[str]
    departure_date: Optional[date] = None
    return_date: Optional[date] = None
    travellers: int = 2
    budget: Optional[float] = None
    origin: Optional[str] = None
    accommodation_types: List[str] = field(default_factory=list)
    board_types: List[str] = field(default_factory=list)
    notes: str = ""
    raw_request: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable version of the configuration."""

        return {
            "destinations": self.destinations,
            diff --git a/agent_core/config.py b/agent_core/config.py
index ded0c20f5a7c36faa5edac15464aacbb3dca9fcb..728d71f8891659101ee8d6c523843085c36d305c 100644
--- a/agent_core/config.py
+++ b/agent_core/config.py
@@ -32,51 +32,53 @@ class AgentConfig:
             "departure_date": self.departure_date.isoformat() if self.departure_date else None,
             "return_date": self.return_date.isoformat() if self.return_date else None,
             "travellers": self.travellers,
             "budget": self.budget,
             "origin": self.origin,
             "accommodation_types": self.accommodation_types,
             "board_types": self.board_types,
             "notes": self.notes,
         }
 
 
 def _parse_date(value: str | None) -> Optional[date]:
     if not value:
         return None
     for fmt in _DATE_FORMATS:
         try:
             return datetime.strptime(value, fmt).date()
         except ValueError:
             continue
     return None
 
 
 def _parse_float(value: str | None) -> Optional[float]:
     if not value:
         return None
-    cleaned = value.replace("€", "").replace(",", ".").strip()
+    cleaned = value.replace("€", "").strip()
+    cleaned = re.sub(r"(?<=\d)\.(?=\d{3}(?:\D|$))", "", cleaned)
+    cleaned = cleaned.replace(",", ".")
     try:
         return float(cleaned)
     except ValueError:
         return None
 
 
 def _ensure_list(value: str | Iterable[str] | None) -> List[str]:
     if value is None:
         return []
     if isinstance(value, str):
         if not value:
             return []
         return [item.strip() for item in value.split(",") if item.strip()]
     return [item for item in value if item]
 
 
 def create_config_from_form(form_data: Mapping[str, Any]) -> AgentConfig:
     """Create a configuration object from an HTML form payload."""
 
     destinations = _ensure_list(form_data.get("destinations"))
     if not destinations:
         destination_value = form_data.get("destination") or form_data.get("destinations") or ""
         destinations = _ensure_list(destination_value)
 
     accommodation_types = _ensure_list(form_data.get("accommodation"))
    board_types = _ensure_list(form_data.get("board"))

    config = AgentConfig(
        destinations=destinations,
        departure_date=_parse_date(form_data.get("departure_date")),
        return_date=_parse_date(form_data.get("return_date")),
        travellers=int(form_data.get("travellers") or 2),
        budget=_parse_float(form_data.get("budget")),
        origin=(form_data.get("origin") or None),
        accommodation_types=accommodation_types,
        board_types=board_types,
        notes=str(form_data.get("notes") or ""),
        raw_request=dict(form_data),
    )
    return config


_BUDGET_PATTERN = re.compile(r"(?P<amount>\d+[\d.,]*)\s?(?:€|eur|euro|euros)?", re.IGNORECASE)
_TRAVELLER_PATTERN = re.compile(r"(?P<count>\d+)\s?(?:personen|people|travellers|reisende|adults)", re.IGNORECASE)
_DATE_RANGE_PATTERN = re.compile(
    r"(?P<start>\d{1,2}[./]\d{1,2}[./]\d{2,4})\s*(?:bis|-|to|–|—)\s*(?P<end>\d{1,2}[./]\d{1,2}[./]\d{2,4})",
    re.IGNORECASE,
)

_DESTINATION_STOP_WORDS = {
    "ich",
    "wir",
    "budget",
    "suche",
    "plane",
    "planen",
    "brauche",
    "bitte",
    "hallo",
    "urlaub",
    "reise",
    "looking",
    "searching",
    "need",
}


def create_config_from_text(message: str) -> AgentConfig:
    """Create a configuration from a free-form text query.

    This parser is intentionally simple but captures the most common
    information mentioned in short chat messages.
    """

    destinations: List[str] = []
    budget: Optional[float] = None
    travellers = 2
    departure_date: Optional[date] = None
    return_date: Optional[date] = None

    message_lower = message.lower()

    for match in _DATE_RANGE_PATTERN.finditer(message_lower):
        departure_date = _parse_date(match.group("start"))
        return_date = _parse_date(match.group("end"))
        break

    if not departure_date:
        # look for single date expressions
        single_date_match = re.search(r"\d{1,2}[./]\d{1,2}[./]\d{2,4}", message_lower)
        if single_date_match:
            departure_date = _parse_date(single_date_match.group())

    budget_match = _BUDGET_PATTERN.search(message_lower)
    if budget_match:
        budget = _parse_float(budget_match.group("amount"))

    traveller_match = _TRAVELLER_PATTERN.search(message_lower)
    if traveller_match:
        travellers = int(traveller_match.group("count"))

    # very naive destination extraction: look for words after "nach"/"to"
    destination_keywords = re.findall(r"(?:nach|to|richtung)\s+([a-zäöüß\-\s]{3,})", message_lower)
    for keyword in destination_keywords:
        destinations.append(keyword.strip().title())

    if not destinations:
        # fallback: pick capitalised words as potential cities
        for token in re.findall(r"[A-ZÄÖÜ][a-zäöüß]+", message):
            if token.lower() not in {"Ich", "Wir", "Budget"}:
                destinations.append(token)

    if not destinations:
        destinations = ["Unbestimmt"]

    config = AgentConfig(
        destinations=destinations,
        departure_date=departure_date,
        return_date=return_date,
        travellers=travellers,
        budget=budget,
        notes=message,
        raw_request={"message": message},
    )
    return config


def create_config(data: Mapping[str, Any] | str) -> AgentConfig:
    """Unified helper that accepts either dict-like data or raw text."""

    if isinstance(data, Mapping):
        return create_config_from_form(data)
    if isinstance(data, str):
        return create_config_from_text(data)
    raise TypeError("Unsupported configuration payload type")
