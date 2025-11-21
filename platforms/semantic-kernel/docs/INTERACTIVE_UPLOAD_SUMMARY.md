# Interactive Document Upload - Implementation Summary

## ✅ What Was Added

**Interactive document collection** during claim processing - the CLI now prompts you to provide document paths when missing instead of just pausing.

## 🔧 Changes Made

### 1. CLI `process` Command
**Added `--interactive` flag** (enabled by default):
```powershell
# Interactive mode (default) - prompts for documents
python -m claims_sk.cli process claim.md

# Non-interactive mode - pauses and saves
python -m claims_sk.cli process claim.md --no-interactive
```

### 2. Interactive Pause/Resume Loop
When documents are missing:
1. **Lists missing documents** clearly
2. **Asks if you want to provide them now**
3. **Prompts for each document path** (file or directory)
4. **Validates paths** and shows feedback (✓ found, ✗ not found)
5. **Resumes processing automatically** with new documents
6. **Repeats up to 3 times** if agents discover more missing docs

### 3. New Helper Function: `_prompt_for_documents()`
Handles the interactive collection:
- Accepts individual file paths
- Accepts directory paths (includes all files)
- Supports relative and absolute paths
- Allows skipping documents (press Enter)
- Validates file/directory existence
- Retries on errors

### 4. Enhanced Display
When paused, shows:
```
⚠ Required Documents:
  1. vehicle_damage_photos
  2. insurance_exchange_form

Provide these documents to continue processing.
```

## 📋 User Experience

### Before (Manual Resume):
```powershell
# Run process
python -m claims_sk.cli process claim.md
# Status: PAUSED, missing: vehicle_damage_photos, insurance_exchange_form

# Manually resume later
python -m claims_sk.cli resume CLM-123 -d ./documents
```

### After (Interactive):
```powershell
python -m claims_sk.cli process claim.md

# Prompts appear:
⚠ Missing Documents Detected
  1. vehicle_damage_photos
  2. insurance_exchange_form

Would you like to provide these documents now? [Y/n]: y

Path for 'vehicle_damage_photos': ./photos/
  ✓ Found 3 files in directory
Path for 'insurance_exchange_form': ./forms/exchange.pdf
  ✓ File found: exchange.pdf

Resuming orchestration with additional documents...

# Continues automatically to completion
Status: APPROVED
```

## 🎯 Use Cases

### 1. Interactive CLI Demo (Default)
Perfect for demos and development:
```powershell
python -m claims_sk.cli process claim.md
# Prompts for documents inline
```

### 2. Non-Interactive Batch Processing
For automation and scripts:
```powershell
python -m claims_sk.cli process claim.md --no-interactive
# Saves paused state, no prompts
```

### 3. Backend API Integration
APIs should use non-interactive mode:
```python
# Process with session persistence
result = await orchestrator.process_claim(claim_data)

if result["status"] == "paused":
    # Return to frontend for document upload
    return {
        "status": "awaiting_documents",
        "missing_documents": result["missing_documents"],
    }
```

## 📝 Example Session

```powershell
PS> python -m claims_sk.cli process shared/submission/claim.md

┌─────────────────────────────────────┐
│ Claims Orchestration Demo           │
│ Processing claim from: claim.md     │
└─────────────────────────────────────┘

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
  Path for 'insurance_exchange_form': C:\claims\exchange.pdf
    ✓ File found: exchange.pdf

Resuming orchestration with additional documents...

┌─────────────────────────────────────┐
│ Orchestration Result                │
│ APPROVED                            │
│ Termination Reason: complete        │
│ Rounds Executed: 8                  │
└─────────────────────────────────────┘

✓ Handoff payload exported: ./output/CLM-123_handoff.json
```

## 🔄 Flow Diagram

```
┌─────────────────────┐
│ Submit Claim        │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Phase 1: Validation │
└──────────┬──────────┘
           │
           ▼
    ┌──────────────┐
    │ Missing Docs? │
    └───┬──────┬───┘
        │      │
    No  │      │ Yes
        │      │
        │      ▼
        │  ┌─────────────────┐
        │  │ Interactive=True?│
        │  └───┬──────┬──────┘
        │      │      │
        │  Yes │      │ No
        │      │      │
        │      ▼      ▼
        │  ┌────────┐ ┌──────────┐
        │  │ Prompt │ │ Save &   │
        │  │ User   │ │ Pause    │
        │  └───┬────┘ └──────────┘
        │      │
        │      ▼
        │  ┌────────────┐
        │  │ Docs       │
        │  │ Provided?  │
        │  └───┬────┬───┘
        │      │    │
        │  Yes │    │ No
        │      │    │
        │      ▼    ▼
        │  ┌──────────┐
        │  │ Continue │
        │  └────┬─────┘
        │       │
        ▼       ▼
┌──────────────────────┐
│ Phase 2: Gathering   │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ Phase 3: Decision    │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ Complete (Approved/  │
│ Denied)              │
└──────────────────────┘
```

## 🛠️ Technical Details

### Max Iterations: 3
Prevents infinite loops if agents keep finding missing documents:
```python
max_iterations = 3
iteration = 0

while result["status"] == "paused" and interactive and iteration < max_iterations:
    iteration += 1
    # Prompt for documents
    # Resume processing
```

### Path Validation
Handles multiple input types:
- **File**: `C:\docs\report.pdf` → Single document
- **Directory**: `C:\docs\photos\` → All files in directory
- **Relative**: `./documents/form.pdf` → Resolved from CWD
- **Empty**: Press Enter → Skip document

### Document Structure
Creates proper document objects:
```python
{
    "type": "vehicle_damage_photos",
    "filename": "damage_front.jpg",
    "path": "C:\\claims\\photos\\damage_front.jpg"
}
```

## 📚 Documentation

- **User Guide**: `docs/INTERACTIVE_DOCUMENTS.md` - Complete usage guide
- **Session Persistence**: `docs/SESSION_PERSISTENCE.md` - Backend patterns
- **Quick Reference**: `docs/SESSION_QUICK_REFERENCE.md` - Command cheat sheet

## ✅ Validation

Verified:
- ✅ `--interactive` flag shows in help
- ✅ Default behavior is interactive=True
- ✅ `--no-interactive` disables prompts
- ✅ `_prompt_for_documents()` function implemented
- ✅ Display shows missing documents prominently
- ✅ Pause/resume loop supports up to 3 iterations

## 🎯 Next Steps (Optional)

Future enhancements:
- **File type validation** - Check extensions match document type
- **Drag-and-drop support** - GUI file picker integration
- **Bulk upload** - Accept zip file with all documents
- **Document preview** - Show thumbnails before upload
- **Progress tracking** - Show upload progress for large files

## 🔑 Key Takeaway

**Users can now provide missing documents interactively during claim processing** - no need to manually resume with separate commands. The CLI guides them through document collection and automatically continues processing! 🎉
