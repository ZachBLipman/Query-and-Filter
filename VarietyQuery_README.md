# Smart Variety Search – Multi-File Query & Filter Tool

## Overview

This repository contains a **Streamlit web application** for searching and filtering “variety” (or any tabular) data across **multiple CSV/Excel files and multiple sheets**, even when sheets contain:

- A **single large table**, or
- Multiple **sub-tables positioned side-by-side** within the same sheet (separated by empty columns).

The app is optimized for interactive use on moderately large spreadsheets by combining:

- Vectorized Pandas string matching for search terms
- Parallel processing for sub-table sheets (`ThreadPoolExecutor`)
- A user-driven “sheet parsing mode” selector via drag-and-drop

Users can:
- Upload many files at once
- Assign each sheet to “Single Table” or “Sub-Tables” parsing
- Search for one or more terms (comma-separated)
- Apply up to 10 column-based filters with AND/OR logic
- Choose global filter logic (AND/OR across filter groups)
- Export matching rows to CSV
- Optionally display matches inline with highlighted terms

---

## Repository Structure

```
Query-and-Filter/
├── Variety Query.py            # Streamlit app (all logic + UI)
├── requirements.txt            # Dependencies
└── .gitattributes
```

> Note: The zip includes a `.git/` directory (repo metadata). It is not required for runtime.

---

## Installation

### 1) Create a virtual environment (recommended)

```bash
python -m venv venv
source venv/bin/activate          # macOS/Linux
venv\Scripts\activate           # Windows
```

### 2) Install dependencies

```bash
pip install -r requirements.txt
```

`requirements.txt` includes:
- `streamlit`
- `streamlit-sortables` (drag/drop sheet categorization UI)
- `pandas`
- `openpyxl` (Excel parsing)
- `rapidfuzz`

**Important:** In the current code snapshot, `rapidfuzz` is listed but is not referenced in `Variety Query.py`. It may be intended for future fuzzy matching enhancements.

---

## Running the App

```bash
streamlit run "Variety Query.py"
```

---

## Security / Login

The app includes a simple password gate implemented via Streamlit secrets:

```python
if password == st.secrets["auth"]["password"]:
```

To run locally, create:

```
.streamlit/secrets.toml
```

Example:

```toml
[auth]
password = "your-password-here"
```

If this is not configured, the app will raise an error when trying to read `st.secrets`.

> This is a front-end gate intended for lightweight access control, not a hardened authentication system.

---

## Core Concepts

### 1) “Sheet Parsing Modes”

Each uploaded sheet is categorized into one of:

- **Single Table**: the sheet contains one main table (typically left-aligned)
- **Sub-Tables**: the sheet contains multiple adjacent tables separated by empty columns

The UI exposes a drag-and-drop control (via `streamlit_sortables.sort_items`) so the user can assign each sheet to the correct mode before searching.

This matters because the parsing algorithm is different in each case.

---

### 2) Match Types

Search terms can be matched by one of:

- **Partial (contains)** (default)
- **Exact**
- **Starts with**
- **Ends with**

Matching is implemented in a vectorized way (`is_match_series`) using Pandas string operations, making it much faster than row-by-row Python loops for typical spreadsheet sizes.

---

### 3) Filters

Filters are optional and are applied **after** initial term matching.

Each filter group specifies:
- a column name
- a list of acceptable values
- within-group logic: **AND** or **OR**
- a match type (same options + “Does NOT contain” for filters)

Filters are combined across groups using a global logic toggle: **AND** or **OR**.

---

## Data Model for Results

A match result is stored as a dictionary with:

- `File`: original file name
- `Sheet`: sheet name (for Excel) or a synthetic sheet name for CSV
- `Row`: original row number in the sheet (1-based-ish; derived from parsing offset)
- `Matched Term`: the specific term that matched
- `Headers`: list of parsed column headers for the relevant table
- `Values`: list of cell values for the matched row (aligned to Headers)

This structure is used both for on-screen rendering and for export.

---

## How Parsing Works

### A) Loading Files (`load_file`)

- **CSV**: read with `header=None` into a single sheet named `CSV_Sheet`
- **Excel**: each sheet is read with `header=None` and `dtype=str`

The app always loads sheets without assuming headers so it can detect header rows dynamically later.

Caching:
- `load_file` is wrapped in `@st.cache_data(show_spinner=False)` to avoid re-parsing unchanged uploads.

---

### B) Single Table Parsing (`find_matches_single_table_optimized`)

Algorithm summary:

