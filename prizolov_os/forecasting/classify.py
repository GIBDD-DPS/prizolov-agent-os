"""Классы активов и горизонтов: статистика точности копится по ним."""

ASSET_CLASSES = {
    "metal": "драгметаллы",
    "fx": "валюты",
    "crypto": "криптовалюты",
    "stock": "акции (мир)",
    "stock_ru": "акции (Мосбиржа)",
    "index": "индексы",
    "commodity": "сырьё",
    "custom": "свои данные",
    "cashflow": "остаток денег",
}
METAL_FUTURES = {"GC=F", "SI=F", "PL=F", "PA=F", "HG=F"}


def asset_class(source: str, symbol: str) -> str:
    symbol = symbol.upper()
    if source == "cbr":
        return "metal" if symbol in {"GOLD", "SILVER", "PLATINUM", "PALLADIUM"} else "fx"
    if source == "moex":
        return "stock_ru"
    if source == "yahoo":
        if symbol in METAL_FUTURES:
            return "metal"
        if symbol.endswith("=X"):
            return "fx"
        if symbol.endswith("=F"):
            return "commodity"
        if symbol.startswith("^"):
            return "index"
        if "-" in symbol and symbol.split("-")[-1] in {"USD", "EUR", "USDT", "RUB", "BTC"}:
            return "crypto"
        return "stock"
    return "custom"


def horizon_bucket(days: int) -> str:
    if days <= 7:
        return "до 7 дн."
    if days <= 30:
        return "до 30 дн."
    if days <= 90:
        return "до 90 дн."
    return "больше 90 дн."
