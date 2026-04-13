# Nexus Platform — Company Policies

## 1. Refund Policy

Nexus offers a 30-day money-back guarantee for all new subscriptions on the Starter and Pro plans. Enterprise customers are subject to the refund terms negotiated in their master service agreement (MSA). To request a refund, customers must submit a written request to billing@nexus.ai within 30 days of their initial payment. Refunds are processed within 10 business days and credited to the original payment method. Partial refunds are not available for mid-cycle cancellations; accounts cancelled mid-billing period retain access until the end of the paid period. Usage-based overages and professional services fees are non-refundable. In cases of service outage exceeding 99.5% monthly uptime SLA breach, customers may apply for a pro-rated credit per the SLA credit schedule in Section 3.

## 2. Service Level Agreement (SLA) Commitments

Nexus commits to the following uptime guarantees by plan tier:

- **Starter**: 99.0% monthly uptime. Scheduled maintenance windows are excluded and communicated at least 48 hours in advance.
- **Pro**: 99.5% monthly uptime. Maximum scheduled maintenance window of 2 hours per month, communicated 72 hours in advance.
- **Enterprise**: 99.9% monthly uptime. Emergency maintenance must be approved by the customer's designated technical contact except in the event of an active security incident.

SLA credits are calculated as follows: for each full percentage point below the committed uptime, the customer receives a credit equal to 10% of the monthly fee for that tier. Credits are applied to the next invoice and do not exceed 30% of the monthly fee. Credits do not apply to outages caused by customer misconfiguration, third-party service failures outside Nexus's control, or force majeure events.

Response time SLAs for support tickets:
- **Critical** (production system down): 1-hour initial response, 4-hour resolution target.
- **High** (significant feature impaired): 4-hour initial response, 24-hour resolution target.
- **Medium** (minor feature impaired): 24-hour initial response, 72-hour resolution target.
- **Low** (general question or feature request): 72-hour initial response, 2-week resolution target.

## 3. Escalation Procedures

When a support ticket is not resolved within the target resolution window, the following escalation path is triggered automatically:

1. **L1 → L2 Escalation**: If a Critical or High ticket exceeds 2x the resolution target without a status update, it is automatically reassigned to a senior support engineer and the customer's Customer Success Manager (CSM) is notified.
2. **L2 → Engineering Escalation**: If the L2 engineer determines the issue requires a code fix or infrastructure change, the ticket is escalated to the on-call engineering team with a P1 designation in the internal issue tracker.
3. **Executive Escalation**: If a Critical ticket remains unresolved for more than 24 hours, the VP of Customer Success is automatically notified and a bridge call is scheduled with the customer within 2 hours.
4. **Vendor Escalation**: If the root cause involves a third-party dependency (e.g., AWS, Stripe, Twilio), the Support Lead coordinates escalation through the vendor's enterprise support channel.

Customers wishing to manually escalate any ticket may do so by emailing escalations@nexus.ai or calling the emergency support hotline provided in their onboarding documentation.

## 4. Data Retention and Deletion Policy

Nexus retains customer data for the duration of the active subscription plus a 90-day grace period after contract termination. During the grace period, customers may export their data via the API or request a full data export archive from their CSM. After the grace period, all customer data is deleted from production systems within 30 days and from backups within 90 days.

For customers subject to GDPR, CCPA, or other privacy regulations:
- **Right to Erasure (GDPR Article 17)**: Verified deletion requests are fulfilled within 30 days. A deletion confirmation certificate is provided upon request.
- **Data Portability (GDPR Article 20)**: Export requests are fulfilled within 15 business days in JSON or CSV format.
- **Data Processing Agreement (DPA)**: Available upon request for all Enterprise customers; Starter and Pro customers may download the standard DPA from the legal portal.

Audit logs are retained for 7 years to satisfy SOC 2 Type II and ISO 27001 requirements, regardless of subscription status. These logs contain event metadata (timestamps, user IDs, action types) but do not contain customer business data content after the 90-day grace period.

## 5. Customer Onboarding Policy

All new Enterprise customers are assigned a dedicated Customer Success Manager (CSM) within 48 hours of contract signing. The CSM is responsible for coordinating a structured 30-day onboarding program that includes:

- **Week 1**: Technical integration kickoff — API credentials, SSO configuration, and data connector setup.
- **Week 2**: Data ingestion and pilot workflow deployment — ingest first enterprise data source and run a live demo query.
- **Week 3**: Team training — administrator training (2 hours) and end-user training (1 hour per team).
- **Week 4**: Go-live review — success metrics baseline, escalation contacts confirmed, 90-day success plan agreed.

Pro customers receive a self-serve onboarding portal with video walkthroughs, a configuration wizard, and access to weekly group onboarding webinars. Starter customers have access to the documentation portal and community forum.
