# Optimized Smart Variety Search

import streamlit as st
import pandas as pd
import io
import re
import numpy as np
from typing import List, Dict, Any, Tuple
from streamlit_sortables import sort_items
from concurrent.futures import ThreadPoolExecutor

# --- File Loader ---
@st.cache_data(show_spinner=False)
def load_file(file_bytes: bytes, filename: str) -> Dict[str, pd.DataFrame]:
    if filename.endswith('.csv'):
        df = pd.read_csv(io.BytesIO(file_bytes), header=None)
        return {'CSV_Sheet': df}
    elif filename.endswith(('.xlsx', '.xls')):
        excel_file = pd.ExcelFile(io.BytesIO(file_bytes))
        return {sheet_name: excel_file.parse(sheet_name, header=None, dtype=str) for sheet_name in excel_file.sheet_names}
    else:
        raise ValueError("Unsupported file type. Please upload a CSV or Excel file.")

# --- Column Block Detection (Optimized) ---
def find_column_blocks(df: pd.DataFrame) -> List[Tuple[int, int]]:
    is_empty_col = df.isnull().all().values
    blocks = []
    start = None
    for i, is_empty in enumerate(is_empty_col):
        if not is_empty and start is None:
            start = i
        elif is_empty and start is not None:
            blocks.append((start, i))
            start = None
    if start is not None:
        blocks.append((start, len(is_empty_col)))
    return blocks

# --- Match Logic (Vectorized) ---
def is_match_series(series: pd.Series, term: str, match_type: str) -> pd.Series:
    term = term.strip().lower()
    series = series.astype(str).str.strip().str.lower()
    if match_type == "Exact":
        return series == term
    elif match_type == "Partial (contains)":
        return series.str.contains(re.escape(term), case=False, na=False)
    elif match_type == "Starts with":
        return series.str.startswith(term)
    elif match_type == "Ends with":
        return series.str.endswith(term)
    return pd.Series([False] * len(series))

# --- Sub-Table Parsing ---
def parse_block(sheet_name, df, search_terms, match_type, filter_columns):
    results = []
    blocks = find_column_blocks(df)
    df_str = df.astype(str).apply(lambda x: x.str.strip().str.lower())

    for start_col, end_col in blocks:
        sub_df = df.iloc[:, start_col:end_col]
        sub_str = df_str.iloc[:, start_col:end_col]

        header_row, data_start_idx = None, 0
        for i in range(len(sub_df)):
            row = sub_df.iloc[i]
            if not search_terms and filter_columns and any(fc.lower() in row.astype(str).str.lower().values for fc in filter_columns):
                header_row = list(row)
                data_start_idx = i + 1
                break
            elif row.notna().all() and all(str(cell).strip() != "" for cell in row):
                header_row = list(row)
                data_start_idx = i + 1
                break

        if header_row is None:
            header_row = list(sub_df.iloc[0])
            data_start_idx = 1

        for row_idx in range(data_start_idx, len(sub_df)):
            row_str = sub_str.iloc[row_idx]
            for term in search_terms:
                if is_match_series(row_str, term, match_type).any():
                    file_name, sheet = sheet_name.split(' - ', 1)
                    row_values = list(sub_df.iloc[row_idx])
                    row_values += [''] * (len(header_row) - len(row_values))
                    results.append({
                        'File': file_name,
                        'Sheet': sheet,
                        'Row': row_idx + 1,
                        'Matched Term': term,
                        'Headers': header_row,
                        'Values': row_values
                    })
                    break
    return results

# --- Parallel Runner for Sub-Tables ---
def find_matches_by_block_parallel(dataframes: Dict[str, pd.DataFrame], search_terms: List[str], match_type: str, filter_columns: List[str] = None) -> List[Dict[str, Any]]:
    results = []
    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(parse_block, name, df, search_terms, match_type, filter_columns) for name, df in dataframes.items()]
        for f in futures:
            results.extend(f.result())
    return results

# --- Single Table Parsing ---
def find_matches_single_table_optimized(dataframes: Dict[str, pd.DataFrame], selected_sheets: List[str], search_terms: List[str], match_type: str, filter_columns: List[str] = None) -> List[Dict[str, Any]]:
    results = []
    for sheet_name in selected_sheets:
        df = dataframes[sheet_name]
        if df.empty:
            continue

        df_str = df.astype(str).apply(lambda x: x.str.strip().str.lower())
        first_empty_col = next((i for i in range(len(df.columns)) if df.iloc[:, i].isna().all()), len(df.columns))
        col_block = df.iloc[:, :first_empty_col]
        col_block_str = df_str.iloc[:, :first_empty_col]

        header_row_idx = None
        for i in range(len(col_block)):
            row = col_block.iloc[i]
            if not search_terms and filter_columns and any(fc.lower() in row.astype(str).str.lower().values for fc in filter_columns):
                header_row_idx = i
                break
            elif row.notna().all() and all(str(cell).strip() != "" for cell in row):
                header_row_idx = i
                break

        if header_row_idx is None:
            header_row_idx = 0

        header_row = col_block.iloc[header_row_idx]
        valid_col_indices = [i for i, val in enumerate(header_row) if pd.notna(val) and str(val).strip()]

        if not valid_col_indices:
            continue

        headers = [str(header_row[i]) for i in valid_col_indices]
        data = col_block.iloc[header_row_idx + 1:, valid_col_indices].reset_index(drop=True)
        data_str = col_block_str.iloc[header_row_idx + 1:, valid_col_indices].reset_index(drop=True)
        data.columns = headers

        for row_idx in range(len(data)):
            row_str = data_str.iloc[row_idx]
            for term in search_terms:
                if is_match_series(row_str, term, match_type).any():
                    file_name, sheet = sheet_name.split(' - ', 1)
                    row_values = list(data.iloc[row_idx])
                    row_values += [''] * (len(headers) - len(row_values))
                    results.append({
                        'File': file_name,
                        'Sheet': sheet,
                        'Row': row_idx + header_row_idx + 2,
                        'Matched Term': term,
                        'Headers': headers,
                        'Values': row_values
                    })
                    break
    return results

