# dicomHeterogeneity

## 🚀 Fastest Way to Try This: CXR Essential-Tag Pipeline (One Notebook)

Just clone this repo and run a single notebook — no other setup beyond editing a few path variables.

```bash
git clone https://github.com/dr-you-group/dicomHeterogeneity.git
```

Then open `example/cxr_essential_tag_pipeline.ipynb` (Korean guide: `example/cxr_essential_tag_pipeline_document.docx`) —
or the English version, `example/cxr_essential_tag_pipeline_eng.ipynb`
(guide: `example/cxr_essential_tag_pipeline_document_eng.docx`) — in Jupyter, edit the path
variables in the first "user configuration" cell, and run all cells top to bottom.
The notebook takes a raw CXR DICOM folder straight to the 5 final quality-evaluation CSV files.

This project evaluates how closely real-world DICOM metadata conforms to the DICOM standard and quantifies heterogeneity across institutions and manufacturers. It compares actual metadata against standard references (2025c/2014c) to compute tag presence, value presence, standardization rate, and value diversity.

## Structure

- `DicomStandardEvaluator/`
  - `DicomStandardEvaluator_example.ipynb`: evaluation walkthrough (IOD/instance-based)
  - `CxrEssentialTagEvaluator_example.ipynb`: X-ray essential-tag, series-level walkthrough
  - `Evaluator/`
    - `DicomCodeStandardEvaluator.py`: main evaluator class (IOD/Type, instance-level)
    - `DicomCodeStandardEvaluator_withoutVR.py`: evaluator variant without VR
    - `CxrEssentialTagEvaluator.py`: X-ray essential-tag, **series-level, IOD-free** evaluator
    - `DicomCodeStandardEvaluator.md`: class description
- `DicomStandardRetrieval/`
  - `DicomStandardRetrieval_2014c.ipynb`: 2014c reference processing
  - `build_cxr_essential_reference.py`: build the CXR essential-tag reference set
- `files/`
  - `DicomStandardReference_2014c/`: 2014c reference Excel files
  - `DicomStandardReference_2025c/`: 2025c reference Excel files
  - `CxrEssentialTags/`: X-ray essential-tag reference set (with CS allowable values)

## CXR Essential-Tag Evaluator (series-level, IOD-free)

`CxrEssentialTagEvaluator` evaluates real-world DICOM metadata against a flat list of
X-ray **essential tags** (`files/CxrEssentialTags/CxrEssentialTags_ReferenceSet.xlsx`),
differing from `DicomCodeStandardEvaluator` in two ways:

- **IOD / Type are ignored** — every essential tag is treated as Type 1 and compared
  uniformly (no per-IOD standard subsetting).
- **The unit of aggregation is the series**, not the instance. Within a series, if even
  one instance has the tag / a value / a conforming value, that series counts as
  present / valued / conforming.

### Input schema (`df_dataset`)

`IOD` (0008,0016), `study_instance_uid` (0020,000D),
`series_instance_uid` (0020,000E) *(aggregation key)*,
`Manufacturer` (0008,0070), `ScannerModel` (0008,1090),
`Tag`, `AttributeName`, `Value`.

### Metrics (all series-level)

- `tag_completeness`   = (series with tag) / (total series)
- `value_completeness` = (series with value) / (series with tag)
- `value_conformance`  = (series whose CS value conforms) / (series with CS value),
  computed for `VR == 'CS'` tags only. **Comparison is case-insensitive**
  (`CHEST` == `chest` → PASS). Allowable values come from the reference set's
  `CS_allowable_values` (sourced from `cxr-metadata-field_260709.xlsx`).

### Conformance sub-report

`conformance_subreport()` splits non-exact CS values into two buckets:

- **partial** — not an exact match but *contains* an allowable term as a word
  (e.g. expected `CHEST`, got `port chest`): count + `value_counts`.
- **none** — contains no allowable term at all: count + percentage + `value_counts`.

`export_conformance_subreport(prefix)` writes `*_summary.csv`, `*_partial.csv`,
`*_none.csv`. `export_unconformed_values(path)` writes the combined
`Tag, Attribute Name, Defined Values, Unconformed Value` CSV.

### Example

```python
from CxrEssentialTagEvaluator import CxrEssentialTagEvaluator

df_standard = pd.read_excel('files/CxrEssentialTags/CxrEssentialTags_ReferenceSet.xlsx')
evaluator = CxrEssentialTagEvaluator(df_dataset, df_standard)

overall = evaluator.analyze(group_cols=None)                    # whole dataset
rates, stats = evaluator.analyze_with_stats(['Manufacturer'])   # per-group + heterogeneity
report = evaluator.conformance_subreport()                      # summary / partial / none
```

See `DicomStandardEvaluator/CxrEssentialTagEvaluator_example.ipynb`.

## Quick Start

1. Prepare a Python environment
   - Recommended packages: `pandas`, `numpy`, `openpyxl`, `pyarrow`
2. Load standard references
   - Use the Excel files under `files/DicomStandardReference_2025c/`
3. Load metadata
   - Provide metadata as Parquet or a DataFrame
4. Run evaluation
   - See `DicomStandardEvaluator/DicomStandardEvaluator_example.ipynb`

## Input Schema

`df_metadata` (real-world DICOM metadata) required columns:
- `study_id`, `series_id`, `file_id`
- `IOD`: IOD derived from SOP Class UID
- `Tag`: DICOM Tag
- `Value`: Tag value
- `AttributeName` (recommended)
- `Manufacturer`, `ScannerModel` (optional)

`df_standard` (DICOM standard definition) required columns:
- `IOD`, `Tag`, `Attribute Name`, `Type`, `Type_Group`
- `Standard Terms` (Enumerated/Defined Terms)

## Key Metrics

- Tag presence rate: fraction of files where a tag exists
- Value presence rate: fraction of files with a value when the tag exists
- Value standardization rate: fraction matching Enumerated/Defined Terms
- Value diversity: number of unique values

## Example

```python
from Evaluator.DicomCodeStandardEvaluator import DicomCodeStandardEvaluator

evaluator = DicomCodeStandardEvaluator(df_metadata, df_standard)
rates_df, stats_df = evaluator.analyze_rates_with_stats(
    group_cols=['IOD', 'study_id']
)
```

## Reference

- DICOM standard: https://dicom.nema.org/medical/dicom/current/output/chtml/
