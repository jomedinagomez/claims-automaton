# Claims Data Generation Plan

## Overview
This directory contains Python scripts for generating comprehensive insurance claim assessment datasets for the claims orchestration system. The generation process uses Azure OpenAI with Pydantic structured outputs to create realistic, interconnected data that mirrors production insurance workflows.

## Generation Architecture

### Phase-Based Approach
The data generation follows a **phased dependency model** to ensure referential integrity:

1. **Phase 1: Foundation Reference Data** - Independent datasets (policies, vendors, coverage matrix)
2. **Phase 2: Historical Data** - Datasets that reference Phase 1 (claims history)
3. **Phase 3: Configuration Files** - YAML/JSON configuration and external data

### Master Orchestration Script
`generate_all_claims_data.py` - Runs all generation scripts in dependency order, validates outputs, and handles cleanup.

---

## Data Files & Generation Scripts

### Phase 1: Foundation Reference Data (Independent Generation)

#### 1. `01_generate_policies.py` → `policies.csv`
**Output Location**: `shared/datasets/policies.csv`

**Purpose**: Generate active customer insurance policies (auto, home, health)

**Schema** (25 fields):
```csv
policy_number,customer_id,policy_holder_name,dob,license_number,license_state,policy_type,tier,status,effective_date,expiration_date,annual_premium,payment_status,collision_limit,comprehensive_limit,deductible_collision,deductible_comprehensive,liability_bi_per_person,liability_bi_per_accident,liability_pd,uninsured_motorist,medical_payments,aggregate_limit_per_year,claims_count_this_year,claims_paid_this_year,remaining_aggregate,vehicle_make,vehicle_model,vehicle_year,vehicle_vin,vehicle_usage,garaging_address
```

**Generation Rules**:
- **Policy Types**: `auto`, `home`, `health`
- **Policy Tiers**: `basic`, `standard`, `premium`
- **Policy Status**: 85% `active`, 10% `lapsed`, 3% `suspended`, 2% `cancelled`
- **Customer IDs**: CUST-1001 to CUST-5000 (4000 unique customers, some with multiple policies)
- **Policy Numbers**: 
  - Auto: AUTO-###### (6 digits)
  - Home: HOME-###### (6 digits)
  - Health: HEALTH-###### (6 digits)
- **Coverage Amounts**:
  - Auto collision: $15,000 - $50,000
  - Auto comprehensive: $10,000 - $40,000
  - Home fire: $100,000 - $500,000
  - Health surgery: $50,000 - unlimited
- **Effective Dates**: 2022-01-01 to 2025-01-01 (favor 60% older policies 2022-2023)
- **States**: MD, VA, DC, PA (mid-Atlantic region focus)
- **Vehicle Fields**: Only populated for auto policies (vehicle_make, vehicle_model, vehicle_year, vehicle_vin)

**Target Record Count**: 1,000 policies

**Dependencies**: None

---

#### 2. `02_generate_vendors.py` → `vendors.csv`
**Output Location**: `shared/datasets/vendors.csv`

**Purpose**: Generate approved repair shops and medical providers

**Schema** (16 fields):
```csv
vendor_id,vendor_type,business_name,license_number,license_state,license_expiry,rating,total_claims_processed,avg_estimate_accuracy,contact_phone,address,city,state,zip,last_audit_date,audit_status,notes
```

**Generation Rules**:
- **Vendor Types**: `repair_shop` (60%), `medical_provider` (40%)
- **Vendor IDs**: VND-001 to VND-100
- **License States**: MD, VA, DC, PA
- **License Expiry**: 2025-01-01 to 2027-12-31
- **Rating**: 3.5 to 5.0 (weighted toward 4.2-4.8)
- **Audit Status**: 90% `passed`, 7% `conditional`, 3% `failed`
- **Total Claims Processed**: 50 to 1500
- **Avg Estimate Accuracy**: 0.85 to 0.99

**Target Record Count**: 100 vendors

**Dependencies**: None

