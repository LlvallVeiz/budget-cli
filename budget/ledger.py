"""Inti logika budget-cli: model data, penyimpanan JSON, dan perhitungan.

Semua angka uang dihitung dengan :class:`decimal.Decimal` supaya tidak ada
galat pembulatan biner (penting untuk aplikasi keuangan), lalu disimpan ke
JSON sebagai float yang sudah dibulatkan ke 2 desimal.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

# Nama file & lokasi default ledger.
LEDGER_FILENAME = "ledger.json"
DEFAULT_LEDGER_DIR = Path.home() / ".budget"
ENV_LEDGER = "BUDGET_LEDGER"

TWO_PLACES = Decimal("0.01")


class BudgetError(Exception):
    """Error validasi / operasional yang pesannya aman ditampilkan ke user."""


def resolve_ledger_path(explicit: str | None = None) -> Path:
    """Tentukan path ledger: argumen --ledger > env BUDGET_LEDGER > default."""
    if explicit:
        return Path(explicit).expanduser()
    env_path = os.environ.get(ENV_LEDGER)
    if env_path:
        return Path(env_path).expanduser()
    return DEFAULT_LEDGER_DIR / LEDGER_FILENAME


def empty_ledger() -> dict:
    """Struktur awal ledger kosong."""
    return {"transactions": [], "budgets": {}}


def load_ledger(path: Path) -> dict:
    """Muat ledger dari JSON; file yang belum ada dianggap ledger kosong.

    File rusak (JSON tidak valid / struktur salah) menimbulkan BudgetError
    dengan pesan yang jelas, bukan traceback.
    """
    if not path.exists():
        return empty_ledger()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        raise BudgetError(f"Tidak bisa membaca ledger '{path}': {exc}") from exc
    if not isinstance(data, dict) or "transactions" not in data:
        raise BudgetError(f"Format ledger '{path}' tidak dikenali.")
    data.setdefault("budgets", {})
    return data


def save_ledger(path: Path, data: dict) -> None:
    """Simpan ledger ke JSON (indent 2, UTF-8). Buat folder induk bila perlu."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


# ---------------------------------------------------------------------------
# Validasi
# ---------------------------------------------------------------------------

def parse_amount(raw: str) -> Decimal:
    """Parse jumlah uang: harus angka > 0, dibulatkan ke 2 desimal."""
    try:
        amount = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError, AttributeError) as exc:
        raise BudgetError(f"Jumlah tidak valid: '{raw}' bukan angka.") from exc
    if amount <= 0:
        raise BudgetError(f"Jumlah harus lebih besar dari 0 (diterima: {raw}).")
    return amount.quantize(TWO_PLACES)


def parse_date(raw: str | None) -> str:
    """Validasi tanggal YYYY-MM-DD; None berarti hari ini."""
    if raw is None:
        return date.today().isoformat()
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError as exc:
        raise BudgetError(
            f"Tanggal tidak valid: '{raw}' (harus format YYYY-MM-DD "
            "dan tanggal kalender yang benar)."
        ) from exc
    return parsed.isoformat()


def parse_month(raw: str | None) -> str:
    """Validasi bulan YYYY-MM; None berarti bulan berjalan."""
    if raw is None:
        return date.today().strftime("%Y-%m")
    try:
        parsed = datetime.strptime(raw, "%Y-%m")
    except ValueError as exc:
        raise BudgetError(
            f"Bulan tidak valid: '{raw}' (harus format YYYY-MM, contoh 2026-11)."
        ) from exc
    return parsed.strftime("%Y-%m")


def parse_type(raw: str) -> str:
    if raw not in ("income", "expense"):
        raise BudgetError(f"Tipe harus 'income' atau 'expense' (diterima: {raw}).")
    return raw


def require_category(raw: str | None) -> str:
    if raw is None or not str(raw).strip():
        raise BudgetError("Kategori wajib diisi (--category).")
    return str(raw).strip()


# ---------------------------------------------------------------------------
# Transaksi
# ---------------------------------------------------------------------------

def new_transaction_id() -> str:
    """ID unik pendek: 12 karakter hex dari uuid4."""
    return uuid.uuid4().hex[:12]


def add_transaction(
    data: dict,
    *,
    type_: str,
    amount: Decimal,
    category: str,
    date_str: str,
    note: str = "",
) -> dict:
    """Tambah satu transaksi ke ledger (in-memory) dan kembalikan datanya."""
    tx = {
        "id": new_transaction_id(),
        "date": date_str,
        "type": type_,
        "category": category,
        "amount": float(amount),
        "note": note or "",
    }
    data["transactions"].append(tx)
    return tx


