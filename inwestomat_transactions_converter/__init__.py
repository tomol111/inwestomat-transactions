from __future__ import annotations

import dataclasses
import datetime
import enum
from decimal import Decimal
from typing import TypeAlias


Ticker: TypeAlias = str


class TxType(enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclasses.dataclass(frozen=True)
class BinanceTx:
    date: datetime.datetime
    market: tuple[Ticker, Ticker]
    type: TxType
    amount: Decimal
    price: Decimal
    total: Decimal
    fee: Decimal
    fee_coin: Ticker


@dataclasses.dataclass(frozen=True)
class InwestomatTx:
    date: datetime.datetime
    ticker: Ticker
    type: TxType
    amount: Decimal
    price: Decimal
    total_pln: Decimal
    fee: Decimal


def convert_binance_tx(
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
