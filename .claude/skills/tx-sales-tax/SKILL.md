---
name: tx-sales-tax
description: How to resolve recoup review-queue items for Texas purchases. Use when reviewing Texas lines marked NEEDS_REVIEW.
---

# Resolving Texas review-queue items

Each queue item needs a disposition and, usually, a document. Ask the client for the document; never assume it exists.

| Queue reason | What settles it | Disposition if the client can't produce it |
|---|---|---|
| REVIEW_UTILITY | A predominant-use study showing more than 50% of the meter's use is exempt (34 TAC §3.295). Studies cover one meter and need periodic updates. | NO CLAIM |
| REVIEW_REPAIR_PART | Evidence that the part replaces a part of exempt manufacturing equipment and has a useful life over six months | NO CLAIM |
| Reviewer disagreed | The invoice and a short description from the plant of where the item is used | NO CLAIM |
| Freight on mixed invoice | Split the freight by the exempt share of the goods only if the invoice supports it | NO CLAIM for the taxable share |
| No rule profile for state | Run the rules-researcher subagent | Hold |

## Things that commonly mislead

- "Electric" in a description does not mean a utility bill. Electric forklifts are intraplant transportation, which is taxable.
- Hand tools, intraplant transportation equipment, and office items are excluded from the manufacturing exemption (Tex. Tax Code §151.318(c)).
- Data processing services are taxed on 80% of the price (§151.351). Tax on 100% is a 20% overpayment, not a full refund.
- Delivery charges follow the item they deliver (§151.007).

Verify every citation against the current statute before a packet is approved. These notes are a starting point, not legal advice.