1. Identify the first *fully empty* column → treat columns before that as the “main table block”.
2. Detect a header row by scanning from the top:
   - If search terms are empty and filters are provided, it will also accept a row containing any filter column names.
   - Otherwise, it picks the first row where all cells are non-null and non-empty.
   - Fallback: row 0
3. Build the header list from non-empty header cells.
4. Create a normalized lowercase “string view” (`df_str`) for matching.
5. For each data row:
   - Check each search term against the row using the selected match type.
   - If any cell matches, emit a result record.

This is “optimized” mainly by:
- precomputing `df_str` once per sheet
- using vectorized matching per row via `is_match_series`

---

### C) Sub-Table Parsing (`parse_block` + `find_column_blocks`)

A “sub-table sheet” may contain multiple adjacent tables separated by one or more completely empty columns.

Algorithm summary:

1. Detect column blocks with `find_column_blocks(df)`:
   - scan columns
   - each contiguous set of non-empty columns becomes a block `(start_col, end_col)`
2. For each block:
   - detect the header row using the same heuristic as single-table parsing
   - search within that block for matching rows
3. Emit results with file/sheet/row metadata

Parallelization:
- `find_matches_by_block_parallel` uses `ThreadPoolExecutor` to run `parse_block` across selected sheets concurrently.

This is especially useful when many sheets have multiple blocks.

---

## Search + Filter Pipeline (End-to-End)

```
Upload files
   ↓
Parse into per-sheet DataFrames (no headers assumed)
   ↓
User assigns sheets → Single Table vs Sub-Tables
   ↓
Search terms matched (vectorized)
   ↓
(Optionally) apply advanced column filters
   ↓
Results displayed (optional) and exported to CSV
```

---

## UI Walkthrough

### 1) Upload
- `st.file_uploader(..., accept_multiple_files=True)`
- Supports `.csv`, `.xlsx`, `.xls`

### 2) Categorize sheets (drag and drop)
- Unsorted → Single Table → Sub-Tables

### 3) Search
- Search terms: comma-separated string
- Match type dropdown

### 4) Filters
- “Number of Filters” (0–10)
- Each filter is configured in an expander:
  - column name
  - comma-separated values
  - within-filter AND/OR logic

Global settings:
- global filter logic: AND/OR
- filter match type (including “Does NOT contain”)

### 5) Result display mode
- Show All
- Show First N Matches
- Don’t Show Any (download-only mode)

### 6) Export
- Always available when results exist
- `st.download_button` exports `multi_file_search_results.csv`

### 7) Display (optional)
Results are grouped:
- by file
- then by sheet

Each result renders as a styled HTML block, with matched terms highlighted using `<mark>`.

---

## Key Functions

### `find_column_blocks(df)`
Detects contiguous non-empty column blocks (used for sub-table sheets).

### `is_match_series(series, term, match_type)`
Vectorized matching of a term against all cells in a row (case-insensitive).

### `parse_block(...)`
Parses and searches inside each detected column block within a sheet.

### `find_matches_by_block_parallel(...)`
Runs `parse_block` across multiple sheets concurrently.

### `find_matches_single_table_optimized(...)`
Parses and searches the main table region of “single table” sheets.

### `match_filter_group(row_dict, filter_group, match_type)`
Evaluates a single filter group against a row (supports AND/OR within the group).

### `apply_advanced_filters(results, filters, global_logic, match_type)`
Combines filter group results using global AND/OR and filters the match list.

### `highlight_value(value, term, match_type)`
Wraps matched substrings with `<mark>` for inline highlighting.

### `results_to_dataframe(results)`
Flattens match results into a rectangular DataFrame suitable for CSV export.

---

## Limitations / Gotchas

- Header detection is heuristic. If a sheet’s “first fully-populated row” is not actually a header, results may have incorrect headers.
- For sub-table sheets, tables must be separated by fully empty columns for block detection to work reliably.
- Filters match column names by lowercasing and stripping; the column must exist in the detected header row.
- `rapidfuzz` is not currently used; if you need fuzzy column/header matching, it’s a logical enhancement point.

---

## Suggested Enhancements

If you intend to evolve this tool, common next steps are:

- **Fuzzy header/column matching** (use RapidFuzz to map user-entered filter columns to nearest header)
- Better table detection (support empty cells in header rows)
- “Preview detected headers” UI per sheet/block before running the search
- Export format options (Excel output, one sheet per source sheet)
- Persist drag/drop sheet categorization across sessions

---

## License

No license file is included in this snapshot. Add a `LICENSE` file if you plan to distribute this project.