def list_transactions(
    data: dict,
    *,
    month: str | None = None,
    category: str | None = None,
    type_: str | None = None,
) -> list[dict]:
    """Ambil transaksi terfilter, urut terbaru dulu (tanggal desc, lalu id)."""
    result = data["transactions"]
    if month is not None:
        result = [t for t in result if t["date"].startswith(month)]
    if category is not None:
        result = [t for t in result if t["category"] == category]
    if type_ is not None:
        result = [t for t in result if t["type"] == type_]
    # Stabil: transaksi yang ditambah belakangan muncul duluan di tanggal sama.
    return sorted(result, key=lambda t: (t["date"], t["id"]), reverse=True)


def delete_transaction(data: dict, tx_id: str) -> bool:
    """Hapus transaksi berdasarkan ID. True bila ditemukan & dihapus."""
    before = len(data["transactions"])
    data["transactions"] = [t for t in data["transactions"] if t["id"] != tx_id]
    return len(data["transactions"]) < before


# ---------------------------------------------------------------------------
# Ringkasan & anggaran
# ---------------------------------------------------------------------------

def _to_decimal(value) -> Decimal:
    return Decimal(str(value))


def compute_summary(data: dict, month: str) -> dict:
    """Hitung total pemasukan, pengeluaran, saldo, dan total per kategori.

    Mengembalikan dict dengan kunci: month, income, expense, net,
    income_by_category, expense_by_category (keduanya dict kategori->Decimal,
    diurutkan menurun berdasarkan jumlah).
    """
    income = Decimal("0")
    expense = Decimal("0")
    income_by_category: dict[str, Decimal] = {}
    expense_by_category: dict[str, Decimal] = {}

    for tx in data["transactions"]:
        if not tx["date"].startswith(month):
            continue
        amount = _to_decimal(tx["amount"])
        if tx["type"] == "income":
            income += amount
            income_by_category[tx["category"]] = (
                income_by_category.get(tx["category"], Decimal("0")) + amount
            )
        elif tx["type"] == "expense":
            expense += amount
            expense_by_category[tx["category"]] = (
                expense_by_category.get(tx["category"], Decimal("0")) + amount
            )

    def sort_desc(mapping: dict[str, Decimal]) -> dict[str, Decimal]:
        return dict(sorted(mapping.items(), key=lambda kv: kv[1], reverse=True))

    return {
        "month": month,
        "income": income,
        "expense": expense,
        "net": income - expense,
        "income_by_category": sort_desc(income_by_category),
        "expense_by_category": sort_desc(expense_by_category),
    }


def compute_balance(data: dict) -> dict:
    """Total keseluruhan (semua bulan) pemasukan, pengeluaran, dan saldo."""
    income = sum(
        (_to_decimal(t["amount"]) for t in data["transactions"] if t["type"] == "income"),
        Decimal("0"),
    )
    expense = sum(
        (_to_decimal(t["amount"]) for t in data["transactions"] if t["type"] == "expense"),
        Decimal("0"),
    )
    return {"income": income, "expense": expense, "net": income - expense}


def set_budget(data: dict, month: str, category: str, amount: Decimal) -> None:
    """Simpan anggaran bulanan untuk satu kategori."""
    data.setdefault("budgets", {}).setdefault(month, {})[category] = float(amount)


def get_budgets(data: dict, month: str) -> dict[str, Decimal]:
    """Ambil semua anggaran untuk satu bulan (kategori -> Decimal)."""
    raw = data.get("budgets", {}).get(month, {})
    return {cat: _to_decimal(val) for cat, val in raw.items()}


def budget_status(spent: Decimal, limit: Decimal) -> tuple[str, Decimal, Decimal]:
    """Status anggaran sebuah kategori.

    Mengembalikan (label, persen, sisa):
    - "aman" bila pengeluaran < 80% anggaran
    - "mendekati batas" bila pengeluaran >= 80% dan <= 100%
    - "melebihi anggaran" bila pengeluaran > 100%
    """
    if limit <= 0:
        return ("aman", Decimal("0"), limit - spent)
    percent = (spent / limit * 100).quantize(TWO_PLACES)
    remaining = limit - spent
    if spent > limit:
        return ("melebihi anggaran", percent, remaining)
    if percent >= 80:
        return ("mendekati batas", percent, remaining)
    return ("aman", percent, remaining)


def format_money(value: Decimal | float) -> str:
    """Format uang dengan 2 desimal dan pemisah ribuan, contoh 1,500,000.00."""
    return f"{Decimal(str(value)):,.2f}"
