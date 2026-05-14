---
hide:
    - toc
---

<!-- markdownlint-disable MD041 -->
<h1><strong>PSI</strong></h1>

PSI lets two parties learn **which elements they have in common** without revealing the rest. Conceptually:

$$ \text{PSI}(A, B) = A \cap B $$

In practice, the AP3 PSI variant returns a result scoped to the initiator's question — typically *"is element X in B?"* (a boolean) or *"how many of my elements are in B?"* (a count) — without ever exposing the contents of $B$ to the initiator or the contents of $A$ to the receiver.

## Interactive explanation

<iframe src="../../assets/psi-walkthrough.html" width="100%" height="660" style="border: 1px solid #e0e0e0; border-radius: 6px; display: block;" title="Two-stamp envelope walkthrough"></iframe>

??? note "Why does the B stamp survive when A is peeled off?"
    The wrapping/stamping picture works beautifully for the journey but cracks at this exact moment. The fix is a small upgrade to the metaphor.

    Imagine Provider's stamp B isn't a postage sticker laid on top of the wrapper. It's a steel die pressed firmly against the wrapped lump — pressed hard enough that it punches *through* wrapper A and leaves a permanent impression on the ball underneath. The wrapper is just a soft envelope. The stamp's mark lives on the ball itself.

    > The stamp pushes through the wrapper, therefore it leaves a push mark. Peel the wrapper off and the push mark is still there.

    So when Consumer peels A away, the wrapper comes off clean — but the indentation B punched into the ball stays right where it was. And critically: it's the same indentation Provider would have left if it had stamped the bare ball directly. Which is exactly what Provider did to every ball in its own list. Same procedure on both sides → directly comparable outputs. That equality check at the end is only possible because of this.

??? note "Underneath the metaphor"
    The ball is a point $P$ on an elliptic curve. $A$ is Consumer's secret scalar $a$; $B$ is Provider's secret scalar $b$. The protocol computes:

    $$
    \begin{aligned}
    \text{Consumer:} \quad & a \cdot P && \text{(blind)} \\
    \text{Provider:} \quad & b \cdot (a \cdot P) = a \cdot b \cdot P && \text{(evaluate — scalar mul commutes)} \\
    \text{Consumer:} \quad & a^{-1} \cdot (a \cdot b \cdot P) = b \cdot P && \text{(unblind)}
    \end{aligned}
    $$

    The $a$ and $a^{-1}$ annihilate. $b$ was never tangled with $a$, so it survives untouched. What's left is $b \cdot P$ — identical to what Provider produces on every ball in its own list (each is $b \cdot P_i$). Equality comparison works because both sides went through the same $b$-multiplication, on the same hash-to-curve output, and nothing else.

    Without commutativity, peeling A would smear B in some recoverable way ($a^{-1} \cdot b \cdot a \cdot P$ wouldn't simplify to anything useful) and the comparison would silently fail. Every OPRF in the wild — 2HashDH, the constructions in RFC 9497 — is built on a commutative group operation for exactly this reason.

## How it runs (4 envelopes, end to end)

PSI exchanges four envelopes per session. The two messages from the initiator (`OB`) each carry their own signed [`PrivacyIntentDirective`](../directives.md) bound to that envelope's payload — every initiator→receiver message is independently authenticated.

| # | Direction | Phase | Payload | What happens |
|:--:|:--:|---|---|---|
| 1 | OB → BB | `init` | `commit(sid_0, blind)`         | Session kick-off. OB picks `sid_0` and a random blind value, then sends a hiding commitment to them. The signed intent rides here and authenticates OB. |
| 2 | BB → OB | `msg0` | `sid_1`                        | BB picks its half of the session ID (`sid_1`) and sends it in the clear. BB has no way to see `sid_0` yet, so it can't grind. |
| 3 | OB → BB | `msg1` | `sid_0 ‖ blind ‖ psc1`         | OB opens the commit (revealing `sid_0` + `blind`), derives `session_id = H(sid_0, sid_1)`, blinds its query, and sends `psc_msg1`. BB verifies the commit opens correctly. A fresh signed intent on this envelope binds the actual payload. |
| 4 | BB → OB | `msg2` | `psc2`                         | BB runs its half of the cryptographic protocol against its private set, returns the response. BB learns nothing about OB's query. |
| — | (local) | —      | result                         | OB processes `msg2` locally and learns the answer. BB never learns the answer. |

The contributory session_id (`H(sid_0, sid_1)` with a commit-then-reveal exchange) means neither party alone chooses the session_id: OB is locked into `sid_0` by the commit before seeing `sid_1`, and BB has to pick `sid_1` before seeing `sid_0`. This prevents either party from grinding for a session_id that produces a favorable transcript.

The full cryptographic details are encapsulated by the operation implementation; from the SDK side, you call `PSIOperation.start(...)` / `.receive(...)` / `.process(...)` and the framework drives the four envelopes for you (or use `PrivacyAgent.run_intent(...)` to drive the whole exchange end-to-end over A2A).

## Use cases

* **Customer overlap analysis** between companies that don't want to swap customer lists.
* **Fraudulent account detection** across institutions, surfacing only the matches.
* **Supply chain partner verification** — confirming a counterparty exists in an approved-supplier list without exposing the list.
* **Sanctions / blacklist screening** without disclosing either side.

## What PSI does *not* do

* It does not reveal the receiver's full set to the initiator.
* It does not reveal the initiator's query to the receiver.
* It does not, by itself, prove that the receiver actually used the dataset it advertised in its [commitment](../commitments.md). That gap is what proof-of-computation work is intended to close — see the [Distribution](../operations.md#distribution) section and the [Roadmap](../roadmap.md).

For a hands-on tutorial, see the [`psi_simple`](https://github.com/lfdt-ap3/ap3/tree/main/examples/psi_simple) and [`psi_adk_simple`](https://github.com/lfdt-ap3/ap3/tree/main/examples/psi_adk_simple) examples in the main repository.
