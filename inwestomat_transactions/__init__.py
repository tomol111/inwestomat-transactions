from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
import enum
from decimal import Decimal
from typing import Callable, Final, Iterator, TypeAlias

import binance
import openpyxl


Ticker: TypeAlias = str
Market: TypeAlias = tuple[Ticker, Ticker]


class TxType(enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclasses.dataclass(frozen=True)
class BinanceTx:
    date: datetime
    market: Market
    type: TxType
    amount: Decimal
    price: Decimal
    total: Decimal
    fee: Decimal
    fee_coin: Ticker


@dataclasses.dataclass(frozen=True)
class InwestomatTx:
    date: datetime
    ticker: Ticker
    type: TxType
    amount: Decimal
    price: Decimal
    total_pln: Decimal
    fee: Decimal


def convert_binance_tx(btx: BinanceTx, client: binance.Client) -> list[InwestomatTx]:
    pln_prices = find_pln_prices(
        lambda market: get_price(client, btx.date, market),
        btx.market,
        btx.price,
    )
    result = split_binance_tx_to_inwestomat_txs(btx, pln_prices)
    return result


def split_binance_tx_to_inwestomat_txs(
    btx: BinanceTx, pln_prices: dict[Ticker, Decimal]
) -> list[InwestomatTx]:
    match btx.type:
        case TxType.BUY:
            buy_ticker, sell_ticker = btx.market
            sell_amount = btx.total
            buy_amount = btx.amount
        case TxType.SELL:
            sell_ticker, buy_ticker = btx.market
            sell_amount = btx.amount
            buy_amount = btx.total

    sell_price = pln_prices[sell_ticker]
    buy_price = pln_prices[buy_ticker]

    sell_total_pln = sell_amount * sell_price
    buy_total_pln = buy_amount * buy_price

    sell_fee = buy_fee = Decimal()
    if btx.fee_coin == buy_ticker:
        buy_amount -= btx.fee
        buy_fee = btx.fee * buy_price

    sell_tx = InwestomatTx(
        date=btx.date,
        ticker=sell_ticker,
        type=TxType.SELL,
        amount=sell_amount,
        price=sell_price,
        total_pln=sell_total_pln,
        fee=sell_fee,
    )
    buy_tx = InwestomatTx(
        date=btx.date,
        ticker=buy_ticker,
        type=TxType.BUY,
        amount=buy_amount,
        price=buy_price,
        total_pln=buy_total_pln,
        fee=buy_fee,
    )
    return [sell_tx, buy_tx]


class KLineValue(enum.Enum):
    OPEN_TIME = 0
    OPEN = 1
    HIGH = 2
    LOW = 3
    CLOSE = 4
    VOLUME = 5
    CLOSE_TIME = 6
    QUOTE_ASSET_VOLUME = 7
    NUMER_OF_TRADES = 8
    TAKER_BUY_BASE_ASSET_VOLUME = 9
    TAKER_BUY_QUOTE_ASSET_VOLUME = 10
    IGNORE = 11

    def __index__(self) -> int:
        return self.value


def get_price(client: binance.Client, date: datetime, market: Market) -> Decimal:
    assert date.tzinfo
    assert not date.microsecond
    start = int(date.timestamp() * 1000)
    end = start + 1
    klines: list[list] = client.get_historical_klines("".join(market), "1s", start, end)
    return Decimal(klines[0][KLineValue.CLOSE])


def find_pln_prices(
    get_price: Callable[[Market], Decimal], market: Market, price: Decimal
) -> dict[Ticker, Decimal]:
    base_asset, quote_asset = market
    quote_asset_in_pln = get_price((quote_asset, "PLN"))
    base_asset_in_pln = price * quote_asset_in_pln
    return {
        base_asset: base_asset_in_pln,
        quote_asset: quote_asset_in_pln,
    }


def read_binance_transactions(file_path: str) -> list[BinanceTx]:
    data: Iterator = openpyxl.load_workbook(file_path, read_only=True).active.values

    next(data)  # usuń nagłówek z nazwami

    result = list[BinanceTx]()
    for date, market, typ, price, amount, total, fee, fee_coin in data:
        if date is None:
            break
        result.append(BinanceTx(
            date=datetime.fromisoformat(date).replace(tzinfo=timezone.utc),
            market=identify_binance_market_assets(market),
            type=TxType(typ),
            price=Decimal(price),
            amount=Decimal(amount),
            total=Decimal(total),
            fee=Decimal(fee),
            fee_coin=fee_coin,
        ))

    return result


BINANCE_QUOTE_ASSETS: Final = (
    "USDT", "BTC", "TRY", "FDUSD", "USDC", "ETH", "BNB", "EUR", "TUSD", "BRL", "JPY",
    "DAI", "UAH", "PLN", "RON", "ZAR", "MXN", "ARS", "XRP", "TRX", "DOGE", "CZK", "IDRT",
)


def identify_binance_market_assets(market: str) -> Market:
    for quote_asset in BINANCE_QUOTE_ASSETS:
        if market.endswith(quote_asset):
            return (market.removesuffix(quote_asset), quote_asset)
    raise NotImplementedError("Unkown quote asset")
