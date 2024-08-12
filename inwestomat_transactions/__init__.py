from __future__ import annotations

import argparse
import csv
import dataclasses
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import enum
import itertools
import re
import sys
from typing import (
    cast,
    Callable,
    Final,
    Iterable,
    Iterator,
    Literal,
    Sequence,
    TextIO,
)

import binance
import openpyxl


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    match Exchange(args.exchange):
        case Exchange.BINANCE:
            convert_binance(args.input_path, sys.stdout)
        case Exchange.XTB:
            with open(args.input_path, "r", newline="") as input_file:
                convert_xtb(input_file, sys.stdout)
        case _:
            raise NotImplementedError(args.exchange)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="inwestomat")
    parser.add_argument(
        "exchange", choices=[x.value for x in Exchange], type=str.lower,
        help="Giełda, kórej transakcje mają być przekonwertowane."
    )
    parser.add_argument("input_path", help="Ściażka do pliku wejściowego.")
    return parser


class Exchange(enum.Enum):
    BINANCE = "binance"
    XTB = "xtb"


Ticker = str
Market = tuple[Ticker, Ticker]


class TxType(enum.Enum):
    BUY = "BUY"
    SELL = "SELL"
    DEPOSIT = "DEPOSIT"
    WITHDRAW = "WITHDRAW"
    DIVIDEND_INTEREST = "DIVIDEND_INTEREST"
    COSTS = "COSTS"
    SPLIT = "SPLIT"

    def to_pl(self) -> str:
        match self:
            case TxType.BUY: return "Zakup"
            case TxType.SELL: return "Sprzedaż"
            case TxType.DEPOSIT: return "Wpłata środków"
            case TxType.WITHDRAW: return "Wypłata środków"
            case TxType.DIVIDEND_INTEREST: return "Dywidenda / Odsetki"
            case TxType.COSTS: return "Koszty"
            case TxType.SPLIT: return "Split"


BuyOrSell = Literal[TxType.BUY, TxType.SELL]
DepositOrWithdraw = Literal[TxType.DEPOSIT, TxType.WITHDRAW]


class Currency(enum.Enum):
    PLN = "PLN"
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    CHF = "CHF"

    @property
    def ticker(self) -> Ticker:
        if self is Currency.PLN:
            return "Gotówka"
        return f"Waluty_{self.value}"


@dataclasses.dataclass(frozen=True)
class BinanceTx:
    date: datetime
    market: Market
    type: BuyOrSell
    amount: Decimal
    price: Decimal
    total: Decimal
    fee: Decimal
    fee_coin: Ticker


@dataclasses.dataclass(frozen=True)
class XtbBuySell:
    id: str
    type: BuyOrSell
    time: datetime
    symbol: Ticker
    asset_amount: Decimal
    price: Decimal
    currency_amount: Decimal


@dataclasses.dataclass(frozen=True)
class XtbDepositWithdraw:
    id: str
    type: DepositOrWithdraw
    time: datetime
    currency_amount: Decimal


@dataclasses.dataclass(frozen=True)
class XtbDividendInterest:
    id: str
    time: datetime
    symbol: Ticker
    currency_amount: Decimal


@dataclasses.dataclass(frozen=True)
class XtbCosts:
    id: str
    time: datetime
    symbol: Ticker
    currency_amount: Decimal


XtbTx = XtbBuySell | XtbDepositWithdraw | XtbDividendInterest | XtbCosts


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
    comment: str = ""


def convert_binance(input_path: str, output_file: TextIO) -> None:
    binance_client = binance.Client()

    binance_txs = read_binance_transactions(input_path)

    inwestomat_txs = itertools.chain.from_iterable(
        convert_binance_tx(tx, binance_client)
        for tx in binance_txs
    )

    write_inwestomat_transactions(output_file, inwestomat_txs)


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
            type=cast(BuyOrSell, TxType(typ)),
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


def convert_xtb(input_file: TextIO, output_file: TextIO) -> None:
    xtb_txs = read_xtb_transactions(input_file)

    inwestomat_txs = itertools.chain.from_iterable(
        convert_xtb_tx(tx)
        for tx in xtb_txs
    )

    write_inwestomat_transactions(output_file, inwestomat_txs)