# --- Filtering Logic ---
def match_filter_group(row_dict: Dict[str, Any], filter_group: Dict[str, Any], match_type: str) -> bool:
    col_input = filter_group["column"].strip().lower()
    values = filter_group["values"]
    logic = filter_group["logic"]
    normalized_dict = {str(k).strip().lower(): v for k, v in row_dict.items()}
    if col_input not in normalized_dict:
        return False
    cell_value = str(normalized_dict[col_input])
    def matches(val):
        if match_type == "Exact":
            return cell_value.strip().lower() == val.strip().lower()
        elif match_type == "Partial (contains)":
            return val.strip().lower() in cell_value.strip().lower()
        elif match_type == "Starts with":
            return cell_value.strip().lower().startswith(val.strip().lower())
        elif match_type == "Ends with":
            return cell_value.strip().lower().endswith(val.strip().lower())
        return False
    match_results = [matches(v) for v in values]
    return all(match_results) if logic == "AND" else any(match_results)

def apply_advanced_filters(results: List[Dict[str, Any]], filters: List[Dict[str, Any]], global_logic: str, match_type: str) -> List[Dict[str, Any]]:
    filtered = []
    for res in results:
        row_dict = dict(zip(res['Headers'], res['Values']))
        group_matches = [match_filter_group(row_dict, fgroup, match_type) for fgroup in filters]
        if (global_logic == "AND" and all(group_matches)) or (global_logic == "OR" and any(group_matches)):
            filtered.append(res)
    return filtered

# --- Highlight Helper ---
def highlight_value(value: str, term: str, match_type: str) -> str:
    if match_type == "Exact":
        if value.strip().lower() == term.lower():
            return f"<mark>{value}</mark>"
    elif match_type == "Partial (contains)":
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        return pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", value)
    elif match_type == "Starts with":
        if value.lower().startswith(term.lower()):
            return f"<mark>{value[:len(term)]}</mark>{value[len(term):]}"
    elif match_type == "Ends with":
        if value.lower().endswith(term.lower()):
            return f"{value[:-len(term)]}<mark>{value[-len(term):]}</mark>"
    return value

# --- Display Results ---
def display_results(results: List[Dict[str, Any]], match_type: str):
    if not results:
        st.warning("No matches found.")
        return
    grouped = {}
    for res in results:
        key = res['File']
        grouped.setdefault(key, []).append(res)
    for file, file_results in grouped.items():
        st.markdown(f"## Matches in File: `{file}`")
        sheets = {}
        for res in file_results:
            sheets.setdefault(res['Sheet'], []).append(res)
        for sheet, matches in sheets.items():
            st.markdown(f"### Sheet: `{sheet}` — {len(matches)} match(es)")
            for idx, result in enumerate(matches, 1):
                highlighted_values = []
                for header, value in zip(result['Headers'], result['Values']):
                    highlighted = highlight_value(str(value), result['Matched Term'], match_type)
                    highlighted_values.append((header, highlighted))
                html = f"""
                <div style='border:1px solid #ccc; padding:1rem; margin-bottom:1rem; border-radius:0.5rem; background-color:#f9f9f9;'>
                    <h4 style='margin-top:0;'><u>Match {idx}</u> — Row: <code>{result['Row']}</code> — Term: <code>{result['Matched Term']}</code></h4>
                    <h5 style='margin-bottom:0.5rem;'>Matched Row:</h5>
                """
                for header, html_value in highlighted_values:
                    html += f"<b>{header}</b>: {html_value}<br>"
                html += "</div>"
                st.markdown(html, unsafe_allow_html=True)

# --- CSV Export ---
def results_to_dataframe(results: List[Dict[str, Any]]) -> pd.DataFrame:
    records = []
    for result in results:
        record = {
            'File': result['File'],
            'Sheet': result['Sheet'],
            'Row': result['Row'],
            'Matched Term': result['Matched Term']
        }
        for i, (header, value) in enumerate(zip(result['Headers'], result['Values'])):
            record[f'Column_{i+1}_Header'] = header
            record[f'Column_{i+1}_Value'] = value
        records.append(record)
    return pd.DataFrame(records)

