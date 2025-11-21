# Claims Submission - Required Information Guide

This document defines what information the agent needs to process a claim. The agent will ask for missing information conversationally, and you can provide it via **chat messages** or **file uploads**.

---

## Core Information (Always Required)

For **any claim type**, the following information must be provided:

| Information | Example | Status in Your Claim |
|------------|---------|---------------------|
| **Policy Number** | AUTO-789456 | ✅ Provided |
| **Incident Date** | Nov 10, 2025 | ✅ Provided |
| **Filed Date** | Nov 11, 2025 | ✅ Provided |
| **Claim Amount** | $5,000 | ❌ **MISSING** |
| **Incident Location** | I-95 North, mile marker 42 | ✅ Provided |
| **Incident Description** | Rear-ended at red light | ✅ Provided |
| **Contact Information** | 410-555-1234 | ✅ Provided |
| **Customer ID** | Auto-generated or from policy | ⚠️ System will lookup |
| **Claim ID** | Auto-generated | ⚠️ System will generate |

---

## Auto Collision Claims (Your Claim Type)

### Required Information:
- **Other Party Information**: Other driver's name and insurance ✅ (in police report)
- **Police Report Number**: Report reference number ✅ (police_report_12345)
- **Vehicle Damage Description**: Description of damage ✅ (rear bumper and trunk)

### Required Documents:
- **Police Report** ✅ `police_report_12345.md`
- **Repair Estimate** ✅ `repair_estimate_001.md`

### Optional Supporting Documents:
- **Medical Records** ✅ `medical_receipt_summary.md` (you provided this - great!)
- **Witness Statement** ✅ `witness_statement.txt` (you provided this - great!)

---

## What's Missing from Your Claim?

Based on your submission in `claim_submission.md`, you need to provide:

### 🔴 **CLAIM AMOUNT**
You need to specify the total amount you're claiming. This should include:
- Repair costs: $X (from Honest Auto Body estimate)
- Medical costs: $X (from orthopedic clinic)
- Rental car costs (if applicable): $X
- Any other related expenses

**How to provide**: You can type in the chat:
```
"I'm claiming $8,500 total: $4,200 for repairs, $850 for medical treatment, and I'll need a rental car for 5 days"
```

Or upload a file with itemized costs.

---

## How the Agent Will Ask

When you submit your claim, the agent will:

1. ✅ Review your submission
2. ✅ Validate your policy (AUTO-789456)
3. ✅ Check if documents are attached
4. ❌ Detect that **claim_amount** is missing
5. 💬 Ask conversationally: 
   > "📋 I've reviewed your claim and I need this information: **claim_amount**. You can provide this by typing in the chat or uploading a file."

Then you can respond naturally:
- **Via chat**: "The total claim is $8,500"
- **Via file**: Upload a spreadsheet or document with itemized costs

---

## Example Conversational Flow

**You**: *[Upload claim_submission.md with all 4 documents]*

**Agent**: "👋 Hello! I'm reviewing your claim submission..."
*(Processing...)*

**Agent**: "📋 I've reviewed your claim and I need this information: **claim_amount**. You can provide this by typing in the chat or uploading files."

**You**: "The total claim is $8,500 - that's $4,200 for the car repair estimate from Honest Auto Body, $850 for the medical visit and x-rays, and I'll need about $450 for 5 days of rental car while mine is being fixed."

**Agent**: "✅ Thank you! I've updated your claim with the amount of $8,500. Moving to detailed analysis..."
*(Continues processing...)*

---

## Files in Your Documents Folder

You already have these files ready to submit:

```
shared/submission/documents/
├── police_report_12345.md        ✅ Required for auto collision
├── repair_estimate_001.md        ✅ Required for auto collision  
├── medical_receipt_summary.md    ✅ Optional but helpful
└── witness_statement.txt         ✅ Optional but helpful
```

---

## Summary

✅ **You're 90% complete!** Your submission is very thorough.

❌ **Missing**: Just need to specify the **total claim amount**

💡 **Tip**: The agent can accept information through natural conversation. Just type what's missing in the chat instead of having to format everything in JSON or upload new files.
