"""Phase 2D Streamlit presentation of aggregated historical + SQLite metrics.

NOT authenticated! Local-only demonstrations with approved/synthetic datasets.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from analytics import (
    attach_order_facts, courier_performance, delivery_breakdown, historical_leakage,
    overview, prepare_data, select_cohort, sqlite_overview, support_by_channel,
    weekly_ticket_activity,
)


def money(value):
    return f'₹{value:,.0f}'


def metric_text(value, *, suffix='', decimals=1):
    return 'N/A' if value is None or pd.isna(value) else f'{value:,.{decimals}f}{suffix}'


def chart_table(data, x, y, chart='bar', *, label=None):
    """Make charts from aggregates only; never expose raw customer/ticket rows."""
    if data.empty or y not in data or data[y].isna().all():
        st.info('No measurements available for this selection.')
        return
    clean = data[[x, y]].dropna().set_index(x)
    if chart == 'line':
        st.line_chart(clean, use_container_width=True)
    else:
        st.bar_chart(clean, use_container_width=True, horizontal=False)


def render_admin_dashboard(orders: pd.DataFrame, tickets: pd.DataFrame, db_path, user=None):
    from access_control import authorize_analytics
    authorize_analytics(user)
    st.title('📊 QuickCart Operations Dashboard')
    st.caption('Phase 2D · Historical CSV operations metrics + separate live local SQLite request counts')
    st.info('Admin-only reporting. Use synthetic or explicitly authorized customer data; this is not a production system.')

    o, t = prepare_data(orders, tickets)
    valid_dates = o['order_date'].dropna().dt.date
    if valid_dates.empty:
        st.error('No valid order dates found in the historical dataset.')
        return
    date_min, date_max = valid_dates.min(), valid_dates.max()
    couriers = sorted(str(v) for v in o['courier_partner'].dropna().unique())
    categories = sorted(str(v) for v in o['product_category'].dropna().unique())
    channels = sorted(str(v) for v in t['channel'].dropna().unique())

    st.markdown('### Historical snapshot filters')
    dc, cc, catc = st.columns([2, 2, 2])
    with dc:
        selected_dates = st.date_input('Order placement date (inclusive)', value=(date_min, date_max),
                                       min_value=date_min, max_value=date_max, key='dash_dates')
    with cc:
        selected_couriers = st.multiselect('Couriers', couriers, default=couriers, key='dash_couriers')
    with catc:
        selected_categories = st.multiselect('Product categories', categories, default=categories, key='dash_categories')
    selected_channels = st.multiselect('Support channels (ticket metrics only)', channels,
                                       default=channels, key='dash_channels')
    st.caption('Date, courier and category filters select orders, then match their historical tickets. '
               'Support channel filters affect ticket measures, not order counts. '
               'SQLite request statistics are current and intentionally NOT affected by historical filters.')
    if not isinstance(selected_dates, (tuple, list)) or len(selected_dates) != 2:
        st.info('Select both date endpoints to apply the dashboard filters.')
        return
    start, end = selected_dates
    if start > end:
        st.error('Start date must not be after end date.')
        return

    fo, ft = select_cohort(o, t, start_date=start, end_date=end,
                           couriers=selected_couriers, categories=selected_categories,
                           channels=selected_channels)
    stats = overview(fo, ft)
    try:
        live = sqlite_overview(db_path)
    except Exception as exc:
        st.error('Could not read the local SQLite request summary. Check the database file and permissions.')
        st.caption(f'Local database diagnostic: {type(exc).__name__}')
        live = None

    overview_tab, courier_tab, support_tab, refund_tab, sqlite_tab = st.tabs([
        'Overview', 'Courier performance', 'Support SLA & CSAT', 'Refund policy audit', 'Live SQLite requests'])

    with overview_tab:
        st.markdown('#### Historical snapshot KPIs')
        k1, k2, k3, k4 = st.columns(4)
        k1.metric('Unique orders', f'{stats["orders"]:,}')
        k2.metric('Unique historical tickets', f'{stats["tickets"]:,}')
        k3.metric('Total order value', money(stats['gmv_inr']))
        k4.metric('Recorded cash refunds', money(stats['recorded_refunds_inr']))
        k5, k6, k7, k8 = st.columns(4)
        k5.metric('Lost/delayed · shipped', metric_text(stats['lost_delayed_rate_pct'], suffix='%'))
        k6.metric('Open historical tickets', f'{stats["open_tickets"]:,}')
        k7.metric('Avg resolved time', metric_text(stats['avg_resolution_hours'], suffix='h'))
        k8.metric('Valid CSAT average', metric_text(stats['avg_csat'], decimals=2) + ' / 5')
        if stats['invalid_order_amounts']:
            st.warning(f'{stats["invalid_order_amounts"]} selected orders have missing/invalid prices; '
                       'they count as orders but do not contribute to the order value.')
        if not len(fo):
            st.info('No orders matched these filters.')
        left, right = st.columns(2)
        with left:
            st.markdown('##### Delivery status distribution')
            chart_table(delivery_breakdown(fo), 'delivery_status', 'orders')
        with right:
            st.markdown('##### Historical ticket creation by week')
            activity = weekly_ticket_activity(ft)
            chart_table(activity, 'week_start', 'tickets_created', chart='line')
        st.caption('Historical data covers the original cleaned CSV snapshot, not live courier updates.')

    with courier_tab:
        st.markdown('#### Courier comparison')
        st.caption('Lost/delayed denominator = shipped orders only; cancelled-before-ship excluded. '
                   'Resolution time uses resolved tickets; CSAT uses valid ratings.')
        performance = courier_performance(fo, ft)
        a, b = st.columns(2)
        with a:
            st.markdown('##### Lost/delayed delivery rate (%)')
            chart_table(performance, 'courier_partner', 'lost_delayed_rate_pct')
        with b:
            st.markdown('##### Average resolution hours')
            chart_table(performance, 'courier_partner', 'avg_resolution_hours')
        st.dataframe(performance, hide_index=True, use_container_width=True)
        st.download_button('Download aggregated courier metrics (CSV)',
                           performance.to_csv(index=False).encode('utf-8'),
                           file_name='quickcart_courier_metrics.csv', mime='text/csv',
                           disabled=performance.empty)

    with support_tab:
        st.markdown('#### Support experience')
        left, middle, right = st.columns(3)
        left.metric('Resolved historical tickets', f'{stats["resolved_tickets"]:,}')
        middle.metric('Resolved > 24 hours', metric_text(stats['resolved_over_24h_pct'], suffix='%'))
        right.metric('Tickets with valid CSAT', f'{stats["rated_tickets"]:,}')
        by_channel = support_by_channel(ft)
        a, b = st.columns(2)
        with a:
            st.markdown('##### Average support resolution (hours)')
            chart_table(by_channel, 'channel', 'avg_resolution_hours')
        with b:
            st.markdown('##### Average CSAT (1–5)')
            chart_table(by_channel, 'channel', 'avg_csat')
        st.dataframe(by_channel, use_container_width=True, hide_index=True)
        st.caption('Unrated or invalid CSAT values are excluded from averages. Open tickets do not '
                   'enter the resolution-hours denominator.')

    with refund_tab:
        st.markdown('#### Historical refund exception audit')
        c1, c2, c3 = st.columns(3)
        c1.metric('Unique flagged tickets', f'{stats["violating_tickets"]:,}')
        c2.metric('Estimated policy leakage', money(stats['estimated_leak_inr']))
        c3.metric('Cap checks missing amount', f'{stats["uncertain_cap_tickets"]:,}')
        joined, by_rule = historical_leakage(attach_order_facts(fo, ft))
        st.markdown('##### Tickets flagged by SOP rule')
        chart_table(by_rule, 'rule', 'flagged_tickets')
        st.dataframe(by_rule, hide_index=True, use_container_width=True)
        st.warning('Figures describe historical recorded refund fields, NOT confirmed settlements or recoverable cash. '
                   'One ticket may trigger multiple rules. The unique leak estimate uses the largest estimated '
                   'excess per ticket rather than summing overlapping rule estimates.')
        st.caption('Audit replicates the original Part 1 core leakage categories: R1 delayed full refunds, '
                   'R2 replacement plus refund, R3 cancelled unpaid COD cash refund, and R4 cap exceedance. '
                   'The stricter Phase 2A policy engine may additionally flag anomalous records for manual review.')
        st.download_button('Download aggregated violation summary (CSV)',
                           by_rule.to_csv(index=False).encode('utf-8'),
                           file_name='quickcart_violation_summary.csv', mime='text/csv')

    with sqlite_tab:
        st.markdown('#### Local SQLite administrative requests (live counts)')
        st.caption('New local support requests, not original historical CSV support tickets. '
                   'Historical filters above do not apply. Approved follow-up is NOT a refund approval.')
        if st.button('Refresh local SQLite metrics', key='dash_refresh'):
            st.rerun()
        if live is None:
            st.info('SQLite statistics unavailable.')
        else:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric('All local requests', f'{live["total"]:,}')
            c2.metric('Active / not closed', f'{live["active"]:,}')
            c3.metric('Need historical reconciliation', f'{live["needs_reconciliation"]:,}')
            c4.metric('Submitted in last 7 days', f'{live["submitted_last_7_days"]:,}')
            a, b = st.columns(2)
            with a:
                st.markdown('##### Requests by current status')
                chart_table(live['by_status'], 'status', 'requests')
            with b:
                st.markdown('##### Requests created by UTC date')
                if live['daily'].empty:
                    st.info('No locally submitted requests yet. Use Customer help to create one.')
                else:
                    chart_table(live['daily'], 'created_day', 'requests', chart='line')
            st.metric('Logged status events', f'{live["audit_events"]:,}')
            st.dataframe(live['by_status'], hide_index=True, use_container_width=True)
            st.caption('Only aggregate counts are displayed; stored customer questions and review notes '
                       'are not presented or exported from this dashboard.')
