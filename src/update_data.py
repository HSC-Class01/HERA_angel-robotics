"""Collect Angel Robotics periodic-report financial statements from OpenDART.

API keys are supplied only through the DART_API_KEY environment variable.
The all-account financial statement endpoint starts in 2015; filing metadata is
searched from 2010 as requested.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
DASHBOARD_DIR = ROOT / "dashboard"
API_ROOT = "https://opendart.fss.or.kr/api"
COMPANY_NAME = "엔젤로보틱스"
FILING_START_YEAR = 2010
FINANCIAL_START_YEAR = 2015
REPORTS = {
    "11011": ("annual", "사업보고서"),
    "11012": ("half_year", "반기보고서"),
    "11013": ("quarterly", "1분기보고서"),
    "11014": ("quarterly", "3분기보고서"),
}

SESSION = requests.Session()
retry = Retry(
    total=5,
    connect=5,
    read=5,
    backoff_factor=1.0,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset(["GET"]),
    respect_retry_after_header=True,
)
SESSION.mount("https://", HTTPAdapter(max_retries=retry))
SESSION.headers.update({"User-Agent": "HERA-Angel-Robotics-DART-Agent/2.0"})


class DARTError(RuntimeError):
    pass


def api_json(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    """Call an OpenDART JSON endpoint and normalize no-data responses."""
    response = SESSION.get(f"{API_ROOT}/{endpoint}.json", params=params, timeout=(15, 90))
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise DARTError(f"{endpoint}: JSON 응답을 읽지 못했습니다.") from exc

    status = str(payload.get("status", ""))
    if status == "013":  # No data is normal for years before filings or unavailable reports.
        payload.setdefault("list", [])
        return payload
    if status != "000":
        message = str(payload.get("message", "알 수 없는 API 오류"))
        raise DARTError(f"{endpoint}: OpenDART 오류 {status} - {message}")
    return payload


def fetch_corp_code(api_key: str) -> str:
    """Fetch and parse corpCode.xml ZIP using only the standard XML parser."""
    response = SESSION.get(
        f"{API_ROOT}/corpCode.xml", params={"crtfc_key": api_key}, timeout=(15, 90)
    )
    response.raise_for_status()
    try:
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            xml_name = next(
                (name for name in archive.namelist() if name.lower().endswith(".xml")), None
            )
            if not xml_name:
                raise DARTError("corpCode ZIP에 XML 파일이 없습니다.")
            xml_bytes = archive.read(xml_name)
    except zipfile.BadZipFile as exc:
        raise DARTError(
            "corpCode.xml 응답이 ZIP 파일이 아닙니다. DART API 키와 응답을 확인하세요."
        ) from exc

    root = ET.fromstring(xml_bytes)
    candidates: list[dict[str, str]] = []
    for item in root.findall(".//list"):
        row = {child.tag: (child.text or "").strip() for child in item}
        name = re.sub(r"\s+", "", row.get("corp_name", ""))
        if COMPANY_NAME in name:
            candidates.append(row)
    if not candidates:
        raise DARTError(f"corpCode.xml에서 '{COMPANY_NAME}' 회사를 찾지 못했습니다.")

    exact = [r for r in candidates if re.sub(r"\s+", "", r.get("corp_name", "")) == COMPANY_NAME]
    chosen = exact[0] if exact else candidates[0]
    corp_code = chosen.get("corp_code", "").strip()
    if not re.fullmatch(r"\d{8}", corp_code):
        raise DARTError(f"올바르지 않은 corp_code 값입니다: {corp_code!r}")
    (RAW_DIR / "company.json").write_text(
        json.dumps(
            {
                "corp_name": chosen.get("corp_name", COMPANY_NAME),
                "corp_code": corp_code,
                "stock_code": chosen.get("stock_code", ""),
                "collected_at_utc": datetime.now(timezone.utc).isoformat(),
                "source": "OpenDART corpCode.xml",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return corp_code


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", "")
    if text in ("", "-", "–", "—", "None", "nan", "NaN"):
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_filings(api_key: str, corp_code: str) -> pd.DataFrame:
    """Fetch periodic-disclosure index from 2010 and filter annual/half/quarter reports."""
    all_rows: list[dict[str, Any]] = []
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    for year in range(FILING_START_YEAR, datetime.now(timezone.utc).year + 1):
        start_date = f"{year}0101"
        end_date = min(f"{year}1231", today)
        params: dict[str, Any] = {
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bgn_de": start_date,
            "end_de": end_date,
            "pblntf_ty": "A",  # regular disclosures
            "page_no": 1,
            "page_count": 100,
            "sort": "date",
            "sort_mth": "asc",
        }
        page = 1
        while True:
            params["page_no"] = page
            payload = api_json("list", params)
            all_rows.extend(payload.get("list") or [])
            total_pages = int(payload.get("total_page") or 1)
            if page >= total_pages or not payload.get("list"):
                break
            page += 1

    columns = ["corp_name", "corp_code", "report_nm", "rcept_no", "rcept_dt", "flr_nm", "rm"]
    filings = pd.DataFrame(all_rows)
    if filings.empty:
        filings = pd.DataFrame(columns=columns)
    else:
        filings["report_nm"] = filings.get("report_nm", "").fillna("").astype(str)
        mask = filings["report_nm"].str.contains(r"사업보고서|반기보고서|분기보고서", regex=True)
        filings = filings.loc[mask].copy()
        if "rcept_no" in filings.columns:
            filings = filings.drop_duplicates(subset=["rcept_no"], keep="last")
        filings["dart_url"] = filings.get("rcept_no", "").astype(str).apply(
            lambda no: f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={no}" if no else ""
        )
        sort_cols = [c for c in ["rcept_dt", "rcept_no"] if c in filings.columns]
        if sort_cols:
            filings = filings.sort_values(sort_cols)
    filings.to_csv(RAW_DIR / "filings_2010_onward.csv", index=False, encoding="utf-8-sig")
    return filings


def fetch_financial_report(
    api_key: str, corp_code: str, year: int, report_code: str, errors: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Prefer consolidated statements; fallback to separate statements when absent."""
    file_path = RAW_DIR / f"financial_{year}_{report_code}.json"
    for fs_div in ("CFS", "OFS"):
        try:
            payload = api_json(
                "fnlttSinglAcntAll",
                {
                    "crtfc_key": api_key,
                    "corp_code": corp_code,
                    "bsns_year": str(year),
                    "reprt_code": report_code,
                    "fs_div": fs_div,
                },
            )
            if payload.get("list"):
                payload["_agent_requested_fs_div"] = fs_div
                save_json(file_path, payload)
                return payload
        except DARTError as exc:
            # Invalid/deactivated key or quota errors are fatal; trying each report will not help.
            text = str(exc)
            if any(code in text for code in ("오류 010", "오류 011", "오류 012", "오류 020", "오류 901")):
                raise
            errors.append({"year": year, "report_code": report_code, "fs_div": fs_div, "error": text})
        except requests.RequestException as exc:
            errors.append({"year": year, "report_code": report_code, "fs_div": fs_div, "error": str(exc)})

    # On transient no-data responses, keep a previously fetched local record if present.
    if file_path.exists():
        try:
            old_data = json.loads(file_path.read_text(encoding="utf-8"))
            if old_data.get("list"):
                return old_data
        except (OSError, json.JSONDecodeError):
            pass
    return None


