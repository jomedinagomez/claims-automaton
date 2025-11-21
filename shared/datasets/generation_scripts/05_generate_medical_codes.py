#!/usr/bin/env python3
"""Emit medical_codes.csv seeded from PLAN.md plus deterministic ICD-10-style synths."""

from __future__ import annotations

import argparse
import csv
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

MedicalCode = Tuple[str, str, str, int, int, bool, str]


BASE_CODES: List[MedicalCode] = [
    ("K35.80", "Unspecified acute appendicitis", "surgery", 8000, 15000, True, "Emergency appendectomy"),
    ("S72.001A", "Fracture of unspecified part of neck of right femur", "orthopedic", 25000, 50000, True, "Hip fracture surgery"),
    ("I21.9", "Acute myocardial infarction unspecified", "cardiac", 30000, 75000, True, "Heart attack treatment"),
    ("M17.11", "Unilateral primary osteoarthritis right knee", "orthopedic", 15000, 35000, True, "Knee replacement"),
    ("Z00.00", "General adult medical examination", "preventive", 200, 500, True, "Routine checkup"),
    ("J44.1", "COPD with exacerbation", "respiratory", 5000, 12000, True, "COPD treatment"),
    ("E11.9", "Type 2 diabetes mellitus without complications", "chronic", 800, 4500, True, "Ongoing management"),
    ("C50.911", "Malignant neoplasm right female breast", "oncology", 50000, 150000, False, "Cancer treatment"),
    ("S13.4XXA", "Sprain of ligaments of cervical spine", "orthopedic", 3000, 7500, True, "Whiplash care"),
    ("T14.90XA", "Injury unspecified", "trauma", 2000, 8000, True, "General trauma evaluation"),
    ("S06.0X1A", "Concussion with loss of consciousness", "neurology", 4000, 9000, True, "Concussion monitoring"),
    ("G81.91", "Hemiplegia affecting unspecified side", "neurology", 45000, 90000, False, "Stroke rehab"),
    ("S82.201A", "Unspecified fracture of shaft of right tibia", "orthopedic", 12000, 28000, True, "Tibia fracture fixation"),
    ("N18.6", "End stage renal disease", "renal", 60000, 120000, False, "Dialysis + transplant prep"),
    ("F10.239", "Alcohol dependence with withdrawal", "behavioral", 8000, 16000, True, "Inpatient detox"),
    ("O82", "Encounter for cesarean delivery", "obstetrics", 18000, 35000, True, "C-section"),
    ("A41.9", "Sepsis, unspecified", "infectious", 25000, 60000, False, "Severe sepsis care"),
    ("S27.2XXA", "Traumatic pneumothorax", "trauma", 15000, 32000, True, "Chest tube + ICU"),
    ("K80.20", "Calculus of gallbladder", "surgery", 12000, 25000, True, "Laparoscopic cholecystectomy"),
    ("Z51.11", "Encounter for antineoplastic chemotherapy", "oncology", 20000, 60000, False, "Chemo session"),
]


@dataclass(frozen=True)
class MedicalTemplate:
    icd_prefix: str
    description: str
    category: str
    cost_min: int
    cost_max: int
    notes: str
    common: bool
    needs_encounter_suffix: bool = False


