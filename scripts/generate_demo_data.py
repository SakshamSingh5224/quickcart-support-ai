"""Generate 100% synthetic order/ticket CSVs for publishing a portfolio demo.

These identifiers and messages are fabricated and do not reuse the original dataset.
"""
from __future__ import annotations
import argparse
import csv
from pathlib import Path

ORDER_FIELDS = ['order_id','customer_id','customer_city','order_date','product_category',
                'courier_partner','order_amount','shipping_fee','payment_method','delivery_status']
TICKET_FIELDS = ['ticket_id','order_id','customer_id','ticket_created_at','ticket_resolved_at',
                 'issue_category','channel','resolution_status','refund_amount','csat_score',
                 'customer_message','resolution_hours','is_open']


def write_csv(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def generate(destination):
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    orders = []
    tickets = []
    states = ('LOST_IN_TRANSIT', 'DELIVERED', 'DELAYED_IN_TRANSIT', 'RETURNED_TO_SELLER',
              'CANCELLED_BEFORE_SHIP', 'DELIVERED')
    couriers = ('BlueDart_Air', 'Delhivery_Express', 'Shadowfax_Local', 'EcomExpress_Surface')
    for ix in range(1, 37):
        oid = f'ORD-{810000+ix}'
        cid = f'CUST-DEMO-{(ix-1)%3+1:03d}'
        state = states[(ix-1)%6]
        price = 499 + (ix % 9) * 150
        if ix == 2:
            price = 799
        orders.append(dict(
            order_id=oid, customer_id=cid,
            customer_city=('Bengaluru','Mumbai','Delhi NCR')[ix%3],
            order_date=f'2026-03-{(ix%27)+1:02d} 12:00:00',
            product_category=('Electronics','Fashion & Apparel','Home & Kitchen')[ix%3],
            courier_partner=couriers[ix%4], order_amount=f'{price}.0', shipping_fee='49.0',
            payment_method='Cash on Delivery (COD)' if state == 'CANCELLED_BEFORE_SHIP' else 'UPI',
            delivery_status=state))
        if ix <= 28:
            issue = 'Damaged / Defective Item Received' if ix == 2 else 'Item Not Delivered / Delayed'
            resolution = 'Resolved - Replacement Sent' if ix == 2 else ('Open - Awaiting Update' if ix%7==0 else 'Resolved - Agent Replied')
            refund = f'{price}.0' if ix == 2 else '0.0'
            opened = f'2026-04-{(ix%27)+1:02d} 12:00:00'
            is_open = ix % 7 == 0
            tickets.append(dict(
                ticket_id=f'TKT-{910000+ix}', order_id=oid, customer_id=cid,
                ticket_created_at=opened,
                ticket_resolved_at='' if is_open else f'2026-04-{(ix%27)+1:02d} 17:00:00',
                issue_category=issue, channel='In-App Chat', resolution_status=resolution,
                refund_amount=refund, csat_score='' if is_open else str((ix%5)+1),
                customer_message='Synthetic demonstration message about my sample order.',
                resolution_hours='' if is_open else '5.0', is_open=str(is_open)))
    write_csv(root / 'orders_clean.csv', ORDER_FIELDS, orders)
    write_csv(root / 'support_tickets_clean.csv', TICKET_FIELDS, tickets)
    return len(orders), len(tickets)


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--output', default='demo_data')
    args=p.parse_args()
    print('Synthetic orders, tickets:', generate(args.output))
