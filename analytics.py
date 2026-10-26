"""Phase 2D QuickCart operations analytics, independent from Streamlit.

Historical data is a CLEANED CSV SNAPSHOT. SQLite stats are separate, live local
administrative-request counts. No customer messages or IDs enter the aggregates.

Denominators and date filtering:
- Selected dates mean ORDER PLACEMENT dates, inclusive, not ticket creation dates.
- Courier/category filters select an order cohort; ticket channel filters tickets only.
- Lost+delayed rate uses SHIPPED orders (excludes cancelled-before-shipping).
- Resolution hours use RESOLVED tickets only; CSAT uses valid rated tickets only.
- Leak is an ESTIMATE from historical recorded refund fields, not confirmed payouts.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from ticket_store import STATES, connection

BAD = {'LOST_IN_TRANSIT', 'DELAYED_IN_TRANSIT'}
CANCELLED = 'CANCELLED_BEFORE_SHIP'
REPLACEMENT = 'Resolved - Replacement Sent'
FULL_REFUND = 'Resolved - Full Refund Issued'
DAMAGED = 'Damaged / Defective Item Received'
COD = 'Cash on Delivery (COD)'
LEAK_RULES = (
    'R1_delayed_full_refund',
    'R2_replacement_plus_cash',
    'R3_COD_cancelled_refund',
    'R4_exceeds_cap',
)


def prepare_data(orders: pd.DataFrame, tickets: pd.DataFrame):
    """Validate required fields and return normalized, unmodified-source copies."""
    required_o = {'order_id', 'order_date', 'courier_partner', 'product_category',
                  'delivery_status', 'order_amount', 'payment_method'}
    required_t = {'ticket_id', 'order_id', 'ticket_created_at', 'resolution_status',
                  'refund_amount', 'resolution_hours', 'csat_score', 'channel', 'is_open'}
    if (missing := required_o - set(orders.columns)):
        raise ValueError(f'Orders data missing required columns: {sorted(missing)}')
    if (missing := required_t - set(tickets.columns)):
        raise ValueError(f'Tickets data missing required columns: {sorted(missing)}')
    if orders['order_id'].isna().any() or orders['order_id'].duplicated().any():
        raise ValueError('Orders must have one non-null row per order_id.')
    if tickets['ticket_id'].isna().any() or tickets['ticket_id'].duplicated().any():
        raise ValueError('Tickets must have one non-null row per ticket_id.')

    o, t = orders.copy(), tickets.copy()
    o['order_date'] = pd.to_datetime(o['order_date'], errors='coerce')
    t['ticket_created_at'] = pd.to_datetime(t['ticket_created_at'], errors='coerce')
    o['order_amount'] = pd.to_numeric(o['order_amount'], errors='coerce')
    t['refund_amount'] = pd.to_numeric(t['refund_amount'], errors='coerce')
    t['resolution_hours'] = pd.to_numeric(t['resolution_hours'], errors='coerce')
    t['csat_score'] = pd.to_numeric(t['csat_score'], errors='coerce')
    t.loc[~t['csat_score'].between(1, 5), 'csat_score'] = float('nan')
    t['is_open'] = t['is_open'].map(lambda v: v if isinstance(v, bool) else str(v).strip().lower() == 'true')
    return o, t


def select_cohort(orders: pd.DataFrame, tickets: pd.DataFrame, *,
                  start_date: Optional[date] = None, end_date: Optional[date] = None,
                  couriers: Optional[list[str]] = None, categories: Optional[list[str]] = None,
                  channels: Optional[list[str]] = None):
    """Filter orders by placement date/courier/category, then tickets to selected orders.

    Channel applies to ticket metrics ONLY. No ticket metrics are double counted
    when joining to the unique orders table.
    """
    o, t = prepare_data(orders, tickets)
    if start_date is not None:
        o = o[o['order_date'].dt.date >= start_date]
    if end_date is not None:
        o = o[o['order_date'].dt.date <= end_date]
    if couriers is not None:
        o = o[o['courier_partner'].isin(couriers)]
    if categories is not None:
        o = o[o['product_category'].isin(categories)]
    t = t[t['order_id'].isin(o['order_id'])]
    if channels is not None:
        t = t[t['channel'].isin(channels)]
    return o.copy(), t.copy()


def attach_order_facts(orders: pd.DataFrame, tickets: pd.DataFrame):
    """Keep only a narrow validated set of order fields in a many-to-one join."""
    facts = orders[['order_id', 'courier_partner', 'delivery_status', 'order_amount',
                    'payment_method', 'product_category']]
    return tickets.merge(facts, on='order_id', how='left', validate='many_to_one')


def historical_leakage(joined: pd.DataFrame):
    """Flag original Part 1 leakage patterns and deduplicate the estimate per ticket.

    The per-rule amounts are diagnostic and can overlap. The unique total uses the
    LARGEST applicable excess for each ticket (as in the user's Part 1 work),
    not a sum of overlapping rule estimates. Missing order prices cannot be
    cap-checked and should not be silently replaced with zero.
    """
    j = joined.copy()
    if j.empty:
        return j.assign(any_violation=pd.Series(dtype=bool),
                        estimated_leak_inr=pd.Series(dtype=float),
                        missing_amount_for_cap=pd.Series(dtype=bool)), rule_summary(j)
    refund = pd.to_numeric(j['refund_amount'], errors='coerce')
    amount = pd.to_numeric(j['order_amount'], errors='coerce')
    status = j['delivery_status']
    res = j['resolution_status']
    payment = j['payment_method']
    j['R1_delayed_full_refund'] = (status.eq('DELAYED_IN_TRANSIT') &
                                    res.eq(FULL_REFUND) & refund.gt(100))
    j['R2_replacement_plus_cash'] = res.eq(REPLACEMENT) & refund.gt(0)
    j['R3_COD_cancelled_refund'] = (payment.eq(COD) & status.eq(CANCELLED) & refund.gt(0))
    j['R4_exceeds_cap'] = refund.gt(amount + 100.01) & amount.notna()
    j['any_violation'] = j[list(LEAK_RULES)].any(axis=1)
    excess = pd.DataFrame({
        'R1_delayed_full_refund': (refund - 100).where(j['R1_delayed_full_refund'], 0),
        'R2_replacement_plus_cash': refund.where(j['R2_replacement_plus_cash'], 0),
        'R3_COD_cancelled_refund': refund.where(j['R3_COD_cancelled_refund'], 0),
        'R4_exceeds_cap': (refund - amount - 100).where(j['R4_exceeds_cap'], 0),
    }, index=j.index).fillna(0).clip(lower=0)
    j['estimated_leak_inr'] = excess.max(axis=1).round(2)
    j['missing_amount_for_cap'] = amount.isna() | amount.le(0)
    return j, rule_summary(j, excess)


def rule_summary(joined: pd.DataFrame, excess: Optional[pd.DataFrame] = None):
    records = []
    for name in LEAK_RULES:
        matched = int(joined[name].sum()) if name in joined else 0
        value = round(float(excess[name].sum()), 2) if excess is not None else 0.0
        records.append({'rule': name, 'flagged_tickets': matched,
                        'per_rule_estimate_inr': value})
    return pd.DataFrame(records)


def overview(orders: pd.DataFrame, tickets: pd.DataFrame):
    shipped = orders['delivery_status'].ne(CANCELLED)
    bad = orders['delivery_status'].isin(BAD)
    resolved = tickets[~tickets['is_open'] & tickets['resolution_hours'].notna() &
                       tickets['resolution_hours'].ge(0)]
    rated = tickets['csat_score'].dropna()
    joined, rule_stats = historical_leakage(attach_order_facts(orders, tickets))
    return {
        'orders': int(len(orders)), 'shipped_orders': int(shipped.sum()),
        'bad_delivery_orders': int(bad.sum()),
        'lost_delayed_rate_pct': round(float(bad.sum() / shipped.sum() * 100), 2) if shipped.any() else None,
        'gmv_inr': round(float(orders['order_amount'].where(orders['order_amount'].gt(0)).sum()), 2),
        'invalid_order_amounts': int((orders['order_amount'].isna() | orders['order_amount'].le(0)).sum()),
        'tickets': int(len(tickets)), 'open_tickets': int(tickets['is_open'].sum()),
        'resolved_tickets': int(len(resolved)),
        'avg_resolution_hours': round(float(resolved['resolution_hours'].mean()), 2) if len(resolved) else None,
        'resolved_over_24h_pct': round(float(resolved['resolution_hours'].gt(24).mean() * 100), 2) if len(resolved) else None,
        'avg_csat': round(float(rated.mean()), 2) if len(rated) else None,
        'rated_tickets': int(len(rated)),
        'recorded_refunds_inr': round(float(tickets['refund_amount'].sum()), 2),
        'violating_tickets': int(joined['any_violation'].sum()),
        'estimated_leak_inr': round(float(joined['estimated_leak_inr'].sum()), 2),
        'uncertain_cap_tickets': int(joined['missing_amount_for_cap'].sum()) if len(joined) else 0,
    }


def courier_performance(orders: pd.DataFrame, tickets: pd.DataFrame):
    joined, _ = historical_leakage(attach_order_facts(orders, tickets))
    rows = []
    for name, sub in orders.groupby('courier_partner', dropna=False):
        shipped = sub['delivery_status'].ne(CANCELLED)
        bad = sub['delivery_status'].isin(BAD)
        ct = joined[joined['courier_partner'] == name]
        resolved = ct.loc[~ct['is_open'] & ct['resolution_hours'].notna() & ct['resolution_hours'].ge(0)]
        rated = ct['csat_score'].dropna()
        rows.append({
            'courier_partner': name, 'orders': int(len(sub)),
            'shipped_orders': int(shipped.sum()), 'lost_delayed': int(bad.sum()),
            'lost_delayed_rate_pct': round(float(bad.sum()/shipped.sum()*100), 2) if shipped.any() else None,
            'historical_tickets': int(len(ct)), 'open_tickets': int(ct['is_open'].sum()),
            'avg_resolution_hours': round(float(resolved['resolution_hours'].mean()), 2) if len(resolved) else None,
            'avg_csat': round(float(rated.mean()), 2) if len(rated) else None,
            'flagged_tickets': int(ct['any_violation'].sum()),
            'estimated_leak_inr': round(float(ct['estimated_leak_inr'].sum()), 2),
        })
    return pd.DataFrame(rows, columns=['courier_partner', 'orders', 'shipped_orders', 'lost_delayed',
                                      'lost_delayed_rate_pct', 'historical_tickets', 'open_tickets',
                                      'avg_resolution_hours', 'avg_csat', 'flagged_tickets',
                                      'estimated_leak_inr']).sort_values('lost_delayed_rate_pct', ascending=False,
                                                                         na_position='last').reset_index(drop=True)


def delivery_breakdown(orders: pd.DataFrame):
    return (orders.groupby('delivery_status', dropna=False).size()
            .rename('orders').reset_index().sort_values('orders', ascending=False))


def support_by_channel(tickets: pd.DataFrame):
    rows = []
    for channel, sub in tickets.groupby('channel', dropna=False):
        resolved = sub.loc[~sub['is_open'] & sub['resolution_hours'].notna() & sub['resolution_hours'].ge(0)]
        rated = sub['csat_score'].dropna()
        rows.append({'channel': channel, 'tickets': int(len(sub)),
                     'open_tickets': int(sub['is_open'].sum()),
                     'avg_resolution_hours': round(float(resolved['resolution_hours'].mean()), 2) if len(resolved) else None,
                     'resolution_over_24h_pct': round(float(resolved['resolution_hours'].gt(24).mean()*100), 2) if len(resolved) else None,
                     'avg_csat': round(float(rated.mean()), 2) if len(rated) else None,
                     'valid_csat_count': int(len(rated))})
    return pd.DataFrame(rows, columns=['channel', 'tickets', 'open_tickets', 'avg_resolution_hours',
                                      'resolution_over_24h_pct', 'avg_csat', 'valid_csat_count']).sort_values(
                                          'tickets', ascending=False).reset_index(drop=True)


def weekly_ticket_activity(tickets: pd.DataFrame):
    """Group by week of ticket CREATION, with current snapshot open/resolved statuses."""
    if tickets.empty:
        return pd.DataFrame(columns=['week_start', 'tickets_created', 'currently_open'])
    data = tickets[tickets['ticket_created_at'].notna()].copy()
    if data.empty:
        return pd.DataFrame(columns=['week_start', 'tickets_created', 'currently_open'])
    data['week_start'] = (data['ticket_created_at'].dt.normalize() -
                          pd.to_timedelta(data['ticket_created_at'].dt.weekday, unit='D'))
    return (data.groupby('week_start').agg(tickets_created=('ticket_id', 'size'),
                                          currently_open=('is_open', 'sum')).reset_index()
            .sort_values('week_start'))


def sqlite_overview(db_path, *, now: Optional[datetime] = None):
    """Read aggregate metrics via SQL, including ALL requests, not list_requests limit 200.

    SQL only selects aggregates; no customer-question text is returned.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = (now.astimezone(timezone.utc) - timedelta(days=7)).isoformat(timespec='seconds')
    with connection(db_path) as db:
        count_row = db.execute('''
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(CASE WHEN status IN ('SUBMITTED','IN_REVIEW','FOLLOW_UP_APPROVED') THEN 1 ELSE 0 END),0) AS active,
                   COALESCE(SUM(requires_reconciliation),0) AS needs_reconciliation,
                   COALESCE(SUM(CASE WHEN created_at_utc >= ? THEN 1 ELSE 0 END),0) AS submitted_last_7_days
            FROM support_requests''', (cutoff,)).fetchone()
        event_count = db.execute('SELECT COUNT(*) FROM request_events').fetchone()[0]
        grouped = db.execute('SELECT status, COUNT(*) AS requests FROM support_requests GROUP BY status').fetchall()
        daily = db.execute('''SELECT substr(created_at_utc,1,10) AS created_day, COUNT(*) AS requests
                              FROM support_requests GROUP BY substr(created_at_utc,1,10)
                              ORDER BY created_day''').fetchall()
    status_counts = {status: 0 for status in STATES}
    status_counts.update({row['status']: int(row['requests']) for row in grouped})
    return {
        'total': int(count_row['total']),
        'active': int(count_row['active']),
        'needs_reconciliation': int(count_row['needs_reconciliation']),
        'submitted_last_7_days': int(count_row['submitted_last_7_days']),
        'audit_events': int(event_count),
        'by_status': pd.DataFrame([{'status': key, 'requests': n} for key, n in status_counts.items()]),
        'daily': pd.DataFrame([dict(row) for row in daily], columns=['created_day', 'requests']),
    }