---

#### 3. `03_generate_blacklist.py` → `blacklist.csv`
**Output Location**: `shared/datasets/risk/blacklist.csv`

**Purpose**: Generate flagged entities for fraud detection

**Schema** (10 fields):
```csv
entity_id,entity_type,business_name,tax_id,license_number,reason,date_flagged,severity,status,last_verified,notes
```

**Generation Rules**:
- **Entity Types**: `customer` (40%), `repair_shop` (30%), `medical_provider` (20%), `attorney` (10%)
- **Entity IDs**: BL-001 to BL-050
- **Reasons**: `multiple_fraudulent_claims`, `inflated_estimates`, `billing_fraud`, `staged_accident`, `unlicensed_operation`, `excessive_litigation`
- **Severity**: `low`, `medium`, `high`, `critical`
- **Status**: 80% `active`, 15% `under_investigation`, 5% `resolved`
- **Date Flagged**: 2023-01-01 to 2024-11-01
- **Reference Integrity**: 20-30% of blacklisted vendors should reference actual vendor_id values from vendors.csv

**Target Record Count**: 50 blacklist entries

**Dependencies**: Soft dependency on `vendors.csv` (can run independently, but better with vendor references)

---

#### 4. `04_generate_coverage_matrix.py` → `coverage_matrix.csv`
**Output Location**: `shared/datasets/coverage_matrix.csv`

**Purpose**: Define coverage details by policy tier and claim type

**Schema** (6 fields):
```csv
policy_tier,claim_type,coverage_limit,deductible,exclusions,notes
```

**Generation Rules**:
- **Policy Tiers**: `basic`, `standard`, `premium`
- **Claim Types**: `auto_collision`, `auto_comprehensive`, `home_fire`, `health_surgery`
- **Coverage Limits**: Scale by tier (basic < standard < premium)
- **Deductibles**: Inverse scale by tier (basic > standard > premium)
- **Exclusions**: Pipe-delimited strings (e.g., `racing|commercial_use`)

**Target Record Count**: 12 rows (3 tiers × 4 claim types)

**Dependencies**: None

---

#### 5. `05_generate_medical_codes.py` → `medical_codes.csv`
**Output Location**: `shared/datasets/external/medical_codes.csv`

**Purpose**: ICD-10 medical procedure codes for health claim validation

**Schema** (7 fields):
```csv
icd10_code,description,category,typical_cost_min,typical_cost_max,common,notes
```

**Generation Rules**:
- **ICD-10 Codes**: Real medical codes (K35.80, S72.001A, I21.9, M17.11, etc.)
- **Categories**: `surgery`, `orthopedic`, `cardiac`, `respiratory`, `chronic`, `oncology`, `preventive`
- **Cost Ranges**: Realistic typical costs by procedure type
- **Common Flag**: `true` for frequent procedures, `false` for rare/specialized

**Target Record Count**: 50-100 medical codes

**Dependencies**: None

---

### Phase 2: Historical Data (Depends on Phase 1)

#### 6. `06_generate_claims_history.py` → `claims_history.csv`
**Output Location**: `shared/datasets/historical/claims_history.csv`

**Purpose**: Generate historical claims that reference existing policies

**Schema** (14 fields):
```csv
claim_id,customer_id,policy_number,claim_type,incident_date,filed_date,closed_date,amount_requested,reserved_amount,amount_paid,claim_status,fraud_flag,assigned_adjuster,processing_days,notes
```

**Generation Rules**:
- **CRITICAL DEPENDENCY**: MUST load `policies.csv` first
- **Claim IDs**: CLM-2023-##### and CLM-2024-##### (sequential)
- **Policy Integration**:
  - `customer_id` MUST match policy customer_id
  - `policy_number` MUST match policy policy_number
  - `claim_type` MUST align with policy_type (auto → auto_collision/auto_comprehensive, home → home_fire, health → health_surgery)
