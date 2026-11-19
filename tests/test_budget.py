"""Test budget-cli (unittest, stdlib saja).

Semua test memakai ledger sementara (tempfile) supaya tidak menyentuh
ledger asli di ~/.budget/ledger.json.
"""

import csv
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal
from pathlib import Path

# Izinkan `import budget` saat test dijalankan dari root repo.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from budget import ledger as lg
from budget.cli import main


class BudgetTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Path(self.tmp.name) / "ledger.json"
        self.data = lg.empty_ledger()

    def tearDown(self):
        self.tmp.cleanup()

    # -- helper -----------------------------------------------------------
    def add(self, type_, amount, category, date="2026-11-15", note=""):
        return lg.add_transaction(
            self.data, type_=type_, amount=Decimal(str(amount)),
            category=category, date_str=date, note=note,
        )

    def run_cli(self, *argv):
        """Jalankan CLI dengan ledger sementara; kembalikan (kode, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--ledger", str(self.ledger), *argv])
        return code, out.getvalue(), err.getvalue()

    # -- add / list round-trip --------------------------------------------
    def test_add_list_round_trip(self):
        tx = self.add("expense", "50000", "makan", note="nasi padang")
        lg.save_ledger(self.ledger, self.data)
        loaded = lg.load_ledger(self.ledger)
        self.assertEqual(len(loaded["transactions"]), 1)
        back = loaded["transactions"][0]
        self.assertEqual(back["id"], tx["id"])
        self.assertEqual(back["date"], "2026-11-15")
        self.assertEqual(back["type"], "expense")
        self.assertEqual(back["category"], "makan")
        self.assertEqual(Decimal(str(back["amount"])), Decimal("50000"))
        self.assertEqual(back["note"], "nasi padang")

    def test_list_newest_first_and_filters(self):
        self.add("expense", "10000", "makan", date="2026-11-10")
        self.add("income", "5000000", "gaji", date="2026-11-01")
        self.add("expense", "20000", "transport", date="2026-11-20")
        rows = lg.list_transactions(self.data)
        self.assertEqual([r["date"] for r in rows],
                         ["2026-11-20", "2026-11-10", "2026-11-01"])
        self.assertEqual(len(lg.list_transactions(self.data, month="2026-11")), 3)
        self.assertEqual(len(lg.list_transactions(self.data, month="2026-10")), 0)
        self.assertEqual(len(lg.list_transactions(self.data, category="makan")), 1)
        self.assertEqual(len(lg.list_transactions(self.data, type_="income")), 1)

    # -- ringkasan / matematika -------------------------------------------
    def test_monthly_totals_math(self):
        self.add("income", "5000000", "gaji")
        self.add("income", "250000.50", "freelance")
        self.add("expense", "150000", "makan")
        self.add("expense", "50000", "transport")
        self.add("expense", "99999", "makan", date="2026-10-31")  # bulan lain
        s = lg.compute_summary(self.data, "2026-11")
        self.assertEqual(s["income"], Decimal("5250000.50"))
        self.assertEqual(s["expense"], Decimal("200000"))
        self.assertEqual(s["net"], Decimal("5050000.50"))

    def test_per_category_totals_sorted_desc(self):
        self.add("expense", "150000", "makan")
        self.add("expense", "50000", "makan")
        self.add("expense", "300000", "hiburan")
        s = lg.compute_summary(self.data, "2026-11")
        self.assertEqual(s["expense_by_category"]["makan"], Decimal("200000"))
        self.assertEqual(s["expense_by_category"]["hiburan"], Decimal("300000"))
        # Urut menurun: hiburan dulu, baru makan.
        self.assertEqual(list(s["expense_by_category"]), ["hiburan", "makan"])
        self.assertEqual(s["income_by_category"], {})

    # -- anggaran -----------------------------------------------------------
    def test_budget_status_thresholds(self):
        # Di bawah 80% -> aman.
        self.assertEqual(lg.budget_status(Decimal("100"), Decimal("1000"))[0], "aman")
        # Tepat 80% -> mendekati batas.
        self.assertEqual(lg.budget_status(Decimal("800"), Decimal("1000"))[0],
                         "mendekati batas")
        # 99% -> masih mendekati batas.
        self.assertEqual(lg.budget_status(Decimal("990"), Decimal("1000"))[0],
                         "mendekati batas")
        # Tepat 100% -> mendekati batas (belum lewat).
        self.assertEqual(lg.budget_status(Decimal("1000"), Decimal("1000"))[0],
                         "mendekati batas")
        # Di atas 100% -> melebihi anggaran.
        self.assertEqual(lg.budget_status(Decimal("1000.01"), Decimal("1000"))[0],
                         "melebihi anggaran")

    def test_summary_flags_budget_alerts(self):
        self.add("expense", "850000", "makan")
        lg.set_budget(self.data, "2026-11", "makan", Decimal("1000000"))
        lg.save_ledger(self.ledger, self.data)
        code, out, _ = self.run_cli("summary", "--month", "2026-11")
        self.assertEqual(code, 0)
        self.assertIn("mendekati batas", out)
        self.assertNotIn("melebihi anggaran", out)

        self.add("expense", "200000", "makan")
        lg.save_ledger(self.ledger, self.data)
        code, out, _ = self.run_cli("summary", "--month", "2026-11")
        self.assertEqual(code, 0)
        self.assertIn("melebihi anggaran", out)

    def test_budget_set_show_round_trip(self):
        code, out, _ = self.run_cli("budget", "set", "--category", "makan",
                                    "--amount", "1000000", "--month", "2026-11")
        self.assertEqual(code, 0)
        self.assertIn("Anggaran diset", out)
        code, out, _ = self.run_cli("budget", "show", "--month", "2026-11")
        self.assertEqual(code, 0)
        self.assertIn("makan", out)
        self.assertIn("1,000,000.00", out)

    # -- ekspor -------------------------------------------------------------
    def test_csv_export_shape(self):
        self.add("income", "5000000", "gaji", date="2026-11-01", note="gajian")
        self.add("expense", "50000", "makan", date="2026-11-15", note="nasi padang")
        lg.save_ledger(self.ledger, self.data)
        out_path = Path(self.tmp.name) / "out.csv"
        code, out, _ = self.run_cli("export", "--format", "csv",
                                    "--month", "2026-11", "--out", str(out_path))
        self.assertEqual(code, 0)
        with open(out_path, newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0], ["date", "type", "category", "amount", "note"])
        self.assertEqual(len(rows), 3)  # header + 2 transaksi
        by_date = {r[0]: r for r in rows[1:]}
        self.assertEqual(by_date["2026-11-01"],
                         ["2026-11-01", "income", "gaji", "5000000.00", "gajian"])
        self.assertEqual(by_date["2026-11-15"],
                         ["2026-11-15", "expense", "makan", "50000.00", "nasi padang"])

    def test_json_export_shape(self):
        self.add("expense", "25000", "transport", date="2026-11-05")
        lg.save_ledger(self.ledger, self.data)
        out_path = Path(self.tmp.name) / "out.json"
        code, _, _ = self.run_cli("export", "--format", "json",
                                  "--month", "2026-11", "--out", str(out_path))
        self.assertEqual(code, 0)
        rows = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["category"], "transport")
        self.assertEqual(rows[0]["type"], "expense")

    # -- validasi -----------------------------------------------------------
    def test_invalid_amount_rejected(self):
        for bad in ("0", "-5000", "abc", ""):
            code, _, err = self.run_cli(
                "add", "--type", "expense", "--amount", bad,
                "--category", "makan")
            self.assertNotEqual(code, 0, f"amount={bad!r} harus ditolak")
            self.assertIn("Error", err)
            self.assertNotIn("Traceback", err)

    def test_invalid_date_rejected(self):
        for bad in ("2026-13-01", "2026-02-30", "15-11-2026", "kemarin"):
            code, _, err = self.run_cli(
                "add", "--type", "expense", "--amount", "10000",
                "--category", "makan", "--date", bad)
            self.assertNotEqual(code, 0, f"date={bad!r} harus ditolak")
            self.assertIn("Error", err)
            self.assertNotIn("Traceback", err)

    def test_invalid_month_rejected(self):
        code, _, err = self.run_cli("summary", "--month", "2026-13")
        self.assertNotEqual(code, 0)
        self.assertIn("Error", err)

    # -- hapus & saldo ------------------------------------------------------
    def test_delete_removes_transaction(self):
        tx1 = self.add("expense", "10000", "makan")
        self.add("expense", "20000", "transport")
        lg.save_ledger(self.ledger, self.data)
        code, out, _ = self.run_cli("delete", "--id", tx1["id"])
        self.assertEqual(code, 0)
        self.assertIn("dihapus", out)
        loaded = lg.load_ledger(self.ledger)
        self.assertEqual(len(loaded["transactions"]), 1)
        self.assertEqual(loaded["transactions"][0]["category"], "transport")

    def test_delete_unknown_id_fails(self):
        code, _, err = self.run_cli("delete", "--id", "tidakada123")
        self.assertNotEqual(code, 0)
        self.assertIn("tidak ditemukan", err)

    def test_balance_command(self):
        self.add("income", "1000000", "gaji", date="2026-10-01")
        self.add("expense", "400000", "makan", date="2026-11-15")
        lg.save_ledger(self.ledger, self.data)
        code, out, _ = self.run_cli("balance")
        self.assertEqual(code, 0)
        self.assertIn("1,000,000.00", out)
        self.assertIn("400,000.00", out)
        self.assertIn("600,000.00", out)

    def test_add_cli_end_to_end(self):
        code, out, _ = self.run_cli(
            "add", "--type", "income", "--amount", "2500000",
            "--category", "freelance", "--date", "2026-11-19",
            "--note", "proyek web")
        self.assertEqual(code, 0)
        self.assertIn("Ditambahkan", out)
        code, out, _ = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("freelance", out)
        self.assertIn("2,500,000.00", out)

    def test_env_ledger_variable(self):
        env_path = Path(self.tmp.name) / "env-ledger.json"
        old = os.environ.get(lg.ENV_LEDGER)
        os.environ[lg.ENV_LEDGER] = str(env_path)
        try:
            self.assertEqual(lg.resolve_ledger_path(), env_path)
        finally:
            if old is None:
                del os.environ[lg.ENV_LEDGER]
            else:
                os.environ[lg.ENV_LEDGER] = old


if __name__ == "__main__":
    unittest.main()
