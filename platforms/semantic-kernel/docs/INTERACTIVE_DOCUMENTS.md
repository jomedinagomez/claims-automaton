# Interactive Document Upload - User Guide

## Overview

When processing a claim, if required documents are missing, the CLI can **interactively prompt you** to provide document paths. This eliminates the need for manual session resume commands.

## How It Works

### Automatic Detection
When you run `process`, the orchestrator:
1. Analyzes the claim submission
2. Checks for required documents
3. **Pauses** if any are missing
4. **Prompts you** to provide document paths (if `--interactive` enabled)

### Interactive Flow

```powershell
python -m claims_sk.cli process claim.md
```

**Example Session:**
```
┌─────────────────────────────────────────────┐
│ Claims Orchestration Demo                   │
│ Processing claim from: claim.md             │
└─────────────────────────────────────────────┘

⚠ Missing Documents Detected
The claim cannot proceed without the following documents:

  1. vehicle_damage_photos
  2. insurance_exchange_form

Would you like to provide these documents now? [Y/n]: y

Please provide document paths:
Enter file paths or directory containing documents.
Press Enter without input to skip a document.

  Path for 'vehicle_damage_photos': ./photos/
    ✓ Found 3 files in directory
  Path for 'insurance_exchange_form': ./forms/exchange.pdf
    ✓ File found: exchange.pdf

Resuming orchestration with additional documents...
```

The orchestrator will:
1. Accept your document paths
2. Resume processing automatically
3. Continue until complete or more documents needed

## Usage Modes

### Interactive Mode (Default)
Prompts you when documents are missing:
```powershell
python -m claims_sk.cli process claim.md
# OR explicitly:
python -m claims_sk.cli process claim.md --interactive
```

### Non-Interactive Mode
Pauses and saves session without prompting:
```powershell
python -m claims_sk.cli process claim.md --no-interactive
```

Then resume later:
```powershell
python -m claims_sk.cli resume CLM-123 -d ./documents
```

## Providing Documents

### Option 1: Individual Files
Provide full path to each file:
```
Path for 'vehicle_damage_photos': C:\docs\damage_front.jpg
Path for 'vehicle_damage_photos': C:\docs\damage_rear.jpg
Path for 'vehicle_damage_photos': [Enter to finish]
```

### Option 2: Directory
Provide directory path - all files will be included:
```
Path for 'vehicle_damage_photos': C:\docs\photos\
  ✓ Found 5 files in directory
```

### Option 3: Relative Paths
Use relative paths from current directory:
```
Path for 'police_report': ./documents/police_report.pdf
```

### Option 4: Skip Document
Press Enter without input to skip:
```
Path for 'optional_document': [Enter]
  Skipping optional_document
```

## Multiple Iterations

The CLI supports up to **3 iterations** of document collection. If agents discover additional missing documents during processing, you'll be prompted again:

```
⚠ Missing Documents Detected
Additional documents are now required:

  1. medical_records
  2. repair_estimate

Would you like to provide these documents now? [Y/n]:
```

## API/Backend Integration

For backend APIs (FastAPI, Flask, etc.), use **non-interactive mode** and handle document uploads via API endpoints:

```python
# Backend API pattern
@app.post("/claims")
async def submit_claim(claim_data: dict):
    # Process with session persistence enabled
    result = await orchestrator.process_claim(claim_data)
    
    if result["status"] == "paused":
        return {
            "claim_id": claim_data["claim_id"],
            "status": "awaiting_documents",
            "missing_documents": result["missing_documents"],
            "upload_url": f"/claims/{claim_data['claim_id']}/documents",
        }

@app.post("/claims/{claim_id}/documents")
async def upload_documents(claim_id: str, files: List[UploadFile]):
    # Save files to storage
    document_paths = await save_uploaded_files(files)
    
    # Continue processing
    result = await orchestrator.continue_claim(
        claim_id=claim_id,
        additional_documents={"documents": document_paths},
    )
    
    return {"status": result["status"]}
```

## Error Handling

### File Not Found
```
Path for 'police_report': ./missing.pdf
  ✗ File or directory not found: ./missing.pdf
  Try again? [Y/n]: y
```

### Empty Directory
```
Path for 'photos': ./empty_folder/
  Directory is empty, try again
```

### No Documents Provided
```
Would you like to provide these documents now? [Y/n]: n
Claim saved in paused state. Use 'resume' command to continue later.

ℹ Claim paused. Resume with:
  python -m claims_sk.cli resume CLM-123
```

## Tips

1. **Prepare Documents in Advance**: Have all required documents in a single directory
2. **Use Descriptive Filenames**: Helps with document type inference
3. **Multiple Files Per Type**: Provide directory with all related photos/forms
4. **Skip Optional Docs**: Press Enter to skip non-critical documents
5. **Review First**: Check the missing documents list before providing paths

## Required Document Types

Common document types the orchestrator looks for:

- **vehicle_damage_photos** - Photos of vehicle damage (JPEG, PNG)
- **insurance_exchange_form** - Insurance information exchange form (PDF)
- **police_report** - Police accident report (PDF)
- **medical_records** - Medical documentation (if injury claim)
- **repair_estimate** - Vehicle repair estimate (PDF, XLSX)
- **witness_statements** - Witness testimonies (PDF, TXT)

## Example: Complete Interactive Session

```powershell
PS> python -m claims_sk.cli process shared/submission/claim.md

┌─────────────────────────────────────────────┐
│ Claims Orchestration Demo                   │
│ Processing claim from: claim.md             │
└─────────────────────────────────────────────┘

⚠ Missing Documents Detected
The claim cannot proceed without the following documents:

  1. vehicle_damage_photos
  2. insurance_exchange_form

Would you like to provide these documents now? [Y/n]: y

Please provide document paths:
Enter file paths or directory containing documents.
Press Enter without input to skip a document.

  Path for 'vehicle_damage_photos': C:\claims\photos\
    ✓ Found 3 files in directory
  Path for 'insurance_exchange_form': C:\claims\forms\exchange.pdf
    ✓ File found: exchange.pdf

Resuming orchestration with additional documents...

┌─────────────────────────────────────────────┐
│       Orchestration Result                  │
│ APPROVED                                    │
│ Termination Reason: complete                │
│ Rounds Executed: 8                          │
└─────────────────────────────────────────────┘

✓ Handoff payload exported: ./output/CLM-123_handoff.json
```

## Related Documentation

- [Session Persistence](SESSION_PERSISTENCE.md)
- [Backend API Pattern](../examples/backend_api_example.py)
- [CLI Reference](../README.md)
