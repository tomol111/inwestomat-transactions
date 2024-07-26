import argparse
from datetime import datetime
from decimal import Decimal
import io
from unittest import mock

import pytest

from inwestomat_transactions import (
    BinanceTx,
    build_parser,
    convert_xtb_tx,
    Currency,
    find_pln_prices,
    get_price,
    InwestomatTx,
    read_binance_transactions,
    read_xtb_transactions,
    split_binance_tx_to_inwestomat_txs,
    Ticker,
    TxType,
    write_inwestomat_transactions,
    XtbTx,
)


class Test_parser:
    parser: argparse.ArgumentParser

    @classmethod
    def setup_class(cls) -> None:
        cls.parser = build_parser()

    def test_should_parse_all_positional_arguments(self) -> None:
        args = self.parser.parse_args("binance in.xlsx".split())

        assert args.exchange == "binance"
        assert args.input_path == "in.xlsx"

    def test_should_require_obligatory_arguments(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exc_info:
            self.parser.parse_args([])

        assert exc_info.value.args == (2,)
        error_msg = "error: the following arguments are required: exchange, input_path"
        assert error_msg in capsys.readouterr().err

    def test_should_complain_about_unknown_arguments(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exc_info:
            self.parser.parse_args("binance in.xlsx additional".split())

        assert exc_info.value.args == (2,)
        error_msg = "error: unrecognized arguments: additional"
        assert error_msg in capsys.readouterr().err

    def test_should_ignorecase_for_exchange(self) -> None:
        args = self.parser.parse_args("BinANcE in.xlsx".split())

        assert args.exchange == "binance"


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
            ticker="CURRENCY:BTCPLN",
            currency=Currency.PLN,
            type=TxType.SELL,
            amount=Decimal("0.0001728"),
            price=Decimal("258118"),
            pln_rate=Decimal(1),
            nominal_price=Decimal(1),
            total_pln=Decimal("44.6027904"),
            fee=Decimal(0),
        )
        assert second_tx == InwestomatTx(
            date=date,
            ticker="CURRENCY:ADAPLN",
            currency=Currency.PLN,
            type=TxType.BUY,
            amount=Decimal("23.976"),
            price=Decimal("1.8584496"),
            pln_rate=Decimal(1),
            nominal_price=Decimal(1),
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
            ticker="CURRENCY:ADAPLN",
            currency=Currency.PLN,
            type=TxType.SELL,
            amount=Decimal("24"),
            price=Decimal("1.76500606"),
            pln_rate=Decimal(1),
            nominal_price=Decimal(1),
            total_pln=Decimal("42.36014544"),
            fee=Decimal(0),
        )
        assert second_tx == InwestomatTx(
            date=date,
            ticker="CURRENCY:BTCPLN",
            currency=Currency.PLN,
            type=TxType.BUY,
            amount=Decimal("0.0001815"),
            price=Decimal("233158"),
            pln_rate=Decimal(1),
            nominal_price=Decimal(1),
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

        result = list(read_binance_transactions(file_path))

        assert result == expected


class Test_convert_xtb_tx:
    def test_should_convert_pln_buy_transaction(self) -> None:
        tx = XtbTx(
            id="515820417",
            type=TxType.BUY,
            time=datetime.fromisoformat("2024-03-14 15:55:43+02:00"),
            symbol="DEK.PL",
            asset_amount=Decimal("3"),
            price=Decimal("50.60"),
            currency_amount=Decimal("-151.8"),
        )
        expected = [InwestomatTx(
            date=datetime.fromisoformat("2024-03-14 15:55:43+02:00"),
            ticker="WSE:DEK",
            currency=Currency.PLN,
            type=TxType.BUY,
            amount=Decimal("3"),
            price=Decimal("50.60"),
            pln_rate=Decimal(1),
            nominal_price=Decimal(1),
            total_pln=Decimal("151.8"),
            fee=Decimal("0"),
            comment="ID:515820417",
        )]
        result = convert_xtb_tx(tx)
        assert result == expected

    def test_should_convert_pln_sell_transaction(self) -> None:
        tx = XtbTx(
            id="541449014",
            type=TxType.SELL,
            time=datetime.fromisoformat("2024-05-02 13:03:22+02:00"),
            symbol="CDR.PL",
            asset_amount=Decimal("1"),
            price=Decimal("122.30"),
            currency_amount=Decimal("122.3"),
        )
        expected = [InwestomatTx(
            date=datetime.fromisoformat("2024-05-02 13:03:22+02:00"),
            ticker="WSE:CDR",
            currency=Currency.PLN,
            type=TxType.SELL,
            amount=Decimal("1"),
            price=Decimal("122.30"),
            pln_rate=Decimal(1),
            nominal_price=Decimal(1),
            total_pln=Decimal("122.3"),
            fee=Decimal("0"),
            comment="ID:541449014",
        )]
        result = convert_xtb_tx(tx)
        assert result == expected


class Test_read_xtb_transactions:
    def test_should_load_transactions_from_file(self) -> None:
        file = io.StringIO(
            (
                "ID;Type;Time;Symbol;Comment;Amount\n"
                "541449014;Sprzedaż akcji/ETF;02.05.2024 13:03:22;CDR.PL;"
                "CLOSE BUY 1 @ 122.30;122.3\n"
                "515820417;Zakup akcji/ETF;14.03.2024 15:55:43;DEK.PL;"
                "OPEN BUY 3/4 @ 50.60;-151.8\n"
            ),
            newline=None,
        )
        expected = [
            XtbTx(
                id="541449014",
                type=TxType.SELL,
                time=datetime.fromisoformat("2024-05-02 13:03:22+02:00"),
                symbol="CDR.PL",
                asset_amount=Decimal("1"),
                price=Decimal("122.30"),
                currency_amount=Decimal("122.3"),
            ),
            XtbTx(
                id="515820417",
                type=TxType.BUY,
                time=datetime.fromisoformat("2024-03-14 15:55:43+02:00"),
                symbol="DEK.PL",
                asset_amount=Decimal("3"),
                price=Decimal("50.60"),
                currency_amount=Decimal("-151.8"),
            ),
        ]

        result = list(read_xtb_transactions(file))

        assert result == expected


class Test_write_inwestomat_transactions:
    def test_should_save_transactions_in_csv_format(self) -> None:
        txs = [
            InwestomatTx(
                date=datetime.fromisoformat("2024-05-07 00:47:46+00:00"),
                ticker="CURRENCY:BTCPLN",
                currency=Currency.PLN,
                type=TxType.SELL,
                amount=Decimal("0.00024205"),
                price=Decimal("255380.00000000"),
                pln_rate=Decimal(1),
                nominal_price=Decimal(1),
                total_pln=Decimal("61.8147290000000000"),
                fee=Decimal("0"),
            ),
            InwestomatTx(
                date=datetime.fromisoformat("2024-05-07 00:47:46+00:00"),
                ticker="CURRENCY:ETHPLN",
                currency=Currency.PLN,
                type=TxType.BUY,
                amount=Decimal("0.004995"),
                price=Decimal("12362.9458000000000"),
                pln_rate=Decimal(1),
                nominal_price=Decimal(1),
                total_pln=Decimal("61.8147290000000000"),
                fee=Decimal("0.0618147290000000000"),
            ),
        ]

        expected = (
            ";2024-05-07 02:47:46;CURRENCY:BTCPLN;PLN;;;Sprzedaż;"
            "0,00024205;255380;0;1;1;61,814729;;;\n"
            ";2024-05-07 02:47:46;CURRENCY:ETHPLN;PLN;;;Zakup;"
            "0,004995;12362,9458;0,061814729;1;1;61,814729;;;\n"
        )

        with io.StringIO(newline=None) as buffer:
            write_inwestomat_transactions(buffer, txs)
            result = buffer.getvalue()

        assert result == expected
