# Tax Filing Assistant — Scope Document
# Module 1 output | Phase 1 | India Tax Assistant Project

## Target Users
Salaried individuals, resident status, filing Indian income tax returns.

## Assessment Years Covered
- AY 2025-26 (FY 2024-25)
- AY 2026-27 (FY 2025-26, Budget 2025 slabs)
- Architecture is year-agnostic: future AYs added via tax_constants.yaml only, no code changes required.

## Tax Regimes Covered
- Old Tax Regime
- New Tax Regime (default from AY 2024-25 onwards per Section 115BAC)

## Deductions and Sections IN SCOPE

| Section         | Description                        | Instruments Covered                                              |
|-----------------|------------------------------------|------------------------------------------------------------------|
| 80C             | Investment and savings deductions  | LIC premium, PPF, ELSS, EPF (employee)                          |
| 80D             | Health insurance premium deduction | Self/spouse/children (25k) + parents (25k/50k if senior citizen) |
| 10(13A)/Rule 2A | HRA exemption                      | Min of: actual HRA, 50%/40% of salary, rent minus 10% salary    |
| 16(ia)          | Standard deduction                 | Rs 50,000 (old regime), Rs 75,000 (new regime AY 2026-27)       |
| 115BAC          | New regime slabs and conditions    | Regime comparison, switching rules                               |

## Explicitly OUT OF SCOPE
- Capital gains (short-term or long-term, any asset class)
- Business or professional income (44AD, 44ADA)
- NRI taxpayers (residency determination, DTAA, foreign tax credit)
- Section 80E (education loan interest)
- Section 80G (donations)
- Section 80CCD/80CCD(1B) (NPS) — most likely candidate to add in v2
- Section 80TTA / 80TTB (savings/senior citizen interest)
- State-specific professional tax nuances

## Architecture Constraints
1. All numeric constants live in data/tax_constants.yaml, versioned by AY.
   The LLM never performs arithmetic or reads numeric values from embedded text.
2. Knowledge base chunks carry AY validity metadata (effective_from_ay, effective_to_ay).
3. Public tax law text is persisted in ChromaDB. User documents are never persisted (Phase 4).