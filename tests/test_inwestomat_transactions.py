from datetime import datetime
from decimal import Decimal
from unittest import mock

from inwestomat_transactions import (
    BinanceTx,
    split_binance_tx_to_inwestomat_txs,
    find_pln_prices,
    get_price,
    InwestomatTx,
    read_binance_transactions,
    Ticker,
    TxType,
)


class Test_split_binance_tx_to_inwestomat_txs:
    def test_should_split_buy_transaction(self) -> None:
        date = datetime.fromisoformat("2024-05-05 00:34:09")
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

        first_tx, second_tx = split_binance_tx_to_inwestomat_txs(btx, pln_prices)

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

    def test_should_split_sell_transaction(self) -> None:
        date = datetime.fromisoformat("2024-05-01 10:17:28")
        btx = BinanceTx(
            date=date,
            market=("ADA", "BTC"),
            type=TxType.SELL,
            amount=Decimal("24"),
            price=Decimal("0.00000757"),
            total=Decimal("0.00018168"),
            fee=Decimal("0.00000018"),
            fee_coin=("BTC"),
        )
        pln_prices = {"ADA": Decimal("1.76500606"), "BTC": Decimal("233158")}

        first_tx, second_tx = split_binance_tx_to_inwestomat_txs(btx, pln_prices)

        assert first_tx == InwestomatTx(
            date=date,
            ticker="ADA",
            type=TxType.SELL,
            amount=Decimal("24"),
            price=Decimal("1.76500606"),
            total_pln=Decimal("42.36014544"),
            fee=Decimal(0),
        )
        assert second_tx == InwestomatTx(
            date=date,
            ticker="BTC",
            type=TxType.BUY,
            amount=Decimal("0.0001815"),
            price=Decimal("233158"),
            total_pln=Decimal("42.36014544"),
            fee=Decimal("0.04196844"),
        )


class Test_get_price:
    def test_should_return_price_of_currency(self) -> None:
        def fake_get_historical_klines(
            market: str, interval: str, start: int, end: int
        ) -> list[list]:
            assert market == "BTCPLN"
            assert interval == "1s"
            assert start == 1714558648000
            assert end == 1714558648001
            return [[
                1714558648000, "233158.00000000", "233158.00000000", "233158.00000000",
                "233158.00000000", "0.00000000", 1714558648999, "0.00000000", 0,
                "0.00000000", "0.00000000", "0"
            ]]
        mock_client = mock.Mock()
        mock_client.get_historical_klines.side_effect = fake_get_historical_klines

        price = get_price(
            mock_client,
            datetime.fromisoformat("2024-05-01 10:17:28+00:00"),
            ("BTC", "PLN"),
        )

        assert price == Decimal("233158")


class Test_find_pln_prices:
    def test_should_return_prices_in_pln(self) -> None:
        def fake_get_price(market: tuple[Ticker, Ticker]) -> Decimal:
            assert market == ("BTC", "PLN")
            return Decimal("233158")

        result = find_pln_prices(
            fake_get_price,
            ("ADA", "BTC"),
            Decimal("0.00000757"),
        )

        assert result == {"ADA": Decimal("1.76500606"), "BTC": Decimal("233158")}


class Test_read_binance_transactions:
    def test_should_(self) -> None:
        file_path = "tests/binance_transactions.xlsx"
        expected = [
            BinanceTx(
                date=datetime.fromisoformat("2024-05-07 00:47:46+00:00"),
                market=("ETH", "BTC"),
                type=TxType.BUY,
                price=Decimal("0.04841"),
                amount=Decimal("0.005"),
                total=Decimal("0.00024205"),
                fee=Decimal("0.000005"),
                fee_coin="ETH",
            ),
            BinanceTx(
                date=datetime.fromisoformat("2024-05-05 00:34:09+00:00"),
                market=("ADA", "BTC"),
                type=TxType.BUY,
                price=Decimal("0.0000072"),
                amount=Decimal("24"),
                total=Decimal("0.0001728"),
                fee=Decimal("0.024"),
                fee_coin="ADA",
            ),
            BinanceTx(
                date=datetime.fromisoformat("2024-05-01 10:17:28+00:00"),
                market=("ADA", "BTC"),
                type=TxType.SELL,
                price=Decimal("0.00000757"),
                amount=Decimal("24"),
                total=Decimal("0.00018168"),
                fee=Decimal("0.00000018"),
                fee_coin="BTC",
            ),
        ]

        result = read_binance_transactions(file_path)

        assert result == expected