MEDICAL_TEMPLATES: Tuple[MedicalTemplate, ...] = (
    MedicalTemplate("S83.201A", "Bucket-handle tear medial meniscus right knee", "orthopedic", 6500, 18000, "Arthroscopic repair", True, False),
    MedicalTemplate("S83.211A", "Bucket-handle tear lateral meniscus right knee", "orthopedic", 6200, 17500, "Arthroscopic meniscectomy", True, False),
    MedicalTemplate("M25.561", "Pain in right knee", "orthopedic", 800, 3500, "PT evaluation recommended", True, False),
    MedicalTemplate("M23.205", "Derangement of meniscus due to old tear", "orthopedic", 4500, 12000, "Chronic meniscal pathology", True, False),
    MedicalTemplate("K40.90", "Unilateral inguinal hernia without obstruction", "surgery", 9500, 18000, "Laparoscopic mesh repair", True, False),
    MedicalTemplate("K40.20", "Bilateral inguinal hernia without obstruction", "surgery", 12000, 26000, "Bilateral mesh reinforcement", False, False),
    MedicalTemplate("K43.9", "Ventral hernia without obstruction", "surgery", 11000, 24000, "Open hernia repair", True, False),
    MedicalTemplate("K42.9", "Umbilical hernia without obstruction", "surgery", 7500, 16000, "Primary closure or mesh", True, False),
    MedicalTemplate("I25.10", "Atherosclerotic heart disease native coronary artery", "cardiac", 15000, 42000, "Cath lab evaluation + stent possible", True, False),
    MedicalTemplate("I25.119", "Atherosclerotic heart disease with angina pectoris", "cardiac", 18000, 48000, "Cardiac stress test + intervention", True, False),
    MedicalTemplate("I48.91", "Unspecified atrial fibrillation", "cardiac", 8000, 22000, "Anticoagulation + rate control", True, False),
    MedicalTemplate("I50.9", "Heart failure unspecified", "cardiac", 12000, 35000, "Diuresis + cardiac workup", True, False),
    MedicalTemplate("J45.40", "Moderate persistent asthma uncomplicated", "respiratory", 2500, 8000, "Controller medication adjustment", True, False),
    MedicalTemplate("J45.51", "Severe persistent asthma with status asthmaticus", "respiratory", 8000, 22000, "ICU admission + intubation risk", False, False),
    MedicalTemplate("J44.0", "COPD with acute lower respiratory infection", "respiratory", 6000, 16000, "Antibiotics + bronchodilators", True, False),
    MedicalTemplate("J18.9", "Pneumonia unspecified organism", "respiratory", 7000, 18000, "Chest X-ray + antibiotics", True, False),
    MedicalTemplate("E11.65", "Type 2 diabetes with hyperglycemia", "chronic", 1200, 5500, "A1C monitoring + medication titration", True, False),
    MedicalTemplate("E78.5", "Hyperlipidemia unspecified", "chronic", 400, 2200, "Lipid panel + statin therapy", True, False),
    MedicalTemplate("I10", "Essential hypertension", "chronic", 300, 1800, "BP monitoring + antihypertensives", True, False),
    MedicalTemplate("E66.9", "Obesity unspecified", "chronic", 500, 3000, "Diet counseling + bariatric evaluation", True, False),
    MedicalTemplate("C50.919", "Malignant neoplasm of unspecified breast", "oncology", 55000, 165000, "Lumpectomy or mastectomy + chemo", False, False),
    MedicalTemplate("C18.9", "Malignant neoplasm of colon unspecified", "oncology", 48000, 140000, "Colectomy + adjuvant therapy", False, False),
    MedicalTemplate("C34.90", "Malignant neoplasm of unspecified lung", "oncology", 62000, 180000, "Lobectomy + radiation", False, False),
    MedicalTemplate("C79.51", "Secondary malignant neoplasm of bone", "oncology", 45000, 125000, "Palliative radiation + pain management", False, False),
    MedicalTemplate("S82.202A", "Unspecified fracture shaft left tibia", "trauma", 18000, 42000, "ORIF with plate fixation", False, False),
    MedicalTemplate("S82.401A", "Unspecified fracture shaft right fibula", "trauma", 12000, 28000, "Immobilization or ORIF", True, False),
    MedicalTemplate("S06.2X0A", "Diffuse traumatic brain injury without LOC", "trauma", 22000, 58000, "ICU monitoring + neurosurgery consult", False, False),
    MedicalTemplate("S36.500A", "Unspecified injury of unspecified kidney", "trauma", 28000, 75000, "CT imaging + possible nephrectomy", False, False),
    MedicalTemplate("G40.909", "Epilepsy unspecified not intractable", "neurology", 9000, 24000, "EEG + antiepileptic medication", True, False),
    MedicalTemplate("G43.909", "Migraine unspecified not intractable", "neurology", 1500, 6500, "Imaging + migraine prophylaxis", True, False),
    MedicalTemplate("G35", "Multiple sclerosis", "neurology", 18000, 52000, "MRI + disease-modifying therapy", False, False),
    MedicalTemplate("G20", "Parkinson disease", "neurology", 12000, 38000, "Neurologist management + medications", False, False),
    MedicalTemplate("N18.5", "Chronic kidney disease stage 5", "renal", 65000, 135000, "Dialysis initiation + transplant eval", False, False),
    MedicalTemplate("N18.3", "Chronic kidney disease stage 3", "renal", 8000, 22000, "Nephrology follow-up + BP control", True, False),
    MedicalTemplate("N17.9", "Acute kidney failure unspecified", "renal", 28000, 68000, "ICU care + possible dialysis", False, False),
    MedicalTemplate("N20.0", "Calculus of kidney", "renal", 9000, 24000, "Lithotripsy or ureteroscopy", True, False),
    MedicalTemplate("F11.20", "Opioid dependence uncomplicated", "behavioral", 6500, 18000, "MAT initiation + counseling", True, False),
    MedicalTemplate("F10.20", "Alcohol dependence uncomplicated", "behavioral", 7500, 20000, "Detox + rehab program", True, False),
    MedicalTemplate("F33.1", "Major depressive disorder recurrent moderate", "behavioral", 3500, 12000, "Medication + psychotherapy", True, False),
    MedicalTemplate("F41.1", "Generalized anxiety disorder", "behavioral", 2800, 9500, "SSRI + CBT", True, False),
    MedicalTemplate("O80", "Encounter for full-term uncomplicated delivery", "obstetrics", 8500, 18000, "Vaginal delivery + postpartum care", True, False),
    MedicalTemplate("O82", "Encounter for cesarean delivery", "obstetrics", 14000, 28000, "C-section + recovery", True, False),
    MedicalTemplate("O09.511", "Supervision high-risk pregnancy elderly primigravida", "obstetrics", 9500, 24000, "MFM monitoring + NST", False, False),
    MedicalTemplate("O24.410", "Gestational diabetes mellitus diet controlled", "obstetrics", 4500, 12000, "Nutrition counseling + glucose monitoring", True, False),
    MedicalTemplate("U09.9", "Post COVID-19 condition unspecified", "infectious", 5500, 16000, "Multidisciplinary long-COVID clinic", True, False),
    MedicalTemplate("B20", "HIV disease", "infectious", 18000, 52000, "ART initiation + monitoring", False, False),
    MedicalTemplate("A41.9", "Sepsis unspecified organism", "infectious", 32000, 85000, "ICU + broad-spectrum antibiotics", False, False),
    MedicalTemplate("J12.89", "Other viral pneumonia", "infectious", 8500, 22000, "Antiviral therapy + supportive care", True, False),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate medical_codes.csv")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "external" / "medical_codes.csv",
    )
    parser.add_argument(
        "--records",
        type=int,
        default=60,
        help="Total number of codes to emit (PLAN target 50-100)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=777,
        help="Deterministic seed for synthesized codes",
    )
    return parser.parse_args()