- **Incident Date**: MUST be after policy effective_date and before expiration_date
- **Filed Date**: 1-14 days after incident_date
- **Closed Date**: 5-30 days after filed_date (null for open claims)
- **Claim Status**: 94% `closed_approved`, 3% `closed_denied`, 3% `open`
- **Fraud Flag**: 5% true (higher for blacklisted customers)
- **Amount Logic**:
  - `amount_requested` <= policy coverage_limit
  - `amount_paid` <= amount_requested
  - Denied claims: amount_paid = 0
- **Assigned Adjuster**: AGT-001 to AGT-050

**Target Record Count**: ~300-400 claims (30-40% of policies have historical claims)

**Dependencies**: 
- **REQUIRED**: `policies.csv`
- **OPTIONAL**: `blacklist.csv` (for fraud flag correlation)

---

#### 7. `07_generate_payout_benchmarks.py` → `payout_benchmarks.csv`
**Output Location**: `shared/datasets/historical/payout_benchmarks.csv`

**Purpose**: Statistical benchmarks for payout amounts by claim type and severity

**Schema** (10 fields):
```csv
claim_type,severity,avg_payout,std_deviation,percentile_25,percentile_50,percentile_75,percentile_90,sample_size,last_updated
```

**Generation Rules**:
- **Claim Types**: `auto_collision`, `auto_comprehensive`, `home_fire`, `health_surgery`
- **Severity Levels**: 
  - Auto: `minor`, `moderate`, `severe`
  - Home: `minor`, `moderate`, `major`
  - Health: `routine`, `complex`, `critical`
- **Statistical Generation**:
  - **Option A**: Calculate from `claims_history.csv` if available (realistic)
  - **Option B**: Generate synthetic distributions (faster, still realistic)
- **Sample Size**: 100-2500 per category
- **Last Updated**: 2024-11-01

**Target Record Count**: 12 rows (4 claim types × 3 severity levels)

**Dependencies**: 
- **OPTIONAL**: `claims_history.csv` (for real statistics)
- Can run independently with synthetic distributions

---

### Phase 3: Configuration & External Data

#### 8. Configuration Files (YAML/JSON)

These can be **static templates** or **programmatically generated**:

##### `fraud_indicators.yaml`
**Output Location**: `shared/datasets/risk/fraud_indicators.yaml`

**Content**: Red flag patterns for fraud detection
- Duplicate claims thresholds
- High-value claim triggers
- Blacklist checks
- Inconsistent statements
- Suspicious timing patterns
- Missing corroboration

##### `risk_scoring_rules.json`
**Output Location**: `shared/datasets/risk/risk_scoring_rules.json`

**Content**: Point-based risk assessment rules
- Customer claims history scoring
- Claim amount ratio scoring
- Documentation completeness scoring
- Score interpretation thresholds

##### `weather_events.json`
**Output Location**: `shared/datasets/external/weather_events.json`

**Content**: External weather validation data (mock API responses)
- Event IDs, dates, locations
- Event types (heavy_rain, hail, tornado, etc.)
- Severity levels
- Verified sources

##### `police_reports.json`
**Output Location**: `shared/datasets/external/police_reports.json`

**Content**: Simulated police database responses
- Report numbers, dates, locations
- Incident types
- Involved parties
- Officer IDs

---

## Master Orchestration Script

### `generate_all_claims_data.py`

**Purpose**: Run all generation scripts in dependency order with validation

**Execution Flow**:

1. **Phase 1: Foundation Data**
   - Run `01_generate_policies.py` → validate `policies.csv`
   - Run `02_generate_vendors.py` → validate `vendors.csv`
   - Run `03_generate_blacklist.py` → validate `blacklist.csv`
   - Run `04_generate_coverage_matrix.py` → validate `coverage_matrix.csv`
   - Run `05_generate_medical_codes.py` → validate `medical_codes.csv`

2. **Phase 2: Historical Data**
   - Run `06_generate_claims_history.py` → validate `claims_history.csv`
   - Run `07_generate_payout_benchmarks.py` → validate `payout_benchmarks.csv`

