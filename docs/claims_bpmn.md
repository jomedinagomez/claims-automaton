# Claims BPMN Reference

## Process Walkthrough
1. **Request Claim** – claimant submits description and documents.
2. **Review Request Claim** – IntakeAgent normalizes info, flags missing data.
3. **Record Claim Information** – ledger entry created, IDs assigned.
4. **Validate Claim Document and Data** – ValidationAgent checks completeness, fraud cues, and policy coverage.
5. **Claim Analysis** – AnalysisAgent builds narrative, risk/impact score, and payout guidance.
6. **Claim Approval?** – DecisionAgent evaluates acceptance vs. rejection.
   - **Accepted path**
     1. Offer claim settlement.
     2. Record settlement payment.
     3. Close claim.
     4. Payment confirmation.
   - **Rejected path**
     1. Claim rejection review.
     2. Notify request rejection or request additional data.
     3. Optional loop back if customer contests and provides new info.

## Termination Mapping
| BPMN Node | Context Keys | Termination Outcome |
| --- | --- | --- |
| Close Claim | `decision_status="accepted"`, `settlement_completed=True` | Success summary + ledger snapshot.
| Payment | `decision_status="accepted"`, `payment_confirmed=True` | Success with payment receipt details.
| Notify Request Rejection | `decision_status="rejected"`, `rejection_notified=True` | Final rejection rationale + remediation tips.
| Request Additional Data | `state="request_additional_data"`, `missing_documents` non-empty | Pause orchestration (human-in-loop) rather than terminate.
| Stall/Timeout | repeated agent with no ledger delta, or `round_count > max_rounds` | Terminate with partial context + operator alert.

## Implementation Notes
- `ClaimsMagenticManager` compares conversation metadata against the table above each turn.
- Agents must update shared metadata keys (`decision_status`, `settlement_completed`, etc.) before yielding control.
- Telemetry attributes `claim.termination_reason` and `claim.decision_status` should be emitted when termination triggers.
- Human requests for additional data are surfaced via CLI prompt; the orchestration resumes once inputs are supplied.