# --- App Config ---
st.set_page_config(page_title="Smart Variety Search", layout="wide")

def check_password():
    if "authenticated" not in st.session_state:
        st.session_state["authenticated"] = False

    if not st.session_state["authenticated"]:
        with st.form("Password Form"):
            password = st.text_input("Enter password", type="password")
            submitted = st.form_submit_button("Login")
            if submitted:
                if password == st.secrets["auth"]["password"]:
                    st.session_state["authenticated"] = True
                else:
                    st.error("Incorrect password")
        st.stop()

check_password()

# --- Interface ---
st.title("Smart Variety Search Application")

st.markdown("""
Upload one or more CSV or Excel files and enter one or more search terms (comma-separated).
The app will detect either single tables or sub-tables and return full matching rows grouped by file and sheet.

---

**Parsing Options:**
- **Single Table**: Use for sheets with one table.
- **Sub-Tables**: Use for sheets with multiple tables side-by-side.
""")

uploaded_files = st.file_uploader("Upload your CSV or Excel files", type=['csv', 'xlsx', 'xls'], accept_multiple_files=True)

dataframes = {}
if uploaded_files:
    for file in uploaded_files:
        try:
            content = file.read()
            parsed = load_file(content, file.name)
            for sheet, df in parsed.items():
                key = f"{file.name} - {sheet}"
                dataframes[key] = df
        except Exception as e:
            st.error(f"Failed to process file '{file.name}': {e}")

if dataframes:
    st.markdown("### Drag and Drop Sheets Into Parsing Categories")
    original_items = [
        {'header': 'Unsorted', 'items': list(dataframes.keys())},
        {'header': 'Single Table', 'items': []},
        {'header': 'Sub-Tables', 'items': []}
    ]
    sorted_groups = sort_items(original_items, multi_containers=True)
    single_table_sheets = sorted_groups[1]['items']
    subtable_sheets = sorted_groups[2]['items']

    st.markdown("---")
    search_input = st.text_input("Enter Search Terms (comma-separated)")
    match_type = st.selectbox("Match Type", options=["Partial (contains)", "Exact", "Starts with", "Ends with"], index=0)

    filter_count = st.number_input("Number of Filters", min_value=0, max_value=10, value=0, step=1)
    filter_groups = []
    for i in range(filter_count):
        with st.expander(f"Filter {i+1}"):
            column = st.text_input(f"Column name for Filter {i+1}", key=f"f_col_{i}")
            values = st.text_input(f"Comma-separated values", key=f"f_vals_{i}")
            logic = st.selectbox("Column Match Logic (AND/OR)", options=["OR", "AND"], key=f"f_logic_{i}")
            if column and values:
                value_list = [v.strip() for v in values.split(',') if v.strip()]
                filter_groups.append({"column": column, "values": value_list, "logic": logic})

    global_filter_logic = st.radio("Global Row Filter Logic (combine filters with):", ["AND", "OR"])
    filter_match_type = st.selectbox("Filter Match Type", options=["Partial (contains)", "Exact", "Starts with", "Ends with"], index=0)

    search_terms = [term.strip() for term in search_input.split(',') if term.strip()]

    # --- Display Options BEFORE Search ---
    display_option = st.radio(
        "How would you like to display results?",
        options=["Show All", "Show First N Matches", "Don't Show Any"],
        index=0,
        horizontal=True
    )

    max_to_show = None
    if display_option == "Show First N Matches":
        max_to_show = st.number_input(
            "Enter number of results to show",
            min_value=1,
            value=10,
            step=1
        )

    # --- Search Button ---
    if st.button("Search"):
        search_results = []
        filter_columns = [f['column'] for f in filter_groups] if filter_groups else None

        if subtable_sheets:
            sub_df = {s: dataframes[s] for s in subtable_sheets}
            search_results += find_matches_by_block_parallel(
                sub_df,
                search_terms if search_terms else [''],
                match_type,
                filter_columns
            )

        if single_table_sheets:
            search_results += find_matches_single_table_optimized(
                dataframes,
                single_table_sheets,
                search_terms if search_terms else [''],
                match_type,
                filter_columns
            )

        if filter_groups:
            search_results = apply_advanced_filters(
                search_results,
                filter_groups,
                global_filter_logic,
                filter_match_type
            )

        if search_results:
            st.success(f"Found {len(search_results)} matches.")

            # Export results to CSV
            export_df = results_to_dataframe(search_results)
            csv = export_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                "Download Results as CSV",
                data=csv,
                file_name="multi_file_search_results.csv",
                mime='text/csv'
            )

            # Display results based on user toggle
            if display_option == "Show First N Matches" and max_to_show:
                display_results(search_results[:int(max_to_show)], match_type)

            elif display_option == "Show All":
                display_results(search_results, match_type)

            else:
                st.info("Result display is turned off. You can still download the results above.")

        else:
            st.warning("No matches found for the current search and filter criteria.")