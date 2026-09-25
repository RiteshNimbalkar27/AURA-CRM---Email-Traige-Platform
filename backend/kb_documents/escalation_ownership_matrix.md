# Escalation and Ownership Matrix

**Version:** 1.0.0
**Last Updated:** 2024-01-01

This matrix defines the routing rules, SLAs, and ownership for the 5 standard escalation tiers at Nexus Software Inc.

### 1. Security Incidents
*(Examples: Ransomware, data breach, leaked credentials, unauthorized access, extortion)*
- **Queue**: `security`
- **Owner**: SecOps team
- **Contact**: secops@nexus.example (24/7 pager)
- **SLA**: Immediate response (<15 minutes)
- **CRITICAL RULE**: Do not reply to the customer or acknowledge the incident in writing until SecOps clears it. Escalate to the CISO if unresolved within 1 hour.

### 2. Legal and Compliance
*(Examples: DSAR, GDPR requests, cease-and-desist, lawsuit threats, regulatory inquiry)*
- **Queue**: `legal_compliance`
- **Owner**: Legal team
- **Contact**: legal@nexus.example (DSARs specifically route to privacy@nexus.example)
- **SLA**: Response acknowledgement within 2 hours; substantive response within 4 hours.
- **Action**: Send the standard holding acknowledgement template confirming receipt and noting the 30-day statutory response window.

### 3. Reputation and PR
*(Examples: Public review threats, press inquiry, investor inquiry, social media crisis)*
- **Queue**: `reputation_retention`
- **Owner**: PR team + Customer Experience lead
- **Contact**: pr@nexus.example
- **SLA**: Response within 1 hour
- **Action**: Trigger web intelligence monitoring for mention tracking. Offer retention escalation to the CSM within the same contact flow.

### 4. Billing and Product Support
*(Examples: Refunds, billing disputes, product bugs, feature questions, outages)*
- **Queue**: `support_operations`
- **Owner**: Support team
- **SLA**: Standard response time per the customer's plan tier (Enterprise <1h, Professional <4h, Starter <24h).
- **Action**: Standard support operations: check account status, apply SLA credits, escalate to engineering if a bug is confirmed.

### 5. Internal Messages
*(Examples: Communications from @demo-company.example or internal staff)*
- **Queue**: `internal`
- **Owner**: Relevant team lead
- **SLA**: Best-effort routing
