"""Factual dispatch/exposure preconditions; never infer escrow or payment from prose."""
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
import os


def require_paid_offer(proof):
    """Validate the recorded monetary claim, not whether a payer will honour it.

    An absent USD valuation is unknown, not permission to spend engineering time.
    USD-denominated legacy proofs can use their explicit face amount. Other
    currencies require the door's observed USD valuation. No funding is invented.
    """
    if not isinstance(proof, dict):
        raise ValueError('Paid offer evidence missing')
    funding = proof.get('funding')
    if not isinstance(funding, dict):
        raise ValueError('Paid offer funding missing')
    unpriced = (proof.get('funding_status') == 'UNPRICED_OWNER_REQUEST'
                or str(funding.get('currency', '')).upper() == 'FOUNDER')
    if unpriced:
        if os.environ.get('ALLOW_UNPRICED_FOUNDER', 'false').lower() in ('true', '1'):
            return
        raise ValueError('Dispatch blocked: unpriced issue violates No Free Service policy')
    raw = funding.get('usd_value')
    if raw in (None, '') and str(funding.get('currency', '')).upper() in ('USD', 'USDC', 'USDT'):
        raw = funding.get('amount')
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('Paid offer USD valuation missing or invalid') from None
    if not value.is_finite() or value <= 0:
        raise ValueError('Paid offer USD valuation must be finite and positive')


def funding_freshness_refusal(context, funding, *, now=None):
    """Apply the existing age policy to the cited offer, never to bot presence.

    A fresh unrelated comment/push does not renew an old promise. A fresh cited
    offer can support an old issue. This is a review hold, not proof of non-payment.
    Platform membership and bot comments alone do not prove money is in escrow.
    """
    issue = context['issue']
    if not issue.get('created_at'):
        return None  # Older/offline contracts lack age observations; do not invent one.
    now = now or datetime.now(timezone.utc)
    try:
        created = datetime.fromisoformat(str(issue['created_at']).replace('Z', '+00:00'))
        if created.tzinfo is None:
            raise ValueError('Issue creation timezone missing')
        age = (now - created).total_seconds() / 86400
        if age < 0:
            return 'FUNDING_FRESHNESS_UNVERIFIED'
        if age <= 60:
            return None
        source = next((d for d in [issue, *context.get('comments', [])]
                       if d.get('html_url') == funding.get('source_url')), None)
        # updated_at can be changed by unrelated activity; use publication of the
        # actual cited monetary offer. A changed old offer needs an agent review.
        offered = datetime.fromisoformat(str((source or {}).get('created_at', '')).replace('Z', '+00:00'))
        if offered.tzinfo is None:
            raise ValueError('Offer publication timezone missing')
        elapsed = (now - offered).total_seconds() / 86400
        return None if 0 <= elapsed <= 30 else 'FUNDING_FRESHNESS_REVIEW_REQUIRED'
    except (ValueError, TypeError, OverflowError):
        return 'FUNDING_FRESHNESS_UNVERIFIED'