3. **Phase 3: Configuration Files**
   - Copy or generate YAML/JSON files
   - Validate JSON schemas

4. **Validation & Cleanup**
   - Check record counts
   - Validate referential integrity (customer_id, policy_number)
   - Clean up temporary files
   - Generate summary report

**Usage**:
```bash
cd shared/datasets/generation_scripts
python generate_all_claims_data.py
```

---

## Technical Implementation Details

### Azure OpenAI Configuration
All scripts use:
- **Azure AI Foundry Structured Output** with Pydantic models
- **Entra ID Authentication** via `DefaultAzureCredential`
- **Environment Variables** (`.env` file):
  ```
  AZURE_OPENAI_ENDPOINT=https://your-endpoint.openai.azure.com/
  AZURE_OPENAI_DEPLOYMENT=gpt-4o
  AZURE_OPENAI_API_VERSION=2024-08-01-preview
  ```

### Batch Generation Strategy
- **Batch Size**: 10-20 records per API call (optimized for token limits)
- **Retry Logic**: Exponential backoff for rate limiting
- **Progress Tracking**: Real-time console updates with record counts
- **Validation**: Pydantic field validators ensure schema compliance

### Referential Integrity Checks
Scripts that depend on other files implement:
1. **Pre-flight check**: Verify required files exist
2. **Load validation**: Parse CSV and verify required columns
3. **Random sampling**: Select valid foreign keys from dependent datasets
4. **Post-generation check**: Validate all references resolve

---

## Expected Generation Time

- **Phase 1**: ~15-20 minutes (1000 policies + 100 vendors + supporting files)
- **Phase 2**: ~10-15 minutes (300-400 claims + benchmarks)
- **Phase 3**: ~1 minute (config files)
- **Total**: ~25-35 minutes for complete dataset

---

## Output File Summary

| File | Location | Records | Dependencies |
|------|----------|---------|--------------|
| `policies.csv` | `shared/datasets/` | 1,000 | None |
| `vendors.csv` | `shared/datasets/` | 100 | None |
| `blacklist.csv` | `shared/datasets/risk/` | 50 | vendors.csv (soft) |
| `coverage_matrix.csv` | `shared/datasets/` | 12 | None |
| `medical_codes.csv` | `shared/datasets/external/` | 50-100 | None |
| `claims_history.csv` | `shared/datasets/historical/` | 300-400 | policies.csv (required) |
| `payout_benchmarks.csv` | `shared/datasets/historical/` | 12 | claims_history.csv (optional) |
| `fraud_indicators.yaml` | `shared/datasets/risk/` | Static | None |
| `risk_scoring_rules.json` | `shared/datasets/risk/` | Static | None |
| `weather_events.json` | `shared/datasets/external/` | Static | None |
| `police_reports.json` | `shared/datasets/external/` | Static | None |

---

## Prerequisites

### Python Packages
```bash
pip install pandas numpy python-dotenv openai azure-identity pydantic
```

### Environment Setup
1. Create `.env` file with Azure OpenAI credentials
2. Ensure Azure Entra ID authentication is configured
3. Verify network access to Azure OpenAI endpoint

---

## Next Steps

1. ✅ Create directory structure: `shared/datasets/generation_scripts/`
2. ✅ Document plan: `DATA_GENERATION_PLAN.md`
3. ⬜ Implement `01_generate_policies.py`
4. ⬜ Implement `02_generate_vendors.py`
5. ⬜ Implement `03_generate_blacklist.py`
6. ⬜ Implement `04_generate_coverage_matrix.py`
7. ⬜ Implement `05_generate_medical_codes.py`
8. ⬜ Implement `06_generate_claims_history.py`
9. ⬜ Implement `07_generate_payout_benchmarks.py`
10. ⬜ Implement `generate_all_claims_data.py`
11. ⬜ Create static config files (YAML/JSON)
12. ⬜ Test end-to-end generation pipeline
