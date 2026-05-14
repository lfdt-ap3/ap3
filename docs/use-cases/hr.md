<!-- markdownlint-disable MD041 -->
<h1><strong>Reputation checks</strong></h1>

## Cross-organization blacklist screening

**Challenge:**
A company needs to verify a candidate, contractor, or partner against blacklists, sanctions lists, or "do-not-onboard" databases held by other organizations. Sharing the candidate identifier exposes private HR data; sharing the blacklist exposes a competitive moat or violates the data subject's privacy. Both regulations and competitive concerns rule out direct data exchange.

AP3's **Private Set Intersection (PSI)** protocol lets the screening party check whether a single identifier appears in a counterparty's blacklist without revealing who they're checking, and without seeing the blacklist contents. Only matches are surfaced; non-matches stay invisible on both sides.

The same shape applies across industries — the data exchange is *always* "is this one person/entity in your private list?" — even if the industry framing changes.

**Example**

Company A is hiring a driver (or onboarding a delivery partner, or running KYC on a new customer) and wants to check the candidate against Company B's blacklist of 10,000 flagged individuals. Using PSI:

* Company A provides encrypted candidate identifiers
* Company B provides encrypted blacklist entries
* The protocol returns only matches (if any)
* Company B never learns who Company A is checking
* Company A never sees Company B's full blacklist

The same protocol covers hiring, cross-company delivery onboarding, KYC, sanctions screening, vendor due diligence, and any other situation where one party needs to query the other's reputation database with a single identifier.