def synthesize_codes(record_count: int, seed: int) -> List[MedicalCode]:
    if record_count <= len(BASE_CODES):
        return BASE_CODES[:record_count]

    codes: List[MedicalCode] = list(BASE_CODES)
    existing_codes = {code[0] for code in codes}

    template_index = 0
    while len(codes) < record_count:
        template = MEDICAL_TEMPLATES[template_index % len(MEDICAL_TEMPLATES)]
        template_index += 1

        icd_code = template.icd_prefix
        if icd_code in existing_codes:
            continue
        existing_codes.add(icd_code)

        codes.append(
            (icd_code, template.description, template.category, template.cost_min, template.cost_max, template.common, template.notes)
        )

    return codes[:record_count]


def print_medical_code_summary(codes: List[MedicalCode]) -> None:
    category_counts = Counter(code[2] for code in codes)
    common_counts = Counter("common" if code[5] else "special_review" for code in codes)
    print(
        "Medical code summary -> rows: {total}, categories [{categories}], common [{common}]".format(
            total=len(codes),
            categories=", ".join(f"{k}:{v}" for k, v in category_counts.most_common()),
            common=", ".join(f"{k}:{v}" for k, v in common_counts.most_common()),
        )
    )


def main() -> None:
    args = parse_args()
    codes = synthesize_codes(max(args.records, 1), args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["icd10_code", "description", "category", "typical_cost_min", "typical_cost_max", "common", "notes"])
        writer.writerows(codes)
    print_medical_code_summary(codes)
    print(f"Wrote {len(codes)} medical codes to {args.output}")


if __name__ == "__main__":
    main()
