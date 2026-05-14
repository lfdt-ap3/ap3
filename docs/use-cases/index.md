<!-- markdownlint-disable MD041 -->
<h1><strong>Overview</strong></h1>

AP3 enables privacy-preserving collaboration across industries. The pages in this section explore real-world scenarios where AP3 creates significant value by allowing organizations to collaborate on sensitive data without compromising confidentiality.

## How to read these pages

Each use case follows the same shape:

1. **Challenge** — the business problem and why traditional data-sharing falls short (regulatory, competitive, or both).
2. **AP3 mechanism** — the privacy-preserving primitive that applies (PSI, Secure Function Evaluation, Secure Dot Product, …).
3. **Example scenario** — a concrete walk-through with the inputs each side holds, what they exchange, and what they each learn at the end.

The same patterns generalize beyond the industries listed. If you're trying to evaluate whether AP3 fits your problem, look for the *shape* of the data exchange — "we both have lists and want to compare them", "we both have numbers and want a joint score", "we want a yes/no answer based on a counterparty's private data" — rather than the industry label.

> Note: a few of the operations mentioned below (Secure Function Evaluation, Secure Dot Product) are **roadmap operations**, not yet shipped in the SDK. Today's reference implementation focuses on PSI; see the [Roadmap](../roadmap.md) for what's coming next.

## In this section

* **[Monetize Your Data](monetize-with-service-provider.md)** — the operator's guide to standing up a service-provider agent that sells answers, not rows.
* **[Finance & Banking](finance.md)** — joint credit risk, cross-bank fraud pattern detection.
* **[Reputation checks](hr.md)** — secure background, sanctions, and cross-company blacklist screening for hiring, delivery onboarding, KYC, vendor due diligence.
* **[Supply Chain Evaluation](fmcg.md)** — production-demand optimization, supplier quality matching, product compatibility scoring.
