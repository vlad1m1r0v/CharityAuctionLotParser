from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Lot:
    number: int
    title: str
    start_price: int
    link: str
    message_id: int


@dataclass
class Bid:
    user_id: int
    first_name: str
    last_name: Optional[str]
    username: Optional[str]
    amount: int
    comment: str
    timestamp: datetime
    message_id: int

    @property
    def full_name(self) -> str:
        parts = [self.first_name, self.last_name]
        return " ".join(part for part in parts if part)


@dataclass
class LotResult:
    lot: Lot
    winner: Optional[Bid]
    comment_count: int = 0
    bids: list[Bid] = field(default_factory=list)