def convert_xtb_tx(tx: XtbTx) -> list[InwestomatTx]:
    match tx:
        case XtbBuySell():
            inwestomat_tx = InwestomatTx(
                date=tx.time,
                ticker=convert_xtb_ticker(tx.symbol),
                currency=Currency.PLN,
                type=tx.type,
                amount=tx.asset_amount,
                price=tx.price,
                pln_rate=Decimal(1),
                nominal_price=Decimal(1),
                total_pln=abs(tx.currency_amount),
                fee=Decimal(0),
                comment=f"ID:{tx.id}",
            )
        case XtbDepositWithdraw():
            inwestomat_tx = InwestomatTx(
                date=tx.time,
                ticker=Currency.PLN.ticker,
                currency=Currency.PLN,
                type=tx.type,
                amount=Decimal(1),
                price=Decimal(1),
                pln_rate=Decimal(1),
                nominal_price=Decimal(1),
                total_pln=abs(tx.currency_amount),
                fee=Decimal(0),
                comment=f"ID:{tx.id}",
            )
        case XtbDividendInterest():
            inwestomat_tx = InwestomatTx(
                date=tx.time,
                ticker=convert_xtb_ticker(tx.symbol) if tx.symbol else Currency.PLN.ticker,
                currency=Currency.PLN,
                type=TxType.DIVIDEND_INTEREST,
                amount=Decimal(1),
                price=Decimal(1),
                pln_rate=Decimal(1),
                nominal_price=Decimal(1),
                total_pln=tx.currency_amount,
                fee=Decimal(0),
                comment=f"ID:{tx.id}",
            )
        case XtbCosts():
            inwestomat_tx = InwestomatTx(
                date=tx.time,
                ticker=convert_xtb_ticker(tx.symbol) if tx.symbol else Currency.PLN.ticker,
                currency=Currency.PLN,
                type=TxType.COSTS,
                amount=Decimal(1),
                price=Decimal(1),
                pln_rate=Decimal(1),
                nominal_price=Decimal(1),
                total_pln=abs(tx.currency_amount),
                fee=Decimal(0),
                comment=f"ID:{tx.id}",
            )
        case unknown:
            raise NotImplementedError(unknown)

    return [inwestomat_tx]


def convert_xtb_ticker(ticker: Ticker) -> Ticker:
    return "WSE:" + ticker.removesuffix(".PL")


XTB_BUY_SELL_COMMENT_REGEX: Final = re.compile(
    r"""
    (?:OPEN|CLOSE)\ BUY\             # przedrostek
    (?P<asset_amount>\d+(?:\.\d+)?)  # liczba jednostek
    (?:/(?:\d+(?:\.\d+)?))?          # całkowita zlecona liczba jednostek
    \ @\                             # separator
    (?P<price>\d+(?:\.\d+)?)         # cena
    """,
    re.VERBOSE,
)


def read_xtb_transactions(file: TextIO) -> Iterator[XtbTx]:
    row: dict[str, str]
    for row in csv.DictReader(file, delimiter=";"):
        time = datetime.strptime(row["Time"], "%d.%m.%Y %H:%M:%S")\
            .replace(tzinfo=TIMEZONE)
        currency_amount = Decimal(row["Amount"])

        match row["Type"]:
            case "Sprzedaż akcji/ETF" | "Zakup akcji/ETF":
                comment_match = re.fullmatch(XTB_BUY_SELL_COMMENT_REGEX, row["Comment"])
                assert comment_match, "Komentarz nie został rozpoznany"
                yield XtbBuySell(
                    id=row["ID"],
                    type=TxType.BUY if currency_amount < 0 else TxType.SELL,
                    time=time,
                    symbol=row["Symbol"],
                    asset_amount=Decimal(comment_match.group("asset_amount")),
                    price=Decimal(comment_match.group("price")),
                    currency_amount=currency_amount,
                )
            case "Wpłata" | "Wypłata":
                yield XtbDepositWithdraw(
                    id=row["ID"],
                    type=TxType.WITHDRAW if currency_amount < 0 else TxType.DEPOSIT,
                    time=time,
                    currency_amount=currency_amount,
                )
            case "Dywidenda" | "Odsetki od wolnych środków":
                yield XtbDividendInterest(
                    id=row["ID"],
                    time=time,
                    symbol=row["Symbol"],
                    currency_amount=currency_amount,
                )
            case "Podatek od dywidend" | "Podatek od odsetek od wolnych środków":
                yield XtbCosts(
                    id=row["ID"],
                    time=time,
                    symbol=row["Symbol"],
                    currency_amount=currency_amount,
                )
            case _:
                raise NotImplementedError(f"Nieznany typ transakcji: {row['Type']}")


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
            tx.comment,
        ])


def _format_number(num: Decimal) -> str:
    return format(num.normalize(), "f").replace(".", ",")
