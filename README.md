# budget-cli

Pelacak keuangan pribadi dari terminal — catat pemasukan & pengeluaran,
lihat ringkasan bulanan, atur anggaran per kategori, dan ekspor datamu.
Ditulis dengan **Python standard library saja** (tanpa dependensi).

## Instalasi

Tidak ada yang perlu diinstal selain Python 3.12+:

```bash
git clone https://github.com/LlvallVeiz/budget-cli.git
cd budget-cli
python3 budget_cli.py --help
```

Tidak ada `pip install` — `requirements.txt` sengaja kosong.

## Cara pakai

Semua perintah memakai ledger JSON. Lokasi default: `~/.budget/ledger.json`.
Ubah dengan flag global `--ledger PATH` (sebelum sub-perintah) atau
variabel lingkungan `BUDGET_LEDGER`:

```bash
export BUDGET_LEDGER=~/keuangan-saya.json
```

### Tambah transaksi (`add`)

```bash
python3 budget_cli.py add --type income --amount 5000000 --category gaji \
    --date 2026-11-01 --note "gajian"
# Ditambahkan [a1b2c3d4e5f6] 2026-11-01 income  gaji            5,000,000.00  gajian

python3 budget_cli.py add --type expense --amount 50000 --category makan \
    --note "nasi padang"
# Ditambahkan [9f8e7d6c5b4a] 2026-11-19 expense makan              50,000.00  nasi padang
```

`--date` opsional (default: hari ini). `--note` opsional.

### Lihat daftar (`list`)

```bash
python3 budget_cli.py list
# ID            TANGGAL     TIPE     KATEGORI          JUMLAH  CATATAN
# ---------------------------------------------------------------------
# 9f8e7d6c5b4a  2026-11-19  expense  makan           50,000.00  nasi padang
# a1b2c3d4e5f6  2026-11-01  income   gaji         5,000,000.00  gajian
# ---------------------------------------------------------------------
# Total: pemasukan 5,000,000.00 | pengeluaran 50,000.00
```

Filter: `--month YYYY-MM`, `--category CAT`, `--type income|expense`
(dapat dikombinasikan, misalnya `list --month 2026-11 --category makan`).
Urutan: terbaru dulu.

### Ringkasan bulanan (`summary`)

```bash
python3 budget_cli.py summary --month 2026-11
# Ringkasan 2026-11
#   Total pemasukan   :   5,000,000.00
#   Total pengeluaran :      50,000.00
#   Saldo bersih      :   4,950,000.00
#
# Pengeluaran per kategori:
#   makan                  50,000.00  / anggaran 1,000,000.00 (5.0% dipakai, sisa 950,000.00)
#
# Pemasukan per kategori:
#   gaji                5,000,000.00
```

Tanpa `--month`, memakai bulan berjalan. Total per kategori diurutkan
dari yang terbesar.

### Anggaran (`budget set` / `budget show`)

```bash
python3 budget_cli.py budget set --category makan --amount 1000000 --month 2026-11
# Anggaran diset: makan = 1,000,000.00 / bulan 2026-11

python3 budget_cli.py budget show --month 2026-11
# Anggaran 2026-11
# KATEGORI                 ANGGARAN       TERPAKAI  STATUS
# ----------------------------------------------------------------------
# makan                1,000,000.00      50,000.00  5.0%
```

#### Aturan peringatan anggaran

| Pemakaian | Status |
|---|---|
| < 80% anggaran | aman |
| >= 80% s.d. 100% | ⚠ **mendekati batas** |
| > 100% anggaran | ⚠ **melebihi anggaran** |

Status ini muncul di `summary` (di samping kategori yang punya anggaran)
dan di `budget show`. Anggaran tersimpan per bulan; kategori apa pun boleh
dipakai — tidak ada daftar kategori yang dikunci.

### Ekspor (`export`)

```bash
python3 budget_cli.py export --format csv --month 2026-11 --out november.csv
# Diekspor 2 transaksi ke november.csv (csv)

python3 budget_cli.py export --format json --out semua.json
# Diekspor 2 transaksi ke semua.json (json)
```

CSV memakai header `date,type,category,amount,note`. JSON berisi array
transaksi yang sama. `--month` opsional — tanpa itu, semua transaksi
diekspor.

### Hapus transaksi (`delete`)

```bash
python3 budget_cli.py delete --id 9f8e7d6c5b4a
# Transaksi 9f8e7d6c5b4a dihapus.
```

ID yang tidak ditemukan mencetak pesan error dan keluar dengan kode 1.

### Saldo keseluruhan (`balance`)

```bash
python3 budget_cli.py balance
# Saldo keseluruhan
#   Total pemasukan   :   5,000,000.00
#   Total pengeluaran :      50,000.00
#   Saldo bersih      :   4,950,000.00
```

Berbeda dengan `summary` (satu bulan), `balance` menghitung **semua**
transaksi sepanjang waktu.

## Format file ledger

Satu file JSON dengan dua kunci:

```json
{
  "transactions": [
    {
      "id": "a1b2c3d4e5f6",
      "date": "2026-11-01",
      "type": "income",
      "category": "gaji",
      "amount": 5000000.0,
      "note": "gajian"
    }
  ],
  "budgets": {
    "2026-11": {
      "makan": 1000000.0
    }
  }
}
```

- `id`: 12 karakter hex dari UUID4 (dibuat otomatis).
- `date`: `YYYY-MM-DD`.
- `type`: `income` atau `expense`.
- `amount`: angka positif, disimpan dengan 2 desimal. Perhitungan
  memakai `Decimal` supaya tidak ada galat pembulatan.
- `budgets`: anggaran per bulan (`YYYY-MM`) per kategori.

## Validasi & error

- Jumlah harus angka dan **> 0** (`0`, negatif, atau bukan angka ditolak).
- Tanggal harus `YYYY-MM-DD` yang valid di kalender (`2026-02-30` ditolak).
- `--type` dan `--category` wajib diisi.
- Semua error validasi mencetak pesan yang jelas ke stderr dan keluar
  dengan kode non-nol — tanpa traceback.

## Menjalankan test

```bash
python3 -m unittest discover -s tests -v
```

Test memakai ledger sementara (`tempfile`), jadi tidak menyentuh
ledger aslimu. Mencakup: round-trip tambah/daftar, matematika total
bulanan, total per kategori, ambang peringatan anggaran 80% & lewat
batas, bentuk ekspor CSV/JSON, penolakan jumlah & tanggal tidak valid,
serta hapus transaksi.

## Struktur proyek

```
budget-cli/
├── budget/
│   ├── __init__.py      # info versi paket
│   ├── __main__.py      # `python3 -m budget ...`
│   ├── cli.py           # argparse + semua sub-perintah
│   └── ledger.py        # model data, I/O JSON, validasi, perhitungan
├── tests/
│   └── test_budget.py   # 17 test unittest (stdlib saja)
├── budget_cli.py        # titik masuk: `python3 budget_cli.py ...`
├── README.md
├── requirements.txt     # kosong — stdlib saja
└── .gitignore
```

## Lisensi

MIT.
