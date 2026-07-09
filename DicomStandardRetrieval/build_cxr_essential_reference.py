"""
Build the CXR essential-tag reference set used by ``CxrEssentialTagEvaluator``.

Unlike the modality-specific reference sets under ``files/DicomStandardReference_*``,
this reference is a flat list of X-ray *essential* tags:

- It ignores IOD and DICOM Type. Every essential tag is treated as Type 1.
- For the CS tags it carries the allowable value set, so value conformance can be
  evaluated.

Source of the allowable values
------------------------------
``cxr-metadata-field_260709.xlsx`` column ``CS_allowable_values`` (a list-string,
e.g. "['AP', 'PA', 'LL', ...]"). This is the single source of truth for the CS
standard terms; empty entries are dropped.

The output reference stores the allowable values under both ``CS_allowable_values``
(verbatim) and ``Standard Terms`` (as "{'Defined Terms': [...]}") so downstream code
that expects either convention works.

Output
------
``files/CxrEssentialTags/CxrEssentialTags_ReferenceSet.xlsx``
"""

import ast
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, os.pardir))

ESSENTIAL_XLSX = os.environ.get(
    "CXR_ESSENTIAL_XLSX",
    os.path.abspath(os.path.join(REPO, os.pardir, "cxr-metadata-field_260709.xlsx")),
)
OUT_DIR = os.path.join(REPO, "files", "CxrEssentialTags")
OUT_XLSX = os.path.join(OUT_DIR, "CxrEssentialTags_ReferenceSet.xlsx")


def _norm_tag(tag) -> str:
    s = str(tag).strip()
    for ch in "(),​ ":
        s = s.replace(ch, "")
    return s.upper().zfill(8)


def _parse_allowable(cell) -> list:
    """Parse a CS_allowable_values list-string into a clean list (empties dropped)."""
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return []
    if isinstance(cell, (list, tuple)):
        seq = cell
    else:
        try:
            seq = ast.literal_eval(str(cell))
        except (ValueError, SyntaxError):
            seq = []
    return [str(v).strip() for v in seq if str(v).strip() != ""]


def build(essential_xlsx=ESSENTIAL_XLSX, out_xlsx=OUT_XLSX) -> pd.DataFrame:
    df = pd.read_excel(essential_xlsx)
    df["Tag"] = df["Tag"].apply(_norm_tag)
    df["Type"] = "1"  # IOD/Type is not considered: every essential tag is Type 1.

    allow = df.get("CS_allowable_values")
    parsed = allow.map(_parse_allowable) if allow is not None else None

    # Normalized, de-duplicated allowable list per CS tag.
    df["CS_allowable_values"] = (
        parsed.map(lambda vs: sorted(dict.fromkeys(vs))) if parsed is not None else None
    )
    # Mirror into the generic Standard Terms convention.
    df["Standard Terms"] = df.apply(
        lambda r: repr({"Defined Terms": r["CS_allowable_values"]})
        if r["VR"] == "CS" and r["CS_allowable_values"] else None,
        axis=1,
    )

    missing = df[(df["VR"] == "CS") & (df["Standard Terms"].isna())]
    if len(missing):
        raise ValueError(
            "CS tags without allowable values: "
            + ", ".join(f"{r.Tag} {r['Attribute Name']}" for _, r in missing.iterrows())
        )

    cols = ["Tag", "Attribute Name", "Keyword", "VR", "VM", "Type",
            "CS_allowable_values", "Standard Terms", "Description",
            "event_table", "event_value_field", "event_value_field_type"]
    cols = [c for c in cols if c in df.columns]
    df = df[cols]

    os.makedirs(os.path.dirname(out_xlsx), exist_ok=True)
    df.to_excel(out_xlsx, index=False)
    return df


if __name__ == "__main__":
    out = build()
    n_cs = (out["VR"] == "CS").sum()
    print(f"Wrote {OUT_XLSX}")
    print(f"  {len(out)} essential tags ({n_cs} CS tags with allowable values)")
    for _, r in out[out["VR"] == "CS"].iterrows():
        print(f"  {r['Tag']} {r['Attribute Name']:<28} {len(r['CS_allowable_values'])} values")
