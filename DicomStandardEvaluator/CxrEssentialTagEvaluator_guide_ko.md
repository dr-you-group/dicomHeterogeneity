# CXR Essential-Tag Evaluator 사용 가이드 (한글)

X-ray **essential tag** 기준으로 DICOM 메타데이터의 품질을 **series 단위**로 평가하는 도구입니다.
`df_input`(아래 스키마)만 준비하면 다른 연구자도 그대로 돌려볼 수 있습니다.

- 함께 보기: 실행형 노트북 `CxrEssentialTagEvaluator_guide_ko.ipynb`
- 평가기 코드: `Evaluator/CxrEssentialTagEvaluator.py`
- 표준용어(참조): `../files/CxrEssentialTags/CxrEssentialTags_ReferenceSet.xlsx`

---

## 1. 이 도구가 하는 일

기존 `DicomCodeStandardEvaluator`와 두 가지가 다릅니다.

- **IOD / Type 을 고려하지 않습니다.** essential-tag 목록에 있는 모든 태그를 **Type 1**로 간주해
  동일하게 비교합니다. (모달리티별 모듈 subset을 하지 않음)
- **집계 단위가 instance(파일)가 아니라 series 입니다.** 같은 series 안에서 **하나의 instance라도**
  태그/값을 갖거나 표준을 지키면, 그 series는 '있음/준수'로 간주합니다.

---

## 2. 입력: `df_input`

연구자가 준비해야 하는 테이블입니다. **필수 컬럼:**

| 컬럼 | DICOM | 설명 |
|---|---|---|
| `IOD` | (0008,0016) SOP Class UID | IOD (참고용, 매칭엔 미사용) |
| `study_instance_uid` | (0020,000D) | Study Instance UID |
| `series_instance_uid` | (0020,000E) | Series Instance UID — **집계 기준 키** |
| `Manufacturer` | (0008,0070) | 그룹 분석용(옵션) |
| `ScannerModel` | (0008,1090) | 그룹 분석용(옵션) |
| `Tag` | | DICOM Tag (`'00180015'` 형태 권장, `(0018,0015)`·`180015`도 자동 정규화) |
| `AttributeName` | | Attribute Name (없어도 동작) |
| `Value` | | Tag value (문자열) |

- 형식은 **long-format**입니다: 한 행 = (하나의 instance, 하나의 Tag, 그 Value).
- 즉 한 instance가 태그 N개를 가지면 N개 행이 됩니다.
- `Value`가 `"['PA']"`(리스트 문자열)이나 `"PA\LAT"`(DICOM `\` 다중값)이어도 파싱됩니다.

> `df_input` 만드는 방법 예시는 저장소의 `../../characterization_260709.ipynb`
> (S3 long-parquet → df_input 변환)을 참고하세요. **본 가이드는 df_input이 이미 있다고 가정합니다.**

---

## 3. 지표 (모두 series 기준)

| 지표 | 정의 |
|---|---|
| `tag_completeness` | (그 태그가 있는 series) / (전체 series) |
| `value_completeness` | (값이 있는 series) / (태그가 있는 series) |
| `value_conformance` | (CS 값이 표준을 지키는 series) / (CS 값이 있는 series) |

- `value_conformance`는 **`VR == 'CS'` 태그에만** 산출됩니다(그 외 NaN).
- **대-소문자는 pass/fail과 무관**합니다 (`CHEST` == `chest` → PASS).
- 허용값(표준용어)은 참조 파일의 `CS_allowable_values`에서 옵니다.

---

## 4. 실행 (요약)

```python
import sys, pandas as pd
sys.path.append('Evaluator')
from CxrEssentialTagEvaluator import CxrEssentialTagEvaluator

df_standard = pd.read_excel('../files/CxrEssentialTags/CxrEssentialTags_ReferenceSet.xlsx')
evaluator = CxrEssentialTagEvaluator(df_input, df_standard)

# 1) 전체 데이터셋
overall = evaluator.analyze(group_cols=None)

# 2) 그룹별 + 그룹 간 이질성 통계(Mean/Std/CV/Range)
rates, stats = evaluator.analyze_with_stats(group_cols=['Manufacturer'])

# 3) conformance 세부 리포트 (CS 태그)
report = evaluator.conformance_subreport(group_cols=None)   # dict: summary/partial/none
```

---

## 5. 출력 해석

### `analyze()` — 태그별 completeness/conformance
주요 컬럼: `Tag, Attribute Name, VR, total_series, series_with_tag, series_with_value,
series_with_cs_value, series_conform, tag_completeness, value_completeness,
value_conformance, value_diversity`

### `conformance_subreport()` — CS 값 세부 분류 (대소문자 무관)
정확히 일치하지 않는 CS 값을 두 갈래로 나눕니다.

- **partial** — 정확 일치는 아니나 허용값을 **단어로 포함** (예: `CHEST` 여야 하는데 `port chest`)
  → `count`(건수) + value_counts
- **none** — 허용값을 **전혀 포함하지 않음** (예: `banana`)
  → `count` + **`pct`(%)** + value_counts

반환값(dict):
- `report['summary']` : `Tag, Attribute Name, n_values, n_pass, n_partial, n_none, pct_pass, pct_partial, pct_none`
- `report['partial']` / `report['none']` : `Tag, Attribute Name, Defined Values, Value, count, n_series, pct`

> 건수(`count`)·`pct`는 record(=instance) 기준, `n_series`는 참고용 series 수입니다.

---

## 6. 저장 (CSV/Excel)

```python
overall.to_excel('output/cxr_overall_rates.xlsx', index=False)

# conformance 리포트 3종: *_summary.csv / *_partial.csv / *_none.csv
evaluator.export_conformance_subreport('output/cxr_conformance', group_cols=None)

# (요약) 미준수 unique value 통합 CSV
evaluator.export_unconformed_values('output/cxr_unconformed_values.csv')
```

---

## 7. 자주 묻는 것

- **Q. Tag 형식을 8자리로 맞춰야 하나요?**
  A. 권장은 `'00180015'`이지만 `(0018,0015)`, `180015`도 내부에서 자동 정규화됩니다.
- **Q. `value_conformance`가 전부 NaN이에요.**
  A. 해당 태그가 CS가 아니거나(정상), 그 태그에 값이 있는 series가 0인 경우입니다.
- **Q. Manufacturer/ScannerModel 그룹 통계가 무의미해요.**
  A. 데이터가 비식별화되어 값이 비어 있으면 그룹이 사실상 1개가 됩니다. 값이 보존된 데이터에서 의미가 있습니다.
- **Q. 표준 허용값을 바꾸고 싶어요.**
  A. `CxrEssentialTags_ReferenceSet.xlsx`의 `CS_allowable_values`를 수정하거나,
     `DicomStandardRetrieval/build_cxr_essential_reference.py`로 재생성하세요.
