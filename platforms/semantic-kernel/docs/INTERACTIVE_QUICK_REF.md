# Interactive Document Upload - Quick Reference

## Commands

```powershell
# Interactive mode (prompts for documents)
python -m claims_sk.cli process claim.md

# Non-interactive mode (pauses and saves)
python -m claims_sk.cli process claim.md --no-interactive

# Resume paused claim
python -m claims_sk.cli resume CLM-123 -d ./documents
```

## Interactive Flow

When documents are missing:

```
⚠ Missing Documents Detected
  1. vehicle_damage_photos
  2. insurance_exchange_form

Would you like to provide these documents now? [Y/n]: y

Path for 'vehicle_damage_photos': ./photos/
  ✓ Found 3 files in directory

Path for 'insurance_exchange_form': ./forms/exchange.pdf
  ✓ File found: exchange.pdf

Resuming orchestration...
```

## Providing Paths

| Input Type | Example | Result |
|------------|---------|--------|
| **File** | `C:\docs\report.pdf` | Single document |
| **Directory** | `C:\docs\photos\` | All files in directory |
| **Relative** | `./documents/form.pdf` | Resolved from current dir |
| **Skip** | `[Enter]` | Skip this document |

## Path Validation

- ✓ **File found** - Added to documents
- ✓ **Directory found** - All files added
- ✗ **Not found** - Retry prompt
- ⊘ **Empty directory** - Retry prompt

## Error Handling

```
Path for 'police_report': ./missing.pdf
  ✗ File or directory not found
  Try again? [Y/n]: y

Path for 'police_report': ./docs/police_report.pdf
  ✓ File found: police_report.pdf
```

## Multiple Iterations

CLI supports up to **3 rounds** of document collection:

1. **Initial submission** → Missing docs detected
2. **First collection** → Provide docs, resume
3. **Second collection** → More docs needed (if any)
4. **Third collection** → Final docs (if needed)

## Common Document Types

- `vehicle_damage_photos` - JPEG/PNG photos
- `insurance_exchange_form` - PDF form
- `police_report` - PDF report
- `medical_records` - PDF/DOC files
- `repair_estimate` - PDF/XLSX estimate
- `witness_statements` - PDF/TXT statements

## Tips

✓ **Prepare documents in advance** - Have all files in one directory  
✓ **Use clear filenames** - `damage_front.jpg`, `police_report.pdf`  
✓ **Provide directory** - Easier than individual files  
✓ **Skip optional docs** - Press Enter to skip non-critical items  
✓ **Absolute paths** - Less ambiguity than relative paths  

## Backend API Pattern

For APIs, use **non-interactive mode**:

```python
# Process without prompts
result = await orchestrator.process_claim(claim_data)

if result["status"] == "paused":
    # Return to frontend
    return {
        "status": "awaiting_documents",
        "missing_documents": result["missing_documents"],
        "upload_url": f"/claims/{claim_id}/documents"
    }
```

## Configuration

Enable/disable via flag:
```powershell
--interactive    # Prompt for documents (default)
--no-interactive # Pause without prompting
```

Or set environment:
```bash
ORCHESTRATION_ENABLE_HITL=true   # Required for pause behavior
```

## Full Example

```powershell
PS> python -m claims_sk.cli process claim.md

┌─────────────────────────────────────┐
│ Claims Orchestration Demo           │
└─────────────────────────────────────┘

⚠ Missing Documents Detected
  1. vehicle_damage_photos
  2. insurance_exchange_form

Would you like to provide these documents now? [Y/n]: y

Please provide document paths:

  Path for 'vehicle_damage_photos': C:\claims\photos\
    ✓ Found 3 files in directory
  
  Path for 'insurance_exchange_form': C:\claims\exchange.pdf
    ✓ File found: exchange.pdf

Resuming orchestration...

┌─────────────────────────────────────┐
│ Orchestration Result                │
│ APPROVED                            │
│ Rounds Executed: 8                  │
└─────────────────────────────────────┘

✓ Handoff payload exported: ./output/CLM-123_handoff.json
```

## Related Docs

- [Full Guide](INTERACTIVE_DOCUMENTS.md)
- [Session Persistence](SESSION_PERSISTENCE.md)
- [CLI Reference](../README.md)
