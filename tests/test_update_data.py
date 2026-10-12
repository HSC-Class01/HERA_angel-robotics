"""Offline tests for financial calculations; no OpenDART key or network required."""
import importlib.util
import unittest
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("update_data", ROOT / "src" / "update_data.py")
update_data = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(update_data)


class FinancialMetricsTests(unittest.TestCase):
    def make_row(self, year, code, category, report_type, statement, account, amount,
                 cumulative=None, prior=None):
        return {
            "year": year, "report_code": code, "category": category,
            "report_type": report_type, "fs_div": "CFS", "sj_div": statement,
            "account_nm": account, "account_id": account,
            "thstrm_amount": amount, "thstrm_add_amount": cumulative,
            "frmtrm_amount": prior,
        }

    def annual_fixture(self):
        rows = []
        for year, revenue, operating, net, assets, liabilities, equity, ar, inventory, ap in [
            (2023, 1000, 100, 80, 2000, 800, 1200, 180, 100, 80),
            (2024, 1200, 120, 96, 2200, 900, 1300, 220, 120, 90),
        ]:
            for name, value in [
                ("매출액", revenue), ("매출원가", 400), ("매출총이익", revenue - 400),
                ("영업이익(손실)", operating), ("당기순이익(손실)", net),
                ("법인세비용차감전순이익", 100), ("법인세비용", 20),
                ("이자비용", 20), ("감가상각비", 15), ("무형자산상각비", 5),
            ]:
                rows.append(self.make_row(year, "11011", "annual", "사업보고서", "IS", name, value))
            for name, value in [
                ("자산총계", assets), ("유동자산", 800), ("현금및현금성자산", 200),
                ("매출채권", ar), ("재고자산", inventory), ("매입채무", ap),
                ("부채총계", liabilities), ("유동부채", 300), ("자본총계", equity),
                ("단기차입금", 200), ("장기차입금", 100),
            ]:
                rows.append(self.make_row(year, "11011", "annual", "사업보고서", "BS", name, value))
            for name, value in [
                ("영업활동현금흐름", 150), ("투자활동현금흐름", -50),
                ("재무활동현금흐름", -20), ("유형자산의취득", -25), ("무형자산의취득", -5),
            ]:
                rows.append(self.make_row(year, "11011", "annual", "사업보고서", "CF", name, value))
        return pd.DataFrame(rows)

    def test_annual_financial_ratios(self):
        metrics = update_data.build_metrics(self.annual_fixture())
        current = metrics[metrics["year"] == 2024].iloc[0]
        self.assertAlmostEqual(current["revenue_growth_pct"], 20.0, places=3)
        self.assertAlmostEqual(current["debt_to_equity_pct"], 900 / 1300 * 100, places=3)
        self.assertAlmostEqual(current["free_cash_flow"], 120.0, places=3)
        self.assertAlmostEqual(current["ebitda"], 140.0, places=3)
        self.assertAlmostEqual(current["roa_pct"], 96 / 2100 * 100, places=3)
        self.assertAlmostEqual(current["roe_pct"], 96 / 1250 * 100, places=3)
        self.assertAlmostEqual(current["interest_coverage_x"], 6.0, places=3)
        self.assertIsNotNone(current["dso_days"])
        self.assertIsNotNone(current["roic_pct"])

    def test_half_year_uses_cumulative_income_and_cash_flow(self):
        rows = []
        for statement, account, amount, cumulative in [
            ("IS", "매출액", 300, 600),
            ("IS", "영업이익(손실)", 40, 80),
            ("BS", "자산총계", 500, None),
            ("CF", "영업활동현금흐름", 50, 100),
        ]:
            row = self.make_row(2024, "11012", "half_year", "반기보고서", statement, account, amount, cumulative)
            row["fs_div"] = "OFS"
            rows.append(row)
        metrics = update_data.build_metrics(pd.DataFrame(rows))
        current = metrics.iloc[0]
        self.assertEqual(current["revenue"], 600)
        self.assertEqual(current["operating_income"], 80)
        self.assertEqual(current["total_assets"], 500)
        self.assertEqual(current["cash_flow_operations"], 100)


if __name__ == "__main__":
    unittest.main()
