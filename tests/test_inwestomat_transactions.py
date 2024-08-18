import argparse
from datetime import date as Date, datetime as DateTime
from decimal import Decimal
import io
from unittest import mock

import pytest

from inwestomat_transactions import (
    BinanceTx,
    build_parser,
    convert_xtb_tx,
    convert_xtb_tx_not_pln,
    Currency,
    find_pln_prices,
    get_pln_rate,
    get_price,
    InwestomatTx,
    read_binance_transactions,
    read_xtb_transactions,
    split_binance_tx_to_inwestomat_txs,
    Ticker,
    TxType,
    write_inwestomat_transactions,
    XtbBuySell,
    XtbCosts,
    XtbDepositWithdraw,
    XtbDividendInterest,
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

    def test_should_allow_currency_as_optional_argument(self) -> None:
        args = self.parser.parse_args("xtb in.csv --currency=usd".split())

        assert args.currency == "USD"

    def test_should_make_pln_default_currency(self) -> None:
        args = self.parser.parse_args("xtb in.csv".split())

        assert args.currency == "PLN"


class Test_split_binance_tx_to_inwestomat_txs:
    def test_should_split_buy_transaction(self) -> None:
        date = DateTime.fromisoformat("2024-05-05 00:34:09")
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
        date = DateTime.fromisoformat("2024-05-01 10:17:28")
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
            DateTime.fromisoformat("2024-05-01 10:17:28+00:00"),
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
                date=DateTime.fromisoformat("2024-05-07 00:47:46+00:00"),
                market=("ETH", "BTC"),
                type=TxType.BUY,
                price=Decimal("0.04841"),
                amount=Decimal("0.005"),
                total=Decimal("0.00024205"),
                fee=Decimal("0.000005"),
                fee_coin="ETH",
            ),
            BinanceTx(
                date=DateTime.fromisoformat("2024-05-05 00:34:09+00:00"),
                market=("ADA", "BTC"),
                type=TxType.BUY,
                price=Decimal("0.0000072"),
                amount=Decimal("24"),
                total=Decimal("0.0001728"),
                fee=Decimal("0.024"),
                fee_coin="ADA",
            ),
            BinanceTx(
                date=DateTime.fromisoformat("2024-05-01 10:17:28+00:00"),
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
        tx = XtbBuySell(
            id="515820417",
            type=TxType.BUY,
            time=DateTime.fromisoformat("2024-03-14 15:55:43+02:00"),
            symbol="DEK.PL",
            asset_amount=Decimal("3"),
            price=Decimal("50.60"),
            currency_amount=Decimal("-151.8"),
        )
        expected = [InwestomatTx(
            date=DateTime.fromisoformat("2024-03-14 15:55:43+02:00"),
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
        tx = XtbBuySell(
            id="541449014",
            type=TxType.SELL,
            time=DateTime.fromisoformat("2024-05-02 13:03:22+02:00"),
            symbol="CDR.PL",
            asset_amount=Decimal("1"),
            price=Decimal("122.30"),
            currency_amount=Decimal("122.3"),
        )
        expected = [InwestomatTx(
            date=DateTime.fromisoformat("2024-05-02 13:03:22+02:00"),
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

    def test_should_convert_pln_deposit(self) -> None:
        tx = XtbDepositWithdraw(
            id="522216966",
            type=TxType.DEPOSIT,
            time=DateTime.fromisoformat("2024-03-27 16:25:24+02:00"),
            currency_amount=Decimal("2000"),
        )
        expected = [InwestomatTx(
            date=DateTime.fromisoformat("2024-03-27 16:25:24+02:00"),
            ticker="Gotówka",
            currency=Currency.PLN,
            type=TxType.DEPOSIT,
            amount=Decimal(1),
            price=Decimal(1),
            pln_rate=Decimal(1),
            nominal_price=Decimal(1),
            total_pln=Decimal("2000"),
            fee=Decimal(0),
            comment="ID:522216966",
        )]
        result = convert_xtb_tx(tx)
        assert result == expected

    def test_should_convert_pln_dividend(self) -> None:
        tx = XtbDividendInterest(
            id="390106349",
            time=DateTime.fromisoformat("2023-05-10 12:00:14+02:00"),
            symbol="PCR.PL",
            currency_amount=Decimal("21.57"),
        )
        expected = [InwestomatTx(
            date=DateTime.fromisoformat("2023-05-10 12:00:14+02:00"),
            ticker="WSE:PCR",
            currency=Currency.PLN,
            type=TxType.DIVIDEND_INTEREST,
            amount=Decimal(1),
            price=Decimal(1),
            pln_rate=Decimal(1),
            nominal_price=Decimal(1),
            total_pln=Decimal("21.57"),
            fee=Decimal(0),
            comment="ID:390106349",
        )]
        result = convert_xtb_tx(tx)
        assert result == expected

    def test_should_convert_pln_interest(self) -> None:
        tx = XtbDividendInterest(
            id="510588575",
            time=DateTime.fromisoformat("2024-03-05 11:58:33+02:00"),
            symbol="",
            currency_amount=Decimal("1.05"),
        )
        expected = [InwestomatTx(
            date=DateTime.fromisoformat("2024-03-05 11:58:33+02:00"),
            ticker="Gotówka",
            currency=Currency.PLN,
            type=TxType.DIVIDEND_INTEREST,
            amount=Decimal(1),
            price=Decimal(1),
            pln_rate=Decimal(1),
            nominal_price=Decimal(1),
            total_pln=Decimal("1.05"),
            fee=Decimal(0),
            comment="ID:510588575",
        )]
        result = convert_xtb_tx(tx)
        assert result == expected

    def test_should_convert_pln_dividend_costs(self) -> None:
        tx = XtbCosts(
            id="390106350",
            time=DateTime.fromisoformat("2023-05-10 12:00:14+02:00"),
            symbol="PCR.PL",
            currency_amount=Decimal("-4.1"),
        )
        expected = [InwestomatTx(
            date=DateTime.fromisoformat("2023-05-10 12:00:14+02:00"),
            ticker="WSE:PCR",
            currency=Currency.PLN,
            type=TxType.COSTS,
            amount=Decimal(1),
            price=Decimal(1),
            pln_rate=Decimal(1),
            nominal_price=Decimal(1),
            total_pln=Decimal("4.1"),
            fee=Decimal(0),
            comment="ID:390106350",
        )]
        result = convert_xtb_tx(tx)
        assert result == expected

    def test_should_convert_pln_interest_costs(self) -> None:
        tx = XtbCosts(
            id="510588588",
            time=DateTime.fromisoformat("2024-03-05 11:58:35+02:00"),
            symbol="",
            currency_amount=Decimal("-0.2"),
        )
        expected = [InwestomatTx(
            date=DateTime.fromisoformat("2024-03-05 11:58:35+02:00"),
            ticker="Gotówka",
            currency=Currency.PLN,
            type=TxType.COSTS,
            amount=Decimal(1),
            price=Decimal(1),
            pln_rate=Decimal(1),
            nominal_price=Decimal(1),
            total_pln=Decimal("0.2"),
            fee=Decimal(0),
            comment="ID:510588588",
        )]
        result = convert_xtb_tx(tx)
        assert result == expected

    def test_should_convert_not_pln_buy_transaction(self) -> None:
        tx = XtbBuySell(
            id="532073316",
            type=TxType.BUY,
            time=DateTime.fromisoformat("2024-04-15 15:45:00+02:00"),
            symbol="DTLA.UK",
            asset_amount=Decimal("10"),
            price=Decimal("4.3425"),
            currency_amount=Decimal("-43.43"),
        )
        expected = [
            InwestomatTx(
                date=DateTime.fromisoformat("2024-04-15 15:45:00+02:00"),
                ticker="LON:DTLA",
                currency=Currency.USD,
                type=TxType.BUY,
                amount=Decimal("10"),
                price=Decimal("4.3425"),
                pln_rate=Decimal("3.9983"),
                nominal_price=Decimal(1),
                total_pln=Decimal("173.646169"),
                fee=Decimal("0"),
                comment="ID:532073316",
            ),
            InwestomatTx(
                date=DateTime.fromisoformat("2024-04-15 15:45:00+02:00"),
                ticker="Waluty_USD",
                currency=Currency.USD,
                type=TxType.SELL,
                amount=Decimal("43.43"),
                price=Decimal(1),
                pln_rate=Decimal("3.9983"),
                nominal_price=Decimal(1),
                total_pln=Decimal("173.646169"),
                fee=Decimal("0"),
                comment="ID:532073316",
            ),
        ]
        result = convert_xtb_tx_not_pln(tx, Currency.USD, Decimal("3.9983"))
        assert result == expected

    def test_should_convert_not_pln_sell_transaction(self) -> None:
        tx = XtbBuySell(
            id="512039960",
            type=TxType.SELL,
            time=DateTime.fromisoformat("2024-03-07 09:00:27+02:00"),
            symbol="GDXJ.UK",
            asset_amount=Decimal("2"),
            price=Decimal("31.740"),
            currency_amount=Decimal("63.48"),
        )
        expected = [
            InwestomatTx(
                date=DateTime.fromisoformat("2024-03-07 09:00:27+02:00"),
                ticker="LON:GDXJ",
                currency=Currency.USD,
                type=TxType.SELL,
                amount=Decimal("2"),
                price=Decimal("31.740"),
                pln_rate=Decimal("3.9630"),
                nominal_price=Decimal(1),
                total_pln=Decimal("251.57124"),
                fee=Decimal("0"),
                comment="ID:512039960",
            ),
            InwestomatTx(
                date=DateTime.fromisoformat("2024-03-07 09:00:27+02:00"),
                ticker="Waluty_USD",
                currency=Currency.USD,
                type=TxType.BUY,
                amount=Decimal("63.48"),
                price=Decimal(1),
                pln_rate=Decimal("3.9630"),
                nominal_price=Decimal(1),
                total_pln=Decimal("251.57124"),
                fee=Decimal("0"),
                comment="ID:512039960",
            ),
        ]
        result = convert_xtb_tx_not_pln(tx, Currency.USD, Decimal("3.9630"))
        assert result == expected

    def test_should_convert_not_pln_deposit_transaction(self) -> None:
        tx = XtbDepositWithdraw(
            id="535704358",
            type=TxType.DEPOSIT,
            time=DateTime.fromisoformat("2024-04-22 10:15:41+02:00"),
            currency_amount=Decimal("487.9"),
        )
        expected = [
            InwestomatTx(
                date=DateTime.fromisoformat("2024-04-22 10:15:41+02:00"),
                ticker="Gotówka",
                currency=Currency.PLN,
                type=TxType.DEPOSIT,
                amount=Decimal(1),
                price=Decimal(1),
                pln_rate=Decimal(1),
                nominal_price=Decimal(1),
                total_pln=Decimal("1985.16752"),
                fee=Decimal(0),
                comment="ID:535704358",
            ),
            InwestomatTx(
                date=DateTime.fromisoformat("2024-04-22 10:15:41+02:00"),
                ticker="Waluty_USD",
                currency=Currency.USD,
                type=TxType.BUY,
                amount=Decimal("487.9"),
                price=Decimal(1),
                pln_rate=Decimal("4.0688"),
                nominal_price=Decimal(1),
                total_pln=Decimal("1985.16752"),
                fee=Decimal(0),
                comment="ID:535704358",
            ),
        ]
        result = convert_xtb_tx_not_pln(tx, Currency.USD, Decimal("4.0688"))
        assert result == expected

    def test_should_convert_not_pln_interest(self) -> None:
        tx = XtbDividendInterest(
            id="495802028",
            time=DateTime.fromisoformat("2024-02-01 17:44:44+02:00"),
            symbol="",
            currency_amount=Decimal("0.13"),
        )
        expected = [
            InwestomatTx(
                date=DateTime.fromisoformat("2024-02-01 17:44:44+02:00"),
                ticker="Waluty_EUR",
                currency=Currency.EUR,
                type=TxType.DIVIDEND_INTEREST,
                amount=Decimal(1),
                price=Decimal(1),
                pln_rate=Decimal("4.3434"),
                nominal_price=Decimal(1),
                total_pln=Decimal("0.564642"),
                fee=Decimal(0),
                comment="ID:495802028",
            ),
            InwestomatTx(
                date=DateTime.fromisoformat("2024-02-01 17:44:44+02:00"),
                ticker="Waluty_EUR",
                currency=Currency.EUR,
                type=TxType.BUY,
                amount=Decimal("0.13"),
                price=Decimal(1),
                pln_rate=Decimal("4.3434"),
                nominal_price=Decimal(1),
                total_pln=Decimal("0.564642"),
                fee=Decimal(0),
                comment="ID:495802028",
            ),
        ]
        result = convert_xtb_tx_not_pln(tx, Currency.EUR, Decimal("4.3434"))
        assert result == expected

    def test_should_convert_not_pln_interest_costs(self) -> None:
        tx = XtbCosts(
            id="495802050",
            time=DateTime.fromisoformat("2024-02-01 17:44:45+02:00"),
            symbol="",
            currency_amount=Decimal("-0.02"),
        )
        expected = [
            InwestomatTx(
                date=DateTime.fromisoformat("2024-02-01 17:44:45+02:00"),
                ticker="Gotówka",
                currency=Currency.PLN,
                type=TxType.COSTS,
                amount=Decimal(1),
                price=Decimal(1),
                pln_rate=Decimal("4.3434"),
                nominal_price=Decimal(1),
                total_pln=Decimal("0.086868"),
                fee=Decimal(0),
                comment="ID:495802050",
            ),
            InwestomatTx(
                date=DateTime.fromisoformat("2024-02-01 17:44:45+02:00"),
                ticker="Waluty_EUR",
                currency=Currency.EUR,
                type=TxType.SELL,
                amount=Decimal("0.02"),
                price=Decimal(1),
                pln_rate=Decimal("4.3434"),
                nominal_price=Decimal(1),
                total_pln=Decimal("0.086868"),
                fee=Decimal(0),
                comment="ID:495802050",
            ),
        ]
        result = convert_xtb_tx_not_pln(tx, Currency.EUR, Decimal("4.3434"))
        assert result == expected


@pytest.mark.webtest
class Test_get_pln_rate:
    def test_should_get_mid_pln_rate_for_currency_at_preceding_session(self) -> None:
        result = get_pln_rate(Currency.USD, Date.fromisoformat("2024-03-07"))
        assert result == Decimal("3.9630")  # 2024-03-06

    def test_should_get_pln_rate_for_session_that_was_few_days_earlier(self) -> None:
        result = get_pln_rate(Currency.EUR, Date.fromisoformat("2024-08-12"))
        assert result == Decimal("4.3238")  # 2024-08-09


class Test_read_xtb_transactions:
    def test_should_load_transactions_from_file(self) -> None:
        file = io.StringIO(
            (
                "ID;Type;Time;Symbol;Comment;Amount\n"
                "541449014;Sprzedaż akcji/ETF;02.05.2024 13:03:22;CDR.PL;"
                "CLOSE BUY 1 @ 122.30;122.3\n"
                "515820417;Zakup akcji/ETF;14.03.2024 15:55:43;DEK.PL;"
                "OPEN BUY 3/4 @ 50.60;-151.8\n"
                "522216966;Wpłata;27.03.2024 16:25:24;;"
                "Blik(Payu) deposit, PayU provider transaction "
                "id=6M1GZQ8TG4240327GUEST000P01,"
                "PayU merchant reference id=4418669, id=10832576;2000\n"
                "510588588;Podatek od odsetek od wolnych środków;05.03.2024 11:58:35;;"
                "Free-funds Interest Tax 2024-02;-0.2\n"
                "510588575;Odsetki od wolnych środków;05.03.2024 11:58:33;;"
                "Free-funds Interest 2024-02;1.05\n"
                "390106350;Podatek od dywidend;10.05.2023 12:00:14;PCR.PL;"
                "PCR.PL PLN WHT 19%;-4.1\n"
                "390106349;Dywidenda;10.05.2023 12:00:14;PCR.PL;"
                "PCR.PL PLN 21.5700/ SHR;21.57\n"
            ),
            newline=None,
        )
        expected = [
            XtbBuySell(
                id="541449014",
                type=TxType.SELL,
                time=DateTime.fromisoformat("2024-05-02 13:03:22+02:00"),
                symbol="CDR.PL",
                asset_amount=Decimal("1"),
                price=Decimal("122.30"),
                currency_amount=Decimal("122.3"),
            ),
            XtbBuySell(
                id="515820417",
                type=TxType.BUY,
                time=DateTime.fromisoformat("2024-03-14 15:55:43+02:00"),
                symbol="DEK.PL",
                asset_amount=Decimal("3"),
                price=Decimal("50.60"),
                currency_amount=Decimal("-151.8"),
            ),
            XtbDepositWithdraw(
                id="522216966",
                type=TxType.DEPOSIT,
                time=DateTime.fromisoformat("2024-03-27 16:25:24+02:00"),
                currency_amount=Decimal("2000"),
            ),
            XtbCosts(
                id="510588588",
                time=DateTime.fromisoformat("2024-03-05 11:58:35+02:00"),
                symbol="",
                currency_amount=Decimal("-0.2"),
            ),
            XtbDividendInterest(
                id="510588575",
                time=DateTime.fromisoformat("2024-03-05 11:58:33+02:00"),
                symbol="",
                currency_amount=Decimal("1.05"),
            ),
            XtbCosts(
                id="390106350",
                time=DateTime.fromisoformat("2023-05-10 12:00:14+02:00"),
                symbol="PCR.PL",
                currency_amount=Decimal("-4.1"),
            ),
            XtbDividendInterest(
                id="390106349",
                time=DateTime.fromisoformat("2023-05-10 12:00:14+02:00"),
                symbol="PCR.PL",
                currency_amount=Decimal("21.57"),
            ),
        ]

        result = list(read_xtb_transactions(file))

        assert result == expected


class Test_write_inwestomat_transactions:
    def test_should_save_transactions_in_csv_format(self) -> None:
        txs = [
            InwestomatTx(
                date=DateTime.fromisoformat("2024-05-07 00:47:46+00:00"),
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
                date=DateTime.fromisoformat("2024-05-07 00:47:46+00:00"),
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