def normalize_account(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def account_value(
    group: pd.DataFrame,
    terms: list[str],
    statements: tuple[str, ...],
    cumulative: bool = False,
) -> float | None:
    """Lookup an account label within relevant statements with cumulative-period support."""
    if group.empty:
        return None
    candidates = group[group["sj_div"].fillna("").astype(str).isin(statements)].copy()
    if candidates.empty:
        candidates = group.copy()
    candidates["_account_norm"] = candidates["account_nm"].apply(normalize_account)
    value_column = "thstrm_add_amount" if cumulative else "thstrm_amount"
    fallback_column = "thstrm_amount" if cumulative else "thstrm_add_amount"
    for term in terms:
        normalized_term = normalize_account(term)
        matches = candidates[candidates["_account_norm"] == normalized_term]
        if matches.empty:
            matches = candidates[candidates["_account_norm"].str.contains(re.escape(normalized_term), na=False)]
        if matches.empty:
            continue
        for column in (value_column, fallback_column):
            for raw in matches[column].tolist():
                parsed = parse_number(raw)
                if parsed is not None:
                    return parsed
    return None


def sum_accounts(
    group: pd.DataFrame, terms: list[str], statements: tuple[str, ...], cumulative: bool = False
) -> float | None:
    """Sum distinct rows matching account labels; avoids double-counting alias terms."""
    if group.empty:
        return None
    candidates = group[group["sj_div"].fillna("").astype(str).isin(statements)].copy()
    if candidates.empty:
        candidates = group.copy()
    candidates["_account_norm"] = candidates["account_nm"].apply(normalize_account)
    normalized_terms = [normalize_account(term) for term in terms]
    exact_mask = candidates["_account_norm"].isin(normalized_terms)
    matched = candidates[exact_mask]
    if matched.empty:
        matched = candidates[candidates["_account_norm"].apply(
            lambda name: any(term and term in name for term in normalized_terms)
        )]
    value_column = "thstrm_add_amount" if cumulative else "thstrm_amount"
    fallback_column = "thstrm_amount" if cumulative else "thstrm_add_amount"
    values: list[float] = []
    seen: set[tuple[str, str]] = set()
    for _, row in matched.iterrows():
        identity = (str(row.get("account_id") or row.get("account_nm") or ""), str(row.get(value_column)))
        if identity in seen:
            continue
        seen.add(identity)
        number = parse_number(row.get(value_column))
        if number is None:
            number = parse_number(row.get(fallback_column))
        if number is not None:
            values.append(number)
    return sum(values) if values else None


def exact_account_value(
    group: pd.DataFrame, terms: list[str], statements: tuple[str, ...], cumulative: bool = False
) -> float | None:
    """Read exact account names only (used for depreciation/amortization to avoid broad matches)."""
    if group.empty:
        return None
    candidates = group[group["sj_div"].fillna("").astype(str).isin(statements)].copy()
    if candidates.empty:
        candidates = group.copy()
    normalized_terms = {normalize_account(term) for term in terms}
    candidates = candidates[candidates["account_nm"].apply(normalize_account).isin(normalized_terms)]
    value_column = "thstrm_add_amount" if cumulative else "thstrm_amount"
    fallback_column = "thstrm_amount" if cumulative else "thstrm_add_amount"
    for column in (value_column, fallback_column):
        for value in candidates[column].tolist():
            parsed = parse_number(value)
            if parsed is not None:
                return parsed
    return None


def period_days(year: int, report_code: str) -> int:
    """Days in the income/cash-flow period represented by each report code."""
    import calendar
    if report_code == "11011":
        return 366 if calendar.isleap(year) else 365
    if report_code == "11012":
        return (pd.Timestamp(year=year, month=6, day=30) - pd.Timestamp(year=year, month=1, day=1)).days + 1
    if report_code == "11013":
        return (pd.Timestamp(year=year, month=3, day=31) - pd.Timestamp(year=year, month=1, day=1)).days + 1
    if report_code == "11014":
        return (pd.Timestamp(year=year, month=9, day=30) - pd.Timestamp(year=year, month=7, day=1)).days + 1
    return 365

def div_pct(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator * 100.0


def build_metrics(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Map disclosed accounts to key amounts and calculate reference financial ratios."""
    metric_rows: list[dict[str, Any]] = []
    if raw_df.empty:
        return pd.DataFrame()

    grouping = ["year", "report_code", "category", "report_type", "fs_div"]
    for (year, report_code, category, report_type, fs_div), group in raw_df.groupby(grouping, dropna=False):
        year, report_code = int(year), str(report_code)
        period_cumulative = category == "half_year"
        # Income statement values: use the YTD amount for half-year reports.
        revenue = account_value(group, ["매출액", "수익(매출액)", "영업수익"], ("IS", "CIS"), period_cumulative)
        cost_of_sales = account_value(group, ["매출원가", "매출원가(손실)"], ("IS", "CIS"), period_cumulative)
        gross_profit = account_value(group, ["매출총이익(손실)", "매출총이익"], ("IS", "CIS"), period_cumulative)
        sga = account_value(group, ["판매비와관리비", "판매비및관리비"], ("IS", "CIS"), period_cumulative)
        operating_income = account_value(group, ["영업이익(손실)", "영업이익"], ("IS", "CIS"), period_cumulative)
        pretax_income = account_value(group, ["법인세비용차감전순이익(손실)", "법인세비용차감전순이익", "법인세비용차감전이익"], ("IS", "CIS"), period_cumulative)
        income_tax = account_value(group, ["법인세비용", "법인세비용(수익)"], ("IS", "CIS"), period_cumulative)
        net_income = account_value(
            group,
            ["당기순이익(손실)", "분기순이익(손실)", "반기순이익(손실)", "당기순이익", "분기순이익", "반기순이익"],
            ("IS", "CIS"), period_cumulative,
        )
        controlling_net_income = account_value(
            group,
            ["지배기업의소유주에게귀속되는당기순이익(손실)", "지배기업의소유주에게귀속되는당기순이익", "지배주주순이익"],
            ("IS", "CIS"), period_cumulative,
        )
        basic_eps = account_value(group, ["기본주당이익(손실)", "기본주당이익"], ("IS", "CIS"), period_cumulative)
        diluted_eps = account_value(group, ["희석주당이익(손실)", "희석주당이익"], ("IS", "CIS"), period_cumulative)
        # Only compute EBITDA when depreciation/amortization rows are disclosed/mapped.
        da_combined = exact_account_value(group, ["감가상각비및무형자산상각비", "감가상각비와무형자산상각비"], ("IS", "CIS", "CF"), period_cumulative)
        depreciation = exact_account_value(group, ["감가상각비", "유형자산감가상각비"], ("IS", "CIS", "CF"), period_cumulative)
        amortization = exact_account_value(group, ["무형자산상각비", "무형자산의상각비"], ("IS", "CIS", "CF"), period_cumulative)
        if da_combined is not None:
            depreciation_amortization = da_combined
            da_data_status = "combined"
        elif depreciation is not None or amortization is not None:
            # Label as partial when only one component is found; this is not a normalized EBITDA.
            depreciation_amortization = (depreciation or 0.0) + (amortization or 0.0)
            da_data_status = "partial" if depreciation is None or amortization is None else "separate"
        else:
            depreciation_amortization = None
            da_data_status = "unavailable"
        ebitda = operating_income + depreciation_amortization if operating_income is not None and depreciation_amortization is not None else None

        # Balance-sheet values are point-in-time balances; do not use cumulative-period fields.
        total_assets = account_value(group, ["자산총계"], ("BS",))
        current_assets = account_value(group, ["유동자산"], ("BS",))
        noncurrent_assets = account_value(group, ["비유동자산"], ("BS",))
        cash = account_value(group, ["현금및현금성자산", "현금및현금성자산및단기금융상품"], ("BS",))
        receivables = account_value(group, ["매출채권", "매출채권및기타채권", "매출채권및계약자산"], ("BS",))
        inventory = account_value(group, ["재고자산"], ("BS",))
        ppe = account_value(group, ["유형자산"], ("BS",))
        accounts_payable = account_value(group, ["매입채무", "매입채무및기타채무"], ("BS",))
        total_liabilities = account_value(group, ["부채총계"], ("BS",))
        current_liabilities = account_value(group, ["유동부채"], ("BS",))
        noncurrent_liabilities = account_value(group, ["비유동부채"], ("BS",))
        total_equity = account_value(group, ["자본총계"], ("BS",))
        short_borrowings = sum_accounts(group, ["단기차입금", "단기차입부채", "유동성장기차입금", "유동성장기부채", "유동성사채", "유동리스부채"], ("BS",))
        long_borrowings = sum_accounts(group, ["장기차입금", "장기차입부채", "비유동리스부채", "장기리스부채"], ("BS",))
        # A broad standalone "사채" account is captured only if it is not already labelled current.
        bond_value = exact_account_value(group, ["사채"], ("BS",))
        if bond_value is not None and long_borrowings is not None:
            long_borrowings += bond_value
        elif bond_value is not None:
            long_borrowings = bond_value
        interest_bearing_debt = None
        if short_borrowings is not None or long_borrowings is not None:
            interest_bearing_debt = (short_borrowings or 0.0) + (long_borrowings or 0.0)
        interest_expense = account_value(group, ["이자비용", "이자원가"], ("IS", "CIS"), period_cumulative)

        cfo = account_value(group, ["영업활동현금흐름", "영업활동으로인한현금흐름", "영업활동으로부터의현금흐름"], ("CF",), period_cumulative)
        cfi = account_value(group, ["투자활동현금흐름", "투자활동으로인한현금흐름", "투자활동으로부터의현금흐름"], ("CF",), period_cumulative)
        cff = account_value(group, ["재무활동현금흐름", "재무활동으로인한현금흐름", "재무활동으로부터의현금흐름"], ("CF",), period_cumulative)
        capex = sum_accounts(group, ["유형자산의취득", "유형자산취득", "무형자산의취득", "무형자산취득"], ("CF",), period_cumulative)
        fcf = cfo - abs(capex) if cfo is not None and capex is not None else None
        net_debt = interest_bearing_debt - cash if interest_bearing_debt is not None and cash is not None else None
        tax_rate = income_tax / pretax_income if income_tax is not None and pretax_income not in (None, 0) else None

        metric_rows.append({
            "year": year, "report_code": report_code, "report_type": report_type,
            "category": category, "fs_div": fs_div, "period_days": period_days(year, report_code),
            "revenue": revenue, "cost_of_sales": cost_of_sales, "gross_profit": gross_profit,
            "selling_general_admin": sga, "operating_income": operating_income,
            "pretax_income": pretax_income, "income_tax_expense": income_tax, "net_income": net_income,
            "controlling_net_income": controlling_net_income, "basic_eps": basic_eps, "diluted_eps": diluted_eps,
            "depreciation": depreciation,
            "amortization": amortization, "depreciation_amortization": depreciation_amortization,
            "ebitda": ebitda, "ebitda_da_status": da_data_status, "total_assets": total_assets,
            "current_assets": current_assets, "noncurrent_assets": noncurrent_assets,
            "cash_and_equivalents": cash, "accounts_receivable": receivables, "inventory": inventory,
            "property_plant_equipment": ppe, "accounts_payable": accounts_payable,
            "total_liabilities": total_liabilities, "current_liabilities": current_liabilities,
            "noncurrent_liabilities": noncurrent_liabilities, "total_equity": total_equity,
            "short_term_borrowings": short_borrowings, "long_term_borrowings": long_borrowings,
            "interest_bearing_debt": interest_bearing_debt, "net_debt": net_debt,
            "interest_expense": interest_expense, "cash_flow_operations": cfo,
            "cash_flow_investing": cfi, "cash_flow_financing": cff,
            "capex_cash_outflow": abs(capex) if capex is not None else None, "free_cash_flow": fcf,
            "effective_tax_rate_pct": div_pct(income_tax, pretax_income),
            "debt_to_equity_pct": div_pct(total_liabilities, total_equity),
            "liabilities_to_assets_pct": div_pct(total_liabilities, total_assets),
            "equity_to_assets_pct": div_pct(total_equity, total_assets),
            "current_ratio_pct": div_pct(current_assets, current_liabilities),
            "quick_ratio_pct": div_pct((current_assets - inventory) if current_assets is not None and inventory is not None else None, current_liabilities),
            "operating_margin_pct": div_pct(operating_income, revenue),
            "net_margin_pct": div_pct(net_income, revenue), "gross_margin_pct": div_pct(gross_profit, revenue),
            "ebitda_margin_pct": div_pct(ebitda, revenue),
            "interest_coverage_x": operating_income / abs(interest_expense)
                if operating_income is not None and interest_expense not in (None, 0) else None,
            "fcf_margin_pct": div_pct(fcf, revenue),
            "cfo_to_net_income_x": cfo / net_income if cfo is not None and net_income not in (None, 0) else None,
            "net_debt_to_ebitda_x": net_debt / ebitda if category == "annual" and net_debt is not None and ebitda not in (None, 0) else None,
        })

    metrics = pd.DataFrame(metric_rows)
    if metrics.empty:
        return metrics
    # Beginning and ending balance alignment: Q3 uses the same year's half-year ending balance;
    # other reports use prior-year annual ending balances. For first available year, use frmtrm.
    metrics["average_assets"] = None
    metrics["average_equity"] = None
    metrics["average_receivables"] = None
    metrics["average_inventory"] = None
    metrics["average_payables"] = None
    metrics["average_invested_capital"] = None
    metrics["nopat"] = None
    metrics["roic_pct"] = None
    raw_group_keys = ["year", "report_code", "category", "report_type", "fs_div"]
    groups = {tuple([int(k[0]), str(k[1]), str(k[2]), str(k[3]), str(k[4])]): g for k, g in raw_df.groupby(raw_group_keys, dropna=False)}
    metric_index = {(int(r.year), str(r.report_code), str(r.fs_div)): i for i, r in metrics.iterrows()}

    def start_balance(row: pd.Series, column: str, raw_terms: list[str]) -> float | None:
        year, code, division = int(row["year"]), str(row["report_code"]), str(row["fs_div"])
        if code == "11014":
            prior_key = (year, "11012", division)
        else:
            prior_key = (year - 1, "11011", division)
        prior_idx = metric_index.get(prior_key)
        if prior_idx is not None:
            value = metrics.at[prior_idx, column]
            if value is not None and pd.notna(value):
                return float(value)
        # Fall back to previous-period account amount in this API response (not ideal, but disclosed).
        key = (year, code, str(row["category"]), str(row["report_type"]), division)
        group = groups.get(key)
        if group is not None:
            # `frmtrm_amount` is a comparative field; choose exact/contained account match.
            norm_names = group["account_nm"].apply(normalize_account)
            for term in raw_terms:
                norm_term = normalize_account(term)
                matches = group[norm_names == norm_term]
                if matches.empty:
                    matches = group[norm_names.str.contains(re.escape(norm_term), na=False)]
                for val in matches.get("frmtrm_amount", pd.Series(dtype=object)).tolist():
                    parsed = parse_number(val)
                    if parsed is not None:
                        return parsed
        return None

    for idx, row in metrics.iterrows():
        for out_col, raw_col, terms in [
            ("average_assets", "total_assets", ["자산총계"]),
            ("average_equity", "total_equity", ["자본총계"]),
            ("average_receivables", "accounts_receivable", ["매출채권", "매출채권및기타채권"]),
            ("average_inventory", "inventory", ["재고자산"]),
            ("average_payables", "accounts_payable", ["매입채무", "매입채무및기타채무"]),
        ]:
            end_value = row[raw_col]
            beginning = start_balance(row, raw_col, terms)
            if end_value is not None and pd.notna(end_value) and beginning is not None:
                metrics.at[idx, out_col] = (float(end_value) + beginning) / 2.0

    # Calculate ratios requiring average balance sheet values and match numerator period to days.
    for idx, row in metrics.iterrows():
        rev, cogs = row["revenue"], row["cost_of_sales"]
        avg_assets, avg_equity = row["average_assets"], row["average_equity"]
        avg_ar, avg_inv, avg_ap = row["average_receivables"], row["average_inventory"], row["average_payables"]
        metrics.at[idx, "roa_pct"] = div_pct(row["net_income"], avg_assets)
        metrics.at[idx, "roe_pct"] = div_pct(row["net_income"], avg_equity)
        metrics.at[idx, "total_assets_turnover_x"] = float(rev) / float(avg_assets) if rev is not None and avg_assets not in (None, 0) and pd.notna(avg_assets) else None
        days = int(row["period_days"])
        metrics.at[idx, "dso_days"] = float(avg_ar) / float(rev) * days if avg_ar is not None and rev not in (None, 0) and pd.notna(avg_ar) else None
        metrics.at[idx, "dio_days"] = float(avg_inv) / float(cogs) * days if avg_inv is not None and cogs not in (None, 0) and pd.notna(avg_inv) else None
        # DPO uses COGS as a purchases proxy when actual credit purchases are not disclosed.
        metrics.at[idx, "dpo_days"] = float(avg_ap) / float(cogs) * days if avg_ap is not None and cogs not in (None, 0) and pd.notna(avg_ap) else None
        metric_vals = [metrics.at[idx, col] for col in ("dso_days", "dio_days", "dpo_days")]
        metrics.at[idx, "ccc_days"] = metric_vals[0] + metric_vals[1] - metric_vals[2] if all(v is not None and pd.notna(v) for v in metric_vals) else None
        debt = row["interest_bearing_debt"]
        assets = row["total_assets"]
        metrics.at[idx, "interest_bearing_debt_to_assets_pct"] = div_pct(debt, assets)
        current_invested = None
        if row["total_equity"] is not None and pd.notna(row["total_equity"]) and row["interest_bearing_debt"] is not None and pd.notna(row["interest_bearing_debt"]) and row["cash_and_equivalents"] is not None and pd.notna(row["cash_and_equivalents"]):
            current_invested = float(row["total_equity"]) + float(row["interest_bearing_debt"]) - float(row["cash_and_equivalents"])
        year, code, division = int(row["year"]), str(row["report_code"]), str(row["fs_div"])
        prior_key = (year, "11012", division) if code == "11014" else (year - 1, "11011", division)
        prior_idx = metric_index.get(prior_key)
        prior_invested = None
        if prior_idx is not None:
            prev = metrics.loc[prior_idx]
            if all(v is not None and pd.notna(v) for v in [prev.get("total_equity"), prev.get("interest_bearing_debt"), prev.get("cash_and_equivalents")]):
                prior_invested = float(prev["total_equity"]) + float(prev["interest_bearing_debt"]) - float(prev["cash_and_equivalents"])
        if current_invested is not None and prior_invested is not None:
            metrics.at[idx, "average_invested_capital"] = (current_invested + prior_invested) / 2.0
        tax_rate = row["effective_tax_rate_pct"]
        # Use only a disclosed, plausible effective tax rate; never assume a statutory rate.
        if row["operating_income"] is not None and tax_rate is not None and pd.notna(tax_rate) and 0 <= float(tax_rate) <= 100:
            metrics.at[idx, "nopat"] = float(row["operating_income"]) * (1.0 - float(tax_rate) / 100.0)
        avg_ic = metrics.at[idx, "average_invested_capital"]
        nopat = metrics.at[idx, "nopat"]
        if nopat is not None and pd.notna(nopat) and avg_ic not in (None, 0) and pd.notna(avg_ic) and float(avg_ic) > 0:
            metrics.at[idx, "roic_pct"] = float(nopat) / float(avg_ic) * 100.0

    # Compare the same filing type and reporting basis with the prior year.
    metrics["revenue_growth_pct"] = None
    lookup: dict[tuple[str, str, int], float | None] = {}
    for idx, row in metrics.sort_values(["report_code", "fs_div", "year"]).iterrows():
        year, code, division = int(row["year"]), str(row["report_code"]), str(row["fs_div"])
        previous = lookup.get((code, division, year - 1))
        revenue = row["revenue"]
        if revenue is not None and pd.notna(revenue) and previous not in (None, 0) and pd.notna(previous):
            metrics.at[idx, "revenue_growth_pct"] = (float(revenue) / float(previous) - 1.0) * 100.0
        lookup[(code, division, year)] = None if pd.isna(revenue) else float(revenue) if revenue is not None else None
    return metrics.sort_values(["year", "report_code", "fs_div"], ascending=[False, True, True]).reset_index(drop=True)

def json_safe_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    safe = frame.astype(object).where(pd.notna(frame), None)
    records = safe.to_dict(orient="records")
    # Convert NumPy scalar types to native JSON values.
    return json.loads(json.dumps(records, ensure_ascii=False, default=str))


def update_dashboard(metrics: pd.DataFrame) -> None:
    template_path = ROOT / "templates" / "dashboard.html"
    index_path = DASHBOARD_DIR / "index.html"
    if not template_path.exists():
        raise FileNotFoundError(f"대시보드 템플릿이 없습니다: {template_path}")
    peers = [
        {"name": "코스모로보틱스", "focus": "웨어러블 의료재활·보행보조·산업용 슈트", "relation": "직접 제품시장 비교 후보", "status": "코스닥 상장(2026-09 자료 기준, 코드 439960)", "url": "https://comp.wisereport.co.kr/company/c1010001.aspx?cmp_cd=439960"},
        {"name": "위로보틱스", "focus": "웨어러블 보행보조·근력보조 로봇", "relation": "직접 제품시장 비교 후보", "status": "비상장 후보·공개자료 범위 확인", "url": "https://wirobotics.career.greetinghr.com/"},
        {"name": "큐렉소", "focus": "수술로봇·보행 재활로봇 Morning Walk", "relation": "의료로봇 인접 비교", "status": "코스닥 상장", "url": "https://www.curexo.com/"},
        {"name": "네오펙트", "focus": "디지털 재활·재활 솔루션", "relation": "재활시장 인접 후보", "status": "상장/최근 공시 확인", "url": "https://opendart.fss.or.kr/"},
        {"name": "로보티즈", "focus": "로봇 액추에이터·서비스 로봇", "relation": "간접 로봇산업 참고기업", "status": "상장/사업영역 차이 유의", "url": "https://www.robotis.com/"},
    ]
    payload = {
        "metrics": json_safe_records(metrics),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "peer_firms": peers,
        "filing_start_year": FILING_START_YEAR,
        "financial_start_year": FINANCIAL_START_YEAR,
    }
    embedded_json = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    embedded_json = embedded_json.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    html = template_path.read_text(encoding="utf-8").replace("__DATA_JSON__", embedded_json)
    index_path.write_text(html, encoding="utf-8")


def main() -> int:
    api_key = os.environ.get("DART_API_KEY", "").strip()
    if not api_key:
        raise DARTError(
            "DART_API_KEY 환경변수가 없습니다. GitHub Settings → Secrets and variables → Actions에 Secret을 등록하세요."
        )
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)

    print("[1/4] Resolve company corp_code...")
    corp_code = fetch_corp_code(api_key)
    print(f"      {COMPANY_NAME}: {corp_code}")

    print("[2/4] Crawl periodic filings from 2010...")
    filings = collect_filings(api_key, corp_code)
    print(f"      filing rows: {len(filings)}")

    print("[3/4] Collect financial statements from 2015...")
    errors: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []
    for year in range(FINANCIAL_START_YEAR, datetime.now(timezone.utc).year + 1):
        for report_code, (category, report_type) in REPORTS.items():
            payload = fetch_financial_report(api_key, corp_code, year, report_code, errors)
            if not payload or not payload.get("list"):
                continue
            fs_div = payload.get("_agent_requested_fs_div", "")
            for item in payload["list"]:
                raw_rows.append(
                    {
                        "year": year, "report_code": report_code, "report_type": report_type,
                        "category": category, "fs_div": item.get("fs_div") or fs_div,
                        "sj_div": item.get("sj_div"), "account_id": item.get("account_id"),
                        "account_detail": item.get("account_detail"), "account_nm": item.get("account_nm"),
                        "thstrm_nm": item.get("thstrm_nm"), "thstrm_dt": item.get("thstrm_dt"),
                        "thstrm_amount": parse_number(item.get("thstrm_amount")),
                        "thstrm_add_amount": parse_number(item.get("thstrm_add_amount")),
                        "frmtrm_nm": item.get("frmtrm_nm"), "frmtrm_amount": parse_number(item.get("frmtrm_amount")),
                        "frmtrm_q_nm": item.get("frmtrm_q_nm"), "frmtrm_q_amount": parse_number(item.get("frmtrm_q_amount")),
                        "bfefrmtrm_nm": item.get("bfefrmtrm_nm"), "bfefrmtrm_amount": parse_number(item.get("bfefrmtrm_amount")),
                        "rcept_no": item.get("rcept_no"),
                    }
                )
    raw_df = pd.DataFrame(raw_rows)
    raw_df.to_csv(PROCESSED_DIR / "financial_data.csv", index=False, encoding="utf-8-sig")
    metrics = build_metrics(raw_df)
    metrics.to_csv(PROCESSED_DIR / "financial_ratios.csv", index=False, encoding="utf-8-sig")
    save_json(RAW_DIR / "collection_errors.json", {"errors": errors, "updated_at": datetime.now(timezone.utc).isoformat()})
    update_dashboard(metrics)

    summary = {
        "corp_code": corp_code,
        "filing_count": int(len(filings)),
        "financial_account_rows": int(len(raw_df)),
        "metric_rows": int(len(metrics)),
        "error_count": len(errors),
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    save_json(RAW_DIR / "last_run.json", summary)
    print("[4/4] Data and dashboard generated.")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if errors:
        print("WARNING: Some report calls returned errors; see data/raw/collection_errors.json", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DARTError, requests.RequestException, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
