"""Conservative heat-exchanger type standardization.

The raw source value is always retained. Ambiguous FTS values deliberately do
not receive a standard code until their business meaning is confirmed.
"""

from __future__ import annotations

import re
from typing import NamedTuple


class ExchangerTypeMapping(NamedTuple):
    code: str | None
    name: str | None
    raw: str | None
    status: str


TYPE_NAMES = {
    "ST": "Shell & Tube",
    "PL": "Plate",
    "FT": "Finned Tube",
    "ETC": "기타",
}


def standardize_exchanger_type(value: object) -> ExchangerTypeMapping:
    raw = str(value).strip() if value is not None else ""
    if not raw:
        return ExchangerTypeMapping("ETC", TYPE_NAMES["ETC"], None, "UNMAPPED")

    upper = raw.upper()
    compact = re.sub(r"[^A-Z0-9]", "", upper)

    # FTS is intentionally unresolved. Check it before FIN TUBE aliases so it
    # cannot be inferred as a finned-tube code by accident.
    if re.search(r"(^|[^A-Z0-9])FTS([^A-Z0-9]|$)", upper):
        return ExchangerTypeMapping(None, None, raw, "REVIEW")

    if (
        "SHELLTUBE" in compact
        or "SHELLANDTUBE" in compact
        or "TUBESHELL" in compact
        or upper.strip() == "S&T"
    ):
        return ExchangerTypeMapping("ST", TYPE_NAMES["ST"], raw, "MAPPED")
    if "PLATE" in compact or compact == "PHE":
        return ExchangerTypeMapping("PL", TYPE_NAMES["PL"], raw, "MAPPED")
    if "FINTUBE" in compact or "FINNEDTUBE" in compact:
        return ExchangerTypeMapping("FT", TYPE_NAMES["FT"], raw, "MAPPED")
    return ExchangerTypeMapping("ETC", TYPE_NAMES["ETC"], raw, "UNMAPPED")
