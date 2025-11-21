# Claims Information Collection Flow

## Workflow Overview

```
User Submits Claim
     ↓
Agent Analyzes Initial Submission
     ↓
[STEP 1] Ask for Missing DATA
     ↓
User Provides Information (via chat)
     ↓
[STEP 2] Ask for Missing DOCUMENTS
     ↓
User Uploads Files
     ↓
Process Claim
```

---

## Example: Auto Collision Claim

### Sample Initial Submission
```
From: john.smith@example.com
Subject: Claim for car accident yesterday

I need to file a claim for an accident that happened yesterday (Nov 10th) 
on I-95 North around 1:30pm. I was stopped at a red light near mile marker 
42 when someone rear-ended me. It was raining pretty hard.

My policy number is AUTO-789456. The car is a 2020 Toyota Camry.
```

### What Agent Will Ask For (STEP 1 - Data)

**Core Information:**
- ✅ Policy number: AUTO-789456 (provided)
- ✅ Incident date: Nov 10, 2025 (provided)  
- ✅ Incident location: I-95 North, mile marker 42 (provided)
- ✅ Incident description: Rear-ended while stopped (provided)
- ❌ **Claim amount: MISSING** → Agent asks: "What is the total amount you're claiming?"
- ✅ Contact: john.smith@example.com (provided)

**Auto Collision Specific:**
- ✅ Vehicle info: 2020 Toyota Camry (provided)
- ❌ **Vehicle damage description: MISSING** → Agent asks: "Can you describe the damage to your vehicle?"
- ❌ **Vehicle repair amount: MISSING** → Agent asks: "What is the estimated repair cost for your vehicle?"
- ❌ **Other party involved: UNCLEAR** → Agent asks: "Was another vehicle/party involved in the accident?"
- ❌ **Police called: UNCLEAR** → Agent asks: "Did the police come to the scene?"
- ❌ **Injuries occurred: UNCLEAR** → Agent asks: "Were there any injuries from the accident?"

**Agent's Conversational Questions (Example):**
```
🤖 Thank you for submitting your claim. I have a few questions to complete 
   the information:

   1. What is the total amount you're claiming? (This can be an estimate)
   
   2. Can you describe the damage to your vehicle?
   
   3. What is the estimated cost to repair your vehicle?
   
   4. Was another vehicle or party involved in the accident?
   
   5. Did the police respond to the scene?
   
   6. Were there any injuries from the accident?
```

### User Responds (via chat)
```
👤 Total claim is about $8,500. The rear bumper is crushed and trunk lid is 
   dented. Repair estimate is $7,000. Yes, another car hit me and yes, police 
   came. I went to the doctor for neck pain - cervical strain. Medical costs 
   were about $1,500.
```

### Agent Follows Up (STEP 1 continued)
```
🤖 Thank you! Since there were injuries and police involvement, I need a bit 
   more information:
   
   1. Can you provide the other party's name and insurance information?
   
   2. What medical treatment did you receive?
```

### User Responds
```
👤 Other driver was Jane Doe with State Farm policy #12345. I got X-rays and 
   examination at Baltimore Orthopedic Clinic.
```

### Agent Requests Documents (STEP 2)
```
🤖 Perfect! Now I need the following documents to verify your claim:

   Required Documents:
   ✅ Police report - I see you have police_report_12345.md
   ✅ Repair estimate - I see you have repair_estimate_001.md
   ✅ Medical records - I see you have medical_receipt_summary.md
   
   All required documents are present! Let me process your claim now...
```

---

## Configuration Reference

All required data fields are defined in:
```
shared/config/required_information.yaml
```

### For Auto Collision Claims

**Always Required Data:**
1. policy_number
2. incident_date
3. incident_location
4. incident_description
5. claim_amount
6. contact_information
7. vehicle_info
8. vehicle_damage_description
9. vehicle_repair_amount
10. other_party_involved (yes/no)
11. police_called (yes/no)
12. injuries_occurred (yes/no)

**Conditional Data (if applicable):**
- other_party_info (if other_party_involved = yes)
- medical_treatment_received (if injuries_occurred = yes)
- medical_expenses_amount (if injuries_occurred = yes)

**Required Documents (after data collected):**
- police_report (if police_called = yes)
- repair_estimate (always)
- medical_records (if injuries_occurred = yes)
- witness_statement (optional)

---

## Benefits of This Approach

1. **Natural Conversation**: User describes incident naturally, agent asks specific questions
2. **Efficient**: Collect all data before requesting documents
3. **Conditional Logic**: Only ask for relevant information (e.g., medical info if injuries)
4. **Clear Expectations**: User knows exactly what's needed
5. **Flexible Input**: User can provide info via chat or upload documents
