import pdfplumber
import csv
import re
import io
from pathlib import Path
from datetime import datetime
from typing import Union, BinaryIO
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.extraction.schemas import (
    Form16Data, BankTransaction, InvestmentSummary,
    ExtractedFinancials, TransactionCategory, InvestmentTag
)

# ── helpers ───────────────────────────────────────────────────────────────────

def parse_currency(s: str) -> int:
    """'Rs. 1,50,000' or 'Rs. 150,000' or '' → int"""
    if not s or not s.strip():
        return 0
    cleaned = re.sub(r"[^\d]", "", s)
    return int(cleaned) if cleaned else 0


def find_table_with_marker(tables: list, marker: str) -> list:
    """Return the first table whose first row's first cell contains the marker text."""
    for table in tables:
        if table and table[0] and table[0][0] and marker in table[0][0]:
            return table
    return None


def find_row_starting_with(table: list, prefix: str) -> list:
    for row in table:
        if row and row[0] and prefix in row[0]:
            return row
    return None


# ── Form 16 extraction ────────────────────────────────────────────────────────

def extract_form16(source: Union[str, Path, BinaryIO]) -> Form16Data:
    """
    Extracts structured fields from a Form 16 PDF.
    Accepts a file path OR a file-like object (BytesIO) so this same function
    works whether reading a local test fixture or an in-memory upload buffer
    in production (Phase 4 ephemeral flow never writes the source PDF to disk).
    """
    field_found_flags = []  # tracks whether each row/field was LOCATED, not whether its value was > 0

    with pdfplumber.open(source) as pdf:
        all_tables = []
        for page in pdf.pages:
            all_tables.extend(page.extract_tables())

        # ── Part A: identity + employer details ──────────────────────────────
        part_a = find_table_with_marker(all_tables, "Assessment Year")
        if part_a is None:
            raise ValueError("Could not locate Part A table — unrecognized Form 16 layout")

        assessment_year = part_a[0][1].strip()
        employer_name   = part_a[1][1].strip()
        employer_tan    = part_a[1][3].strip()
        employee_name   = part_a[2][1].strip()
        pan_full        = part_a[2][3].strip()
        field_found_flags.extend([True] * 5)  # all 5 Part A fields located

        # ── TDS table: total TDS deducted ─────────────────────────────────────
        tds_table = find_table_with_marker(all_tables, "Quarter")
        tds_deducted = 0
        total_row = find_row_starting_with(tds_table, "Total") if tds_table else None
        if total_row:
            tds_deducted = parse_currency(total_row[3])
        field_found_flags.append(total_row is not None)

        # ── Part B: salary breakdown and deductions ───────────────────────────
        part_b = find_table_with_marker(all_tables, "PARTICULARS")
        if part_b is None:
            raise ValueError("Could not locate Part B table — unrecognized Form 16 layout")

        def get_amount(prefix: str, col: int) -> tuple[int, bool]:
            """Returns (value, was_row_found) — a found row with value 0 is still a success."""
            row = find_row_starting_with(part_b, prefix)
            if row is None:
                return 0, False
            return parse_currency(row[col]), True

        gross_salary,          f1 = get_amount("Total Gross Salary", 2)
        hra_received,            f2 = get_amount("House Rent Allowance", 1)
        hra_exemption_claimed,  f3 = get_amount("HRA Exemption", 1)
        standard_deduction,     f4 = get_amount("Standard Deduction", 1)
        deduction_80C,           f5 = get_amount("Section 80C", 1)
        deduction_80D,           f6 = get_amount("Section 80D", 1)
        net_taxable_income,     f7 = get_amount("NET TAXABLE INCOME", 2)
        basic_salary,            f8 = get_amount("Salary as per provisions", 1)

        field_found_flags.extend([f1, f2, f3, f4, f5, f6, f7, f8])

        confidence = round(sum(field_found_flags) / len(field_found_flags), 2)

        return Form16Data(
            employee_name=employee_name,
            pan_masked=pan_full,
            employer_name=employer_name,
            employer_tan=employer_tan,
            assessment_year=assessment_year,
            gross_salary=gross_salary,
            basic_salary=basic_salary,
            hra_received=hra_received,
            hra_exemption_claimed=hra_exemption_claimed,
            standard_deduction=standard_deduction,
            deduction_80C_claimed=deduction_80C,
            deduction_80D_claimed=deduction_80D,
            net_taxable_income=net_taxable_income,
            tds_deducted=tds_deducted,
            extraction_confidence=confidence,
        )


# ── Bank statement extraction ─────────────────────────────────────────────────

def extract_bank_statement(source: Union[str, Path, BinaryIO]) -> tuple[list[BankTransaction], InvestmentSummary]:
    """
    Parses the bank statement CSV, skipping the header metadata block,
    and returns both the raw transaction list and an aggregated investment summary.
    """
    if isinstance(source, (str, Path)):
        with open(source, "r", encoding="utf-8") as f:
            lines = f.readlines()
    else:
        content = source.read()
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        lines = content.splitlines(keepends=True)

    # Find the actual transaction header row
    header_idx = next(
        (i for i, line in enumerate(lines) if line.startswith("Date,Description")),
        None
    )
    if header_idx is None:
        raise ValueError("Could not locate transaction header row in bank statement")

    reader = csv.DictReader(lines[header_idx:])
    transactions = []

    for row in reader:
        try:
            txn_date = datetime.strptime(row["Date"], "%d-%b-%Y").date()
        except (ValueError, KeyError):
            continue  # skip malformed rows

        debit  = parse_currency(row.get("Debit (Rs.)", ""))
        credit = parse_currency(row.get("Credit (Rs.)", ""))
        category_str = row.get("Category", "OTHER").strip()
        tag_str       = row.get("Tag", "").strip()

        try:
            category = TransactionCategory(category_str)
        except ValueError:
            category = TransactionCategory.OTHER

        try:
            tag = InvestmentTag(tag_str)
        except ValueError:
            tag = InvestmentTag.NONE

        transactions.append(BankTransaction(
            txn_date=txn_date,
            description=row.get("Description", "").strip(),
            debit=debit if debit > 0 else None,
            credit=credit if credit > 0 else None,
            category=category,
            tag=tag,
        ))

    # ── aggregate into InvestmentSummary ──────────────────────────────────────
    summary = InvestmentSummary()

    for txn in transactions:
        amount = txn.debit or 0
        if txn.tag == InvestmentTag.LIC_80C:
            summary.total_lic_premium += amount
        elif txn.tag == InvestmentTag.PPF_80C:
            summary.total_ppf_deposit += amount
        elif txn.tag == InvestmentTag.ELSS_80C:
            summary.total_elss_investment += amount
        elif txn.tag == InvestmentTag.SELF_80D:
            summary.total_self_health_premium += amount
        elif txn.tag == InvestmentTag.PARENTS_80D:
            summary.total_parents_health_premium += amount
        elif txn.tag == InvestmentTag.HRA_RENT:
            summary.total_rent_paid_annual += amount
            summary.rent_transaction_count += 1

    summary.total_80C_raw = (
        summary.total_lic_premium +
        summary.total_ppf_deposit +
        summary.total_elss_investment
    )

    return transactions, summary


# ── combined extraction ────────────────────────────────────────────────────────

def extract_all(form16_source, bank_statement_source, session_id: str) -> ExtractedFinancials:
    form16_data = extract_form16(form16_source)
    transactions, investment_summary = extract_bank_statement(bank_statement_source)

    return ExtractedFinancials(
        session_id=session_id,
        form16=form16_data,
        investments=investment_summary,
        raw_transactions=transactions,
    )