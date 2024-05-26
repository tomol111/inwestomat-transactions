import datetime
from decimal import Decimal

from inwestomat_transactions_converter import (
    BinanceTx,
    convert_binance_tx,
    InwestomatTx,
    TxType,
)


class Test_convert_binance_tx:
    def test_should_convert_buy_transaction(self) -> None:
        date = datetime.datetime.fromisoformat("2024-05-05 00:34:09")
        btx = BinanceTx(
            date=date,
            market=("ADA", "BTC"),
            type=TxType.BUY,
            amount=Decimal("24"),
            price=Decimal("0.0000072"),
            total=Decimal("0.0001728"),
            fee=Decimal("0.024"),
            fee_coin=("ADA"),
        )
        pln_prices = {"ADA": Decimal("1.8584496"), "BTC": Decimal("258118")}

        first_tx, second_tx = convert_binance_tx(btx, pln_prices)

        assert first_tx == InwestomatTx(
            date=date,
            ticker="BTC",
            type=TxType.SELL,
            amount=Decimal("0.0001728"),
            price=Decimal("258118"),
            total_pln=Decimal("44.6027904"),
            fee=Decimal(0),
        )
        assert second_tx == InwestomatTx(
            date=date,
            ticker="ADA",
            type=TxType.BUY,
            amount=Decimal("23.976"),
            price=Decimal("1.8584496"),
            total_pln=Decimal("44.6027904"),
            fee=Decimal("0.0446027904"),
        )
