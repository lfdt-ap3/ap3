<!-- markdownlint-disable MD041 -->
<h1><strong>Finance & Banking</strong></h1>

## Joint Credit Risk Assessment

**Challenge:**
Banks need to assess credit risk for customers who may have relationships with multiple financial institutions. However, sharing customer data directly violates privacy regulations and exposes competitive intelligence about customer portfolios.

AP3 enables bank's AI agents to compute joint credit-risk scores using **Secure Function Evaluation (SFE)** without revealing individual customer data, transaction histories, or proprietary risk models.

**Example Scenario:**

Bank A and Bank B want to assess the creditworthiness of a shared customer. Using AP3, agents jointly compute a risk score that combines:

* Bank A's transaction history (encrypted)
* Bank B's credit utilization data (encrypted)
* Both banks' proprietary risk models (hidden)

The result is a comprehensive risk score without either bank seeing the other's data or algorithms.

## Fraud Pattern Detection

**Challenge:**
Financial institutions need to identify fraudulent accounts and patterns across organizations, but sharing fraud databases would expose customer information and proprietary fraud detection strategies.

AP3 enables bank's AI agents to identify overlapping fraud patterns between their databases without revealing non-matching entries or the full contents of their fraud lists.

**Example Scenario:**

Bank X has flagged 1,000 suspicious accounts. Bank Y maintains a fraud database of 5,000 known fraudulent accounts. Using PSI, they discover 50 overlapping accounts, enabling both banks to:

* Immediately freeze the matched accounts
* Share fraud indicators (not raw data) to improve detection
* Build better fraud models without exposing their databases
