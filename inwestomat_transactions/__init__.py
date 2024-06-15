from __future__ import annotations

import argparse
import csv
import dataclasses
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import enum
import itertools
import sys
from typing import Callable, Final, Iterable, Iterator, Sequence, TextIO, TypeAlias

import binance
import openpyxl


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    convert_binance(args.input_path, args.output_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="inwestomat")
    parser.add_argument("input_path")
    parser.add_argument("output_path", nargs="?")
    return parser


def convert_binance(input_path: str, output_path: str | None) -> None:
    binance_client = binance.Client()

    binance_txs = read_binance_transactions(input_path)

    inwestomat_txs = itertools.chain.from_iterable(
        convert_binance_tx(tx, binance_client)
        for tx in binance_txs
    )

    if output_path is None:
        write_inwestomat_transactions(sys.stdout, inwestomat_txs)
    else:
        with open(output_path, "w", newline="") as output_file:
            write_inwestomat_transactions(output_file, inwestomat_txs)


Ticker: TypeAlias = str
Market: TypeAlias = tuple[Ticker, Ticker]


class TxType(enum.Enum):
    BUY = "BUY"
    SELL = "SELL"

    def to_pl(self) -> str:
        match self:
            case TxType.BUY: return "Zakup"
            case TxType.SELL: return "Sprzedaż"


class Currency(enum.Enum):
    PLN = "PLN"
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    CHF = "CHF"


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
    currency: Currency
    type: TxType
    amount: Decimal
    price: Decimal
    pln_rate: Decimal
    nominal_price: Decimal
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
        ticker=format_cryptocurrency_ticker(sell_ticker),
        currency=Currency.PLN,
        type=TxType.SELL,
        amount=sell_amount,
        price=sell_price,
        pln_rate=Decimal(1),
        nominal_price=Decimal(1),
        total_pln=sell_total_pln,
        fee=sell_fee,
    )
    buy_tx = InwestomatTx(
        date=btx.date,
        ticker=format_cryptocurrency_ticker(buy_ticker),
        currency=Currency.PLN,
        type=TxType.BUY,
        amount=buy_amount,
        price=buy_price,
        pln_rate=Decimal(1),
        nominal_price=Decimal(1),
        total_pln=buy_total_pln,
        fee=buy_fee,
    )
    return [sell_tx, buy_tx]


def format_cryptocurrency_ticker(ticker: Ticker) -> Ticker:
    return f"CURRENCY:{ticker}PLN"


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


def read_binance_transactions(file_path: str) -> Iterator[BinanceTx]:
    worksheet = openpyxl.load_workbook(file_path, read_only=True).active

    max_col = 8
    rows = (
        [worksheet.cell(row, column).value for column in range(1, max_col+1)]
        for row in itertools.count(2)
    )

    for date, market, typ, price, amount, total, fee, fee_coin in rows:
        if date is None:
            break
        yield BinanceTx(
            date=datetime.fromisoformat(date).replace(tzinfo=timezone.utc),
            market=identify_binance_market_assets(market),
            type=TxType(typ),
            price=Decimal(price),
            amount=Decimal(amount),
            total=Decimal(total),
            fee=Decimal(fee),
            fee_coin=fee_coin,
        )


BINANCE_QUOTE_ASSETS: Final = (
    "USDT", "BTC", "TRY", "FDUSD", "USDC", "ETH", "BNB", "EUR", "TUSD", "BRL", "JPY",
    "DAI", "UAH", "PLN", "RON", "ZAR", "MXN", "ARS", "XRP", "TRX", "DOGE", "CZK", "IDRT",
)


def identify_binance_market_assets(market: str) -> Market:
    for quote_asset in BINANCE_QUOTE_ASSETS:
        if market.endswith(quote_asset):
            return (market.removesuffix(quote_asset), quote_asset)
    raise NotImplementedError("Unkown quote asset")


TIMEZONE: Final = timezone(timedelta(hours=2))


def write_inwestomat_transactions(file: TextIO, txs: Iterable[InwestomatTx]) -> None:

    writer = csv.writer(file, delimiter=";")
    for tx in txs:
        writer.writerow([
            # Konto
            "",
            # Data
            tx.date.astimezone(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S"),
            # Ticker
            tx.ticker,
            # Waluta
            tx.currency.value,
            # Nazwa
            "",
            # Klasa aktywów
            "",
            # Rodzaj transakcji
            tx.type.to_pl(),
            # Liczba
            _format_number(tx.amount),
            # Cena
            _format_number(tx.price),
            # Prowizje
            _format_number(tx.fee),
            # Kurs PLN transakcji
            _format_number(tx.pln_rate),
            # Cena nominalna
            _format_number(tx.nominal_price),
            # Total PLN
            _format_number(tx.total_pln),
            # Klucz
            "",
            # XIRR
            "",
            # Komantarz
            "",
        ])


def _format_number(num: Decimal) -> str:
    return format(num.normalize(), "f").replace(".", ",")
