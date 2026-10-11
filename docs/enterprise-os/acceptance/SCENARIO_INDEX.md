# Scenario review index

All 96 cases are planned_not_executed. See catalog.json for concrete Given/When/Then, numerical oracles, boundaries and review layers. This index is not an execution report.

| ID | Workflow | Task | Risk | Stress tags |
| --- | --- | --- | --- | --- |
| EOS-W1-001 | W1 | Current scope with stale budget | R0 | happy, missing_freshness |
| EOS-W1-002 | W1 | Noisy bilingual scope | R0 | noisy |
| EOS-W1-003 | W1 | Ambiguous pilot name | R0 | ambiguous |
| EOS-W1-004 | W1 | Follow-up removes budget | R0 | chat_followup |
| EOS-W1-005 | W1 | Read ACL revoked mid-retrieval | R0 | acl_revoked |
| EOS-W1-006 | W1 | Citation payload drift | R0 | schema_drift |
| EOS-W1-007 | W1 | Injection in evidence | R0 | prompt_injection |
| EOS-W1-008 | W1 | One file times out | R0 | timeout |
| EOS-W1-009 | W1 | Transient search retry | R0 | transient_network |
| EOS-W1-010 | W1 | Resume partial response | R0 | restart_partial_completion |
| EOS-W1-011 | W1 | Mobile source inspection | R0 | accessibility_mobile |
| EOS-W1-012 | W1 | Read-only budget zero | R0 | unknown_side_effect_budget_exhausted |
| EOS-W2-001 | W2 | Approved template dual export | R1 | happy |
| EOS-W2-002 | W2 | Noisy template name | R1 | noisy |
| EOS-W2-003 | W2 | Two template versions | R1 | ambiguous |
| EOS-W2-004 | W2 | Follow-up shorten risks | R1 | chat_followup |
| EOS-W2-005 | W2 | Template ACL revoked | R1 | acl_revoked |
| EOS-W2-006 | W2 | Exact send approval stale | R3 | approval_input_changed |
| EOS-W2-007 | W2 | Template schema adds field | R1 | schema_drift |
| EOS-W2-008 | W2 | Injected template footer | R1 | prompt_injection |
| EOS-W2-009 | W2 | PDF conversion timeout | R1 | timeout |
| EOS-W2-010 | W2 | Crash before local save | R1 | crash_before_effect |
| EOS-W2-011 | W2 | Crash after artifact receipt gap | R1 | crash_after_effect_before_receipt |
| EOS-W2-012 | W2 | Upload rejects large PDF | R1 | upload_error |
| EOS-W3-001 | W3 | Cost workbook formulas | R1 | happy |
| EOS-W3-002 | W3 | Four-slide review deck | R1 | happy |
| EOS-W3-003 | W3 | Locale noise | R1 | noisy |
| EOS-W3-004 | W3 | Missing cost not zero | R1 | missing_freshness |
| EOS-W3-005 | W3 | Follow-up cost change | R1 | chat_followup |
| EOS-W3-006 | W3 | Artifact ACL revoked | R1 | acl_revoked |
| EOS-W3-007 | W3 | Layout schema change | R1 | schema_drift |
| EOS-W3-008 | W3 | Formula injection cell | R1 | prompt_injection |
| EOS-W3-009 | W3 | Recalc worker timeout | R1 | timeout |
| EOS-W3-010 | W3 | Double click export | R1 | duplicate_submission |
| EOS-W3-011 | W3 | Crash after workbook save | R1 | crash_after_effect_before_receipt |
| EOS-W3-012 | W3 | Keyboard slide review | R1 | accessibility_mobile |
| EOS-W4-001 | W4 | Tiered capacity delta | R1 | happy |
| EOS-W4-002 | W4 | Noisy source units | R1 | noisy |
| EOS-W4-003 | W4 | Unclear fact identity | R1 | ambiguous |
| EOS-W4-004 | W4 | Follow-up exclude lead | R1 | chat_followup |
| EOS-W4-005 | W4 | Source access revoked | R1 | acl_revoked |
| EOS-W4-006 | W4 | Publish approval changed source | R2 | approval_input_changed |
| EOS-W4-007 | W4 | Registry version drift | R2 | schema_drift |
| EOS-W4-008 | W4 | Source says self-verify | R1 | prompt_injection |
| EOS-W4-009 | W4 | Crash before approved commit | R2 | crash_before_effect, timeout |
| EOS-W4-010 | W4 | Commit succeeded receipt missing | R2 | crash_after_effect_before_receipt |
| EOS-W4-011 | W4 | Duplicate approved publish | R2 | duplicate_submission |
| EOS-W4-012 | W4 | Unknown publish effect budget | R2 | unknown_side_effect_budget_exhausted |
| EOS-W5-001 | W5 | File plus CRM meeting brief | R0 | happy |
| EOS-W5-002 | W5 | Noisy bilingual account | R0 | noisy |
| EOS-W5-003 | W5 | Two Cedar accounts | R0 | ambiguous |
| EOS-W5-004 | W5 | Follow-up next action only | R0 | chat_followup |
| EOS-W5-005 | W5 | CRM field ACL revoked | R0 | acl_revoked |
| EOS-W5-006 | W5 | Stage field renamed | R0 | schema_drift |
| EOS-W5-007 | W5 | CRM note injection | R0 | prompt_injection |
| EOS-W5-008 | W5 | CRM timeout file still usable | R0 | timeout |
| EOS-W5-009 | W5 | CRM transient reset | R0 | transient_network |
| EOS-W5-010 | W5 | Brief upload failure | R1 | upload_error |
| EOS-W5-011 | W5 | Restart half-built brief | R0 | restart_partial_completion |
| EOS-W5-012 | W5 | Mobile meeting card | R0 | accessibility_mobile |
| EOS-W6-001 | W6 | Shortage before due date | R0 | happy |
| EOS-W6-002 | W6 | Inbound later sensitivity | R0 | missing_freshness |
| EOS-W6-003 | W6 | Noisy pack rounding | R0 | noisy |
| EOS-W6-004 | W6 | Ambiguous unit | R0 | ambiguous |
| EOS-W6-005 | W6 | Follow-up demand reduction | R0 | chat_followup |
| EOS-W6-006 | W6 | Inventory ACL revoked | R0 | acl_revoked |
| EOS-W6-007 | W6 | Order approval amount changed | R2 | approval_input_changed |
| EOS-W6-008 | W6 | Inventory schema unit drift | R0 | schema_drift |
| EOS-W6-009 | W6 | Injected supplier note | R0 | prompt_injection |
| EOS-W6-010 | W6 | MRP connector timeout | R0 | timeout |
| EOS-W6-011 | W6 | Crash after order unknown | R2 | crash_after_effect_before_receipt |
| EOS-W6-012 | W6 | Order budget exhausted | R2 | unknown_side_effect_budget_exhausted |
| EOS-W7-001 | W7 | Discover read tool | R0 | happy |
| EOS-W7-002 | W7 | Noisy tool intent | R0 | noisy |
| EOS-W7-003 | W7 | Tool names ambiguous | R0 | ambiguous |
| EOS-W7-004 | W7 | Read follow-up same capability | R0 | chat_followup |
| EOS-W7-005 | W7 | Capability revoked | R0 | acl_revoked |
| EOS-W7-006 | W7 | Tool effect becomes unknown | R0 | schema_drift |
| EOS-W7-007 | W7 | Description injection | R0 | prompt_injection |
| EOS-W7-008 | W7 | MCP request timeout | R0 | timeout |
| EOS-W7-009 | W7 | MCP transient network | R0 | transient_network |
| EOS-W7-010 | W7 | Malformed output | R0 | schema_drift |
| EOS-W7-011 | W7 | Unknown side-effect zero budget | R0 | unknown_side_effect_budget_exhausted |
| EOS-W7-012 | W7 | Fake read mobile interaction | R0 | accessibility_mobile |
| EOS-W8-001 | W8 | Workspace morning draft | R1 | happy |
| EOS-W8-002 | W8 | Noisy scheduled request | R1 | noisy |
| EOS-W8-003 | W8 | Ambiguous workspace | R1 | ambiguous |
| EOS-W8-004 | W8 | Follow-up compact agenda | R1 | chat_followup |
| EOS-W8-005 | W8 | Workspace ACL revoked at wake | R1 | acl_revoked |
| EOS-W8-006 | W8 | Approval changed schedule target | R3 | approval_input_changed |
| EOS-W8-007 | W8 | Scheduler payload drift | R1 | schema_drift |
| EOS-W8-008 | W8 | Task injection outbound | R1 | prompt_injection |
| EOS-W8-009 | W8 | Context read timeout | R1 | timeout |
| EOS-W8-010 | W8 | Duplicate wakeup event | R1 | duplicate_submission |
| EOS-W8-011 | W8 | Restart partial morning draft | R1 | restart_partial_completion |
| EOS-W8-012 | W8 | Crash after internal draft | R1 | crash_after_effect_before_receipt |
