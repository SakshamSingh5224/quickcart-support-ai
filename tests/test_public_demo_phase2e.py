"""Ensure public export is fully synthetic and resists accidental data inclusion."""
import csv
import pytest
from scripts.build_public_demo import build
from scripts.check_demo_safety import check


def test_export_contains_only_synthetic_data(tmp_path):
    dest=tmp_path/'demo'
    build(dest)
    assert check(dest)
    assert (dest/'app.py').exists()
    assert (dest/'.github/workflows/ci.yml').exists()
    assert (dest/'tests/test_security_phase2e.py').exists()
    assert not (dest/'part1').exists()
    with (dest/'data/orders_clean.csv').open() as file:
        orders=list(csv.DictReader(file))
    with (dest/'data/support_tickets_clean.csv').open() as file:
        tickets=list(csv.DictReader(file))
    assert len(orders)==36
    assert len(tickets)==28
    assert next(o for o in orders if o['order_id']=='ORD-810002')['customer_id']=='CUST-DEMO-002'
    with pytest.raises(ValueError):
        build(dest)
    orders[0]['order_id']='ORD-700002'
    with (dest/'data/orders_clean.csv').open('w',newline='') as file:
        w=csv.DictWriter(file,fieldnames=orders[0].keys());w.writeheader();w.writerows(orders)
    with pytest.raises(ValueError):
        check(dest)
