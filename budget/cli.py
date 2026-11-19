"""Antarmuka baris perintah (CLI) untuk budget-cli.

Semua perintah memakai argparse. Error validasi ditangkap dan dicetak sebagai
pesan yang jelas ke stderr dengan kode keluar 1 — tidak pernah traceback.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from decimal import Decimal
from pathlib import Path

from . import ledger as lg


# ---------------------------------------------------------------------------
# Perintah-perintah
# ---------------------------------------------------------------------------

def cmd_add(args) -> int:
    path = lg.resolve_ledger_path(args.ledger)
    try:
        type_ = lg.parse_type(args.type)
        amount = lg.parse_amount(args.amount)
        category = lg.require_category(args.category)
        date_str = lg.parse_date(args.date)
    except lg.BudgetError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    data = lg.load_ledger(path)
    tx = lg.add_transaction(
        data, type_=type_, amount=amount, category=category,
        date_str=date_str, note=args.note or "",
    )
    lg.save_ledger(path, data)
    print(
        f"Ditambahkan [{tx['id']}] {tx['date']} "
        f"{tx['type']:7} {tx['category']:<15} {lg.format_money(amount)}"
        + (f"  {tx['note']}" if tx["note"] else "")
    )
    return 0


def cmd_list(args) -> int:
    path = lg.resolve_ledger_path(args.ledger)
    month = lg.parse_month(args.month) if args.month else None
    data = lg.load_ledger(path)
    rows = lg.list_transactions(
        data, month=month, category=args.category, type_=args.type
    )
    if not rows:
        print("Tidak ada transaksi.")
        return 0
    # Lebar kolom dinamis berdasarkan isi, dengan batas yang wajar.
    cat_w = max(len(t["category"]) for t in rows)
    note_w = max(len(t["note"]) for t in rows)
    cat_w = min(max(cat_w, 8), 20)
    header = (
        f"{'ID':<12}  {'TANGGAL':<10}  {'TIPE':<7}  "
        f"{'KATEGORI':<{cat_w}}  {'JUMLAH':>14}  CATATAN"
    )
    print(header)
    print("-" * len(header))
    for t in rows:
        print(
            f"{t['id']:<12}  {t['date']:<10}  {t['type']:<7}  "
            f"{t['category']:<{cat_w}}  {lg.format_money(t['amount']):>14}  "
            f"{t['note']}"
        )
    print("-" * len(header))
    total_in = sum(
        (Decimal(str(t["amount"])) for t in rows if t["type"] == "income"),
        Decimal("0"),
    )
    total_out = sum(
        (Decimal(str(t["amount"])) for t in rows if t["type"] == "expense"),
        Decimal("0"),
    )
    print(f"Total: pemasukan {lg.format_money(total_in)} | "
          f"pengeluaran {lg.format_money(total_out)}")
    return 0


def _print_category_block(title: str, mapping: dict, budgets=None) -> None:
    """Cetak blok total per kategori; bila budgets diberikan, sertakan status."""
    print(f"\n{title}")
    if not mapping and not budgets:
        print("  (tidak ada)")
        return
    categories = sorted(
        set(mapping) | set(budgets or {}),
        key=lambda c: mapping.get(c, Decimal("0")),
        reverse=True,
    )
    for cat in categories:
        spent = mapping.get(cat, Decimal("0"))
        line = f"  {cat:<20} {lg.format_money(spent):>14}"
        if budgets is not None and cat in budgets:
            limit = budgets[cat]
            status, percent, remaining = lg.budget_status(spent, limit)
            line += (
                f"  / anggaran {lg.format_money(limit):>14} "
                f"({percent}% dipakai, sisa {lg.format_money(remaining)})"
            )
            if status == "melebihi anggaran":
                line += "  ⚠ melebihi anggaran"
            elif status == "mendekati batas":
                line += "  ⚠ mendekati batas"
        print(line)


def cmd_summary(args) -> int:
    path = lg.resolve_ledger_path(args.ledger)
    try:
        month = lg.parse_month(args.month)
    except lg.BudgetError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    data = lg.load_ledger(path)
    s = lg.compute_summary(data, month)
    budgets = lg.get_budgets(data, month)
    print(f"Ringkasan {month}")
    print(f"  Total pemasukan   : {lg.format_money(s['income']):>14}")
    print(f"  Total pengeluaran : {lg.format_money(s['expense']):>14}")
    print(f"  Saldo bersih      : {lg.format_money(s['net']):>14}")
    _print_category_block("Pengeluaran per kategori:", s["expense_by_category"], budgets)
    _print_category_block("Pemasukan per kategori:", s["income_by_category"])
    return 0


def cmd_budget_set(args) -> int:
    path = lg.resolve_ledger_path(args.ledger)
    try:
        month = lg.parse_month(args.month)
        amount = lg.parse_amount(args.amount)
        category = lg.require_category(args.category)
    except lg.BudgetError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    data = lg.load_ledger(path)
    lg.set_budget(data, month, category, amount)
    lg.save_ledger(path, data)
    print(f"Anggaran diset: {category} = {lg.format_money(amount)} / bulan {month}")
    return 0


def cmd_budget_show(args) -> int:
    path = lg.resolve_ledger_path(args.ledger)
    try:
        month = lg.parse_month(args.month)
    except lg.BudgetError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    data = lg.load_ledger(path)
    budgets = lg.get_budgets(data, month)
    if not budgets:
        print(f"Tidak ada anggaran untuk bulan {month}.")
        print("Set dengan: budget set --category KATEGORI --amount JUMLAH")
        return 0
    s = lg.compute_summary(data, month)
    print(f"Anggaran {month}")
    print(f"{'KATEGORI':<20} {'ANGGARAN':>14} {'TERPAKAI':>14} {'STATUS'}")
    print("-" * 70)
    for cat in sorted(budgets, key=lambda c: budgets[c], reverse=True):
        limit = budgets[cat]
        spent = s["expense_by_category"].get(cat, Decimal("0"))
        status, percent, remaining = lg.budget_status(spent, limit)
        flag = ""
        if status == "melebihi anggaran":
            flag = "  ⚠ melebihi anggaran"
        elif status == "mendekati batas":
            flag = "  ⚠ mendekati batas"
        print(
            f"{cat:<20} {lg.format_money(limit):>14} "
            f"{lg.format_money(spent):>14}  {percent}%{flag}"
        )
    return 0


def cmd_export(args) -> int:
    path = lg.resolve_ledger_path(args.ledger)
    try:
        month = lg.parse_month(args.month) if args.month else None
    except lg.BudgetError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    data = lg.load_ledger(path)
    rows = lg.list_transactions(data, month=month)
    out = Path(args.out).expanduser()
    try:
        if args.format == "csv":
            with open(out, "w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(["date", "type", "category", "amount", "note"])
                for t in rows:
                    writer.writerow([
                        t["date"], t["type"], t["category"],
                        f"{Decimal(str(t['amount'])):.2f}", t["note"],
                    ])
        else:  # json
            with open(out, "w", encoding="utf-8") as fh:
                json.dump(rows, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
    except OSError as exc:
        print(f"Error: tidak bisa menulis ke '{out}': {exc}", file=sys.stderr)
        return 1
    print(f"Diekspor {len(rows)} transaksi ke {out} ({args.format})")
    return 0


def cmd_delete(args) -> int:
    path = lg.resolve_ledger_path(args.ledger)
    data = lg.load_ledger(path)
    if lg.delete_transaction(data, args.id):
        lg.save_ledger(path, data)
        print(f"Transaksi {args.id} dihapus.")
        return 0
    print(f"Error: transaksi dengan ID '{args.id}' tidak ditemukan.", file=sys.stderr)
    return 1


def cmd_balance(args) -> int:
    path = lg.resolve_ledger_path(args.ledger)
    data = lg.load_ledger(path)
    b = lg.compute_balance(data)
    print("Saldo keseluruhan")
    print(f"  Total pemasukan   : {lg.format_money(b['income']):>14}")
    print(f"  Total pengeluaran : {lg.format_money(b['expense']):>14}")
    print(f"  Saldo bersih      : {lg.format_money(b['net']):>14}")
    return 0


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="budget",
        description="Pelacak keuangan pribadi dari terminal (tanpa dependensi).",
    )
    parser.add_argument(
        "--ledger", metavar="PATH",
        help="Path file ledger JSON (default: ~/.budget/ledger.json, "
             "atau env BUDGET_LEDGER).",
    )
    sub = parser.add_subparsers(dest="command", metavar="PERINTAH")

    p_add = sub.add_parser("add", help="Tambah transaksi.")
    p_add.add_argument("--type", required=True, choices=["income", "expense"],
                       help="Jenis transaksi.")
    p_add.add_argument("--amount", required=True, help="Jumlah (> 0).")
    p_add.add_argument("--category", required=True, help="Kategori.")
    p_add.add_argument("--date", help="Tanggal YYYY-MM-DD (default: hari ini).")
    p_add.add_argument("--note", default="", help="Catatan (opsional).")
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="Tampilkan daftar transaksi.")
    p_list.add_argument("--month", help="Filter bulan YYYY-MM.")
    p_list.add_argument("--category", help="Filter kategori.")
    p_list.add_argument("--type", choices=["income", "expense"],
                        help="Filter jenis transaksi.")
    p_list.set_defaults(func=cmd_list)

    p_summary = sub.add_parser("summary", help="Ringkasan bulanan + status anggaran.")
    p_summary.add_argument("--month", help="Bulan YYYY-MM (default: bulan ini).")
    p_summary.set_defaults(func=cmd_summary)

    p_budget = sub.add_parser("budget", help="Kelola anggaran bulanan per kategori.")
    budget_sub = p_budget.add_subparsers(dest="budget_command", metavar="AKSI")

    p_bset = budget_sub.add_parser("set", help="Set anggaran kategori.")
    p_bset.add_argument("--category", required=True)
    p_bset.add_argument("--amount", required=True, help="Batas anggaran (> 0).")
    p_bset.add_argument("--month", help="Bulan YYYY-MM (default: bulan ini).")
    p_bset.set_defaults(func=cmd_budget_set)

    p_bshow = budget_sub.add_parser("show", help="Tampilkan anggaran & pemakaian.")
    p_bshow.add_argument("--month", help="Bulan YYYY-MM (default: bulan ini).")
    p_bshow.set_defaults(func=cmd_budget_show)

    p_export = sub.add_parser("export", help="Ekspor transaksi ke CSV/JSON.")
    p_export.add_argument("--format", required=True, choices=["csv", "json"])
    p_export.add_argument("--month", help="Filter bulan YYYY-MM.")
    p_export.add_argument("--out", required=True, help="Path file keluaran.")
    p_export.set_defaults(func=cmd_export)

    p_delete = sub.add_parser("delete", help="Hapus transaksi berdasarkan ID.")
    p_delete.add_argument("--id", required=True, help="ID transaksi.")
    p_delete.set_defaults(func=cmd_delete)

    p_balance = sub.add_parser("balance", help="Total pemasukan/pengeluaran keseluruhan.")
    p_balance.set_defaults(func=cmd_balance)

    return parser


def main(argv=None) -> int:
    """Titik masuk CLI. Mengembalikan kode keluar (0 = sukses)."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except lg.BudgetError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
