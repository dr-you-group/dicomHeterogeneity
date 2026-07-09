import ast
import re
import numpy as np
import pandas as pd


class CxrEssentialTagEvaluator:
    """
    X-ray essential-tag 기준의 series-level DICOM 품질 평가기.

    기존 DicomCodeStandardEvaluator와의 차이:
      - IOD / Type을 고려하지 않음: df_standard(essential tags)에 포함된 모든 태그를
        Type 1로 간주하고 동일하게 비교.
      - 집계 단위가 instance(file)가 아니라 series.
        같은 series 안에서 하나의 instance만 태그/값을 갖거나 표준을 지켜도
        해당 series는 '있음/준수'로 간주.

    Metrics (모두 series 기준):
      - tag_completeness   = (태그가 있는 series) / (전체 series)
      - value_completeness = (값이 있는 series)   / (태그가 있는 series)
      - value_conformance  = (CS 값이 표준을 지키는 series) / (CS 값이 있는 series)
                             (VR == 'CS' 인 태그에 대해서만 산출, 그 외에는 NaN)

    df_metadata (INPUT) 필수 컬럼:
      - IOD                  : (0008,0016) SOP Class UID 기반 IOD (참고용, 매칭엔 미사용)
      - study_instance_uid   : (0020,000D) Study Instance UID
      - series_instance_uid  : (0020,000E) Series Instance UID   <- 집계 기준 키
      - Manufacturer         : (0008,0070) Manufacturer          (group_cols 옵션)
      - ScannerModel         : (0008,1090) Manufacturer's Model Name (group_cols 옵션)
      - Tag                  : DICOM Tag
      - AttributeName        : Attribute Name
      - Value                : Tag value

    df_standard (essential tags) 필수 컬럼:
      - Tag, Attribute Name, VR
      - CS_allowable_values : CS 태그의 허용값 리스트("['AP','PA',...]" 형태의
        list-string / list). 없으면 Standard Terms 를 사용.
      - Standard Terms (대안): "{'Enumerated Values': [...]}" 또는
        "{'Defined Terms': [...]}" 형태의 dict / dict-string.

    conformance 규칙:
      - VR == 'CS' 인 태그에 대해서만 산출.
      - 대-소문자는 pass/fail 과 무관 (예: 'CHEST' == 'chest' -> PASS).
    """

    SERIES_COL = "series_instance_uid"

    def __init__(self, df_metadata, df_standard, series_col=SERIES_COL):
        self.series_col = series_col
        self.df_standard = self._prepare_standard(df_standard)
        self.df_metadata = self._prepare_metadata(df_metadata)

    # ------------------------------------------------------------------ #
    # preparation
    # ------------------------------------------------------------------ #
    @staticmethod
    def _norm_tag(tag):
        """Tag를 8자리 대문자 hex 문자열로 정규화 ('(0018,0015)', 180015, '00180015' -> '00180015')."""
        if pd.isna(tag):
            return tag
        s = re.sub(r"[^0-9A-Fa-f]", "", str(tag))
        return s.upper().zfill(8)

    def _prepare_standard(self, df_standard):
        df = df_standard.copy()
        df["Tag"] = df["Tag"].map(self._norm_tag)
        df = df.drop_duplicates(subset=["Tag"], keep="first").reset_index(drop=True)
        df["_valid_values"] = df.apply(self._row_valid_values, axis=1)
        # 대-소문자 무관 비교를 위한 소문자 집합
        df["_valid_lower"] = df["_valid_values"].map(
            lambda vs: {v.lower() for v in vs}
        )
        return df

    @classmethod
    def _row_valid_values(cls, row):
        """CS_allowable_values 우선, 없으면 Standard Terms 에서 허용값 집합 추출."""
        if "CS_allowable_values" in row.index:
            vals = cls._parse_allowable(row.get("CS_allowable_values"))
            if vals:
                return vals
        return cls._extract_valid_values(row.get("Standard Terms"))

    @staticmethod
    def _parse_allowable(cell):
        """CS_allowable_values(list 또는 list-string)를 정규화된 집합으로 파싱 (빈값 제거)."""
        if cell is None or (isinstance(cell, float) and pd.isna(cell)):
            return set()
        if isinstance(cell, (list, tuple, set)):
            seq = cell
        else:
            try:
                seq = ast.literal_eval(str(cell))
            except (ValueError, SyntaxError):
                seq = []
        return {str(v).strip() for v in seq if str(v).strip() != ""}

    def _prepare_metadata(self, df_metadata):
        df = df_metadata.copy()
        df["Tag"] = df["Tag"].map(self._norm_tag)
        df["Value"] = df["Value"].astype("object")
        return df

    @staticmethod
    def _extract_valid_values(standard_terms):
        """Standard Terms(dict 또는 dict-string)에서 표준 용어 집합 추출."""
        valid = set()
        parsed = standard_terms
        if isinstance(standard_terms, str):
            try:
                parsed = ast.literal_eval(standard_terms)
            except (ValueError, SyntaxError):
                parsed = None
        if isinstance(parsed, dict):
            for key in ("Enumerated Values", "Defined Terms"):
                vals = parsed.get(key, [])
                if isinstance(vals, (list, tuple, set)):
                    valid.update(str(v).strip() for v in vals)
        return valid

    # ------------------------------------------------------------------ #
    # value helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_tokens(value):
        """Value를 토큰 리스트로 파싱. "['PA']" / "PA" / "PA\\LAT" 등 처리."""
        if pd.isna(value):
            return []
        s = str(value).strip()
        if s == "" or s == "[]":
            return []
        try:
            parsed = ast.literal_eval(s)
            if isinstance(parsed, (list, tuple)):
                return [str(p).strip() for p in parsed if str(p).strip() != ""]
        except (ValueError, SyntaxError):
            pass
        # DICOM multi-value delimiter fallback
        if "\\" in s:
            return [p.strip() for p in s.split("\\") if p.strip() != ""]
        return [s]

    def _empty_value_mask(self, series):
        s = series.astype("object")
        as_str = s.astype(str).str.strip()
        return s.isna() | (as_str == "") | (as_str == "[]") | (as_str == "nan")

    @staticmethod
    def _word_tokens(value):
        """value를 소문자 단어 토큰으로 분리. 'port chest' -> ['port','chest']."""
        return [t for t in re.split(r"[^0-9A-Za-z]+", str(value).lower()) if t]

    def _value_conforms(self, value, valid_lower):
        """단일 instance value가 표준을 지키면 True.
        DICOM 다중값('\\') 각 부분이 (대-소문자 무관) 허용값에 속하면 PASS."""
        tokens = self._parse_tokens(value)
        if not tokens:
            return False
        return all(t.lower() in valid_lower for t in tokens)

    def _classify_value(self, value, valid_lower):
        """비어있지 않은 value를 conformance 관점에서 분류.
          - 'pass'    : (대-소문자 무관) 정확히 허용값과 일치
          - 'partial' : 정확히 일치하진 않지만 허용값을 단어로 포함 ('port chest' ⊇ 'chest')
          - 'none'    : 허용값을 전혀 포함하지 않음
        """
        if self._value_conforms(value, valid_lower):
            return "pass"
        tokens = set(self._word_tokens(value))
        if tokens & valid_lower:
            return "partial"
        return "none"

    # ------------------------------------------------------------------ #
    # core: one group
    # ------------------------------------------------------------------ #
    def _analyze_one_group(self, df, group_id):
        scol = self.series_col
        total_series = df[scol].nunique()
        if total_series == 0:
            return pd.DataFrame()

        empty_mask = self._empty_value_mask(df["Value"])
        rows = []
        for _, std_row in self.df_standard.iterrows():
            tag = std_row["Tag"]
            vr = std_row.get("VR")
            valid_lower = std_row["_valid_lower"]

            tag_mask = df["Tag"] == tag
            series_with_tag = df.loc[tag_mask, scol].nunique()
            tag_completeness = series_with_tag / total_series

            value_mask = tag_mask & (~empty_mask)
            series_with_value = df.loc[value_mask, scol].nunique()
            value_completeness = (
                series_with_value / series_with_tag if series_with_tag > 0 else np.nan
            )

            # conformance: CS 태그에 한해 series 단위 (하나라도 지키면 준수)
            series_with_cs_value = 0
            series_conform = 0
            value_conformance = np.nan
            if vr == "CS" and valid_lower and series_with_value > 0:
                sub = df.loc[value_mask, [scol, "Value"]].copy()
                sub["_conf"] = sub["Value"].map(
                    lambda v: self._value_conforms(v, valid_lower)
                )
                per_series = sub.groupby(scol)["_conf"].any()
                series_with_cs_value = per_series.shape[0]
                series_conform = int(per_series.sum())
                value_conformance = (
                    series_conform / series_with_cs_value
                    if series_with_cs_value > 0 else np.nan
                )

            series_diversity = df.loc[value_mask, "Value"].map(
                lambda v: tuple(self._parse_tokens(v))
            )
            n_unique_values = series_diversity[series_diversity.map(bool)].nunique()

            row = {
                "Tag": tag,
                "Attribute Name": std_row.get("Attribute Name"),
                "VR": vr,
                "total_series": total_series,
                "series_with_tag": series_with_tag,
                "series_with_value": series_with_value,
                "series_with_cs_value": series_with_cs_value,
                "series_conform": series_conform,
                "tag_completeness": tag_completeness,
                "value_completeness": value_completeness,
                "value_conformance": value_conformance,
                "value_diversity": n_unique_values,
            }
            row.update(group_id)
            rows.append(row)
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------ #
    # public: analyze
    # ------------------------------------------------------------------ #
    def analyze(self, group_cols=None):
        """
        series-level 태그 품질 분석.
        :param group_cols: None 이면 전체 데이터셋 1개 그룹.
                           예) ['Manufacturer'], ['Manufacturer', 'ScannerModel'],
                               ['IOD', 'study_instance_uid'] 등.
        :return: rates DataFrame
        """
        if not group_cols:
            return self._analyze_one_group(self.df_metadata, {}).reset_index(drop=True)

        results = []
        for keys, gdf in self.df_metadata.groupby(group_cols, dropna=False):
            if not isinstance(keys, tuple):
                keys = (keys,)
            group_id = dict(zip(group_cols, keys))
            res = self._analyze_one_group(gdf, group_id)
            if not res.empty:
                results.append(res)
        if not results:
            return pd.DataFrame()
        return pd.concat(results, ignore_index=True)

    def analyze_with_stats(self, group_cols):
        """
        그룹별 series-level metric 산출 후, 그룹 간 이질성 통계(Mean/Std/CV/Range) 계산.
        :return: (rates_df, stats_df)
        """
        rates_df = self.analyze(group_cols=group_cols)
        metric_cols = ["tag_completeness", "value_completeness", "value_conformance"]

        stats_list = []
        for tag, group in rates_df.groupby("Tag"):
            for metric in metric_cols:
                vals = group[metric].dropna()
                mean = vals.mean()
                cv = (vals.std() / mean * 100) if (pd.notna(mean) and mean != 0) else np.nan
                stats_list.append({
                    "Tag": tag,
                    "Attribute Name": group["Attribute Name"].iloc[0],
                    "VR": group["VR"].iloc[0],
                    "Metric": metric,
                    "Mean": mean,
                    "Std": vals.std(),
                    "CV(%)": cv,
                    "Min": vals.min(),
                    "Max": vals.max(),
                    "Range": (vals.max() - vals.min()) if len(vals) else np.nan,
                    "n_groups": len(group),
                    "n_groups_valid": len(vals),
                })
        return rates_df, pd.DataFrame(stats_list)

    # ------------------------------------------------------------------ #
    # public: CS value classification (pass / partial / none)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _format_tag(tag8):
        return f"({tag8[:4]},{tag8[4:]})" if isinstance(tag8, str) and len(tag8) == 8 else tag8

    def _classify_records(self, group_cols=None):
        """비어있지 않은 CS record 각각에 category(pass/partial/none)를 부여해 반환.

        category:
          - 'pass'    : 대-소문자 무관 정확 일치
          - 'partial' : 정확 일치는 아니나 허용값을 단어로 포함 ('port chest' ⊇ 'chest')
          - 'none'    : 허용값을 전혀 포함하지 않음
        반환 컬럼: [series_instance_uid, Tag, Attribute Name, Defined Values,
                    Value, category] (+ group_cols)
        """
        scol = self.series_col
        df = self.df_metadata
        empty_mask = self._empty_value_mask(df["Value"])
        gcols = [c for c in (group_cols or []) if c in df.columns]

        cs_std = self.df_standard[self.df_standard["VR"] == "CS"]
        frames = []
        for _, std_row in cs_std.iterrows():
            tag = std_row["Tag"]
            valid_lower = std_row["_valid_lower"]
            if not valid_lower:
                continue
            tag_mask = (df["Tag"] == tag) & (~empty_mask)
            if not tag_mask.any():
                continue
            sub = df.loc[tag_mask, [scol, "Value"] + gcols].copy()
            sub["Tag"] = self._format_tag(tag)
            sub["Attribute Name"] = std_row.get("Attribute Name")
            sub["Defined Values"] = repr(sorted(std_row["_valid_values"]))
            sub["category"] = sub["Value"].map(
                lambda v: self._classify_value(v, valid_lower)
            )
            frames.append(sub)

        cols = [scol, "Tag", "Attribute Name", "Defined Values", "Value",
                "category"] + gcols
        if not frames:
            return pd.DataFrame(columns=cols)
        return pd.concat(frames, ignore_index=True)[cols]

    def conformance_subreport(self, group_cols=None):
        """
        CS 값의 conformance 세부 리포트.

        :return: dict
          - 'summary' : Tag(+group)별 record 건수/비율
              [Tag, Attribute Name, (group_cols), n_values,
               n_pass, n_partial, n_none, pct_pass, pct_partial, pct_none]
          - 'partial' : 정확히 일치하진 않지만 허용값을 포함하는 값의 value_counts
              [Tag, Attribute Name, (group_cols), Defined Values, Value, count, n_series, pct]
          - 'none'    : 허용값을 전혀 포함하지 않는 값의 value_counts
              [Tag, Attribute Name, (group_cols), Defined Values, Value, count, n_series, pct]
        건수(count) 및 pct 는 record(=instance) 기준, n_series 는 참고용 series 수.
        pct 는 해당 Tag(+group)의 전체 비어있지 않은 CS record 대비 비율(%).
        """
        scol = self.series_col
        gcols = [c for c in (group_cols or []) if c in self.df_metadata.columns]
        recs = self._classify_records(group_cols=gcols)
        key = ["Tag", "Attribute Name"] + gcols

        empty_summary_cols = key + ["n_values", "n_pass", "n_partial", "n_none",
                                    "pct_pass", "pct_partial", "pct_none"]
        empty_detail_cols = key + ["Defined Values", "Value", "count", "n_series", "pct"]
        if recs.empty:
            return {"summary": pd.DataFrame(columns=empty_summary_cols),
                    "partial": pd.DataFrame(columns=empty_detail_cols),
                    "none": pd.DataFrame(columns=empty_detail_cols)}

        # --- summary (record 기준) ---
        counts = (recs.groupby(key + ["category"]).size()
                  .unstack("category", fill_value=0).reset_index())
        for c in ("pass", "partial", "none"):
            if c not in counts.columns:
                counts[c] = 0
        counts["n_values"] = counts[["pass", "partial", "none"]].sum(axis=1)
        summary = counts.rename(columns={"pass": "n_pass", "partial": "n_partial",
                                          "none": "n_none"})
        for c in ("pass", "partial", "none"):
            summary[f"pct_{c}"] = (summary[f"n_{c}"] / summary["n_values"] * 100).round(2)
        summary = summary[empty_summary_cols].sort_values(
            ["pct_none", "pct_partial"], ascending=False).reset_index(drop=True)

        # tag(+group)별 전체 건수 (pct 분모)
        totals = recs.groupby(key).size().rename("n_values").reset_index()

        def _detail(cat):
            part = recs[recs["category"] == cat]
            if part.empty:
                return pd.DataFrame(columns=empty_detail_cols)
            agg = (part.groupby(key + ["Defined Values", "Value"])
                   .agg(count=("Value", "size"),
                        n_series=(scol, "nunique")).reset_index())
            agg = agg.merge(totals, on=key, how="left")
            agg["pct"] = (agg["count"] / agg["n_values"] * 100).round(2)
            agg = agg.drop(columns=["n_values"])
            return agg[empty_detail_cols].sort_values(
                key + ["count"], ascending=[True] * len(key) + [False]
            ).reset_index(drop=True)

        return {"summary": summary, "partial": _detail("partial"), "none": _detail("none")}

    def export_conformance_subreport(self, out_prefix, group_cols=None):
        """conformance_subreport 결과를 CSV 3개로 저장.
        생성 파일: {out_prefix}_summary.csv / _partial.csv / _none.csv
        :return: subreport dict
        """
        rep = self.conformance_subreport(group_cols=group_cols)
        for name, dfr in rep.items():
            dfr.to_csv(f"{out_prefix}_{name}.csv", index=False, encoding="utf-8-sig")
        return rep

    def unconformed_values(self, group_cols=None):
        """
        (기존 요구) CS 태그별로 표준용어에 정확히 일치하지 않는(=미준수) unique value 정리.
        partial + none 을 모두 포함. 대-소문자 무관.
        :return: columns = [Tag, Attribute Name, Defined Values, Unconformed Value]
                 (+ group_cols, category, n_series, count)
        """
        rep = self.conformance_subreport(group_cols=group_cols)
        parts = []
        for cat in ("partial", "none"):
            dfr = rep[cat].copy()
            if not dfr.empty:
                dfr.insert(0, "category", cat)
                parts.append(dfr)
        gcols = [c for c in (group_cols or []) if c in self.df_metadata.columns]
        base_cols = ["Tag", "Attribute Name", "Defined Values", "Unconformed Value"]
        out_cols = base_cols + gcols + ["category", "count", "n_series"]
        if not parts:
            return pd.DataFrame(columns=out_cols)
        out = pd.concat(parts, ignore_index=True).rename(
            columns={"Value": "Unconformed Value"})
        return out[[c for c in out_cols if c in out.columns]]

    def export_unconformed_values(self, path, group_cols=None):
        """unconformed_values 결과를 CSV로 저장."""
        dfu = self.unconformed_values(group_cols=group_cols)
        dfu.to_csv(path, index=False, encoding="utf-8-sig")
        return dfu
