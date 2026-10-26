"""QuickCart Part 1: cleaning + analysis. Run: python3 part1_clean_and_analyze.py"""
import pandas as pd, numpy as np, re, json, os
U='/mnt/user-data/uploads/'; OUT='/mnt/user-data/outputs/'
os.makedirs(OUT,exist_ok=True)
o=pd.read_csv(U+'orders.csv',dtype=str,keep_default_na=False)
t=pd.read_csv(U+'support_tickets.csv',dtype=str,keep_default_na=False)
log=[]
def L(file,issue,fix,n): log.append(dict(file=file,issue=issue,fix=fix,rows_affected=int(n)))

# ---------- helpers ----------
FMTS=['%Y-%m-%d %H:%M:%S','%Y/%m/%d %H:%M:%S','%d-%b-%Y %I:%M %p','%d-%b-%y %H:%M','%d-%b-%Y %H:%M',
      '%b %d, %Y %H:%M','%B %d, %Y %I:%M %p','%B %d, %Y %H:%M','%b %d, %Y %I:%M %p',
      '%d/%m/%Y %H:%M','%d-%m-%Y %H:%M','%d.%m.%Y %H:%M']   # numeric dates are DAY-first (verified via duplicate pairs)
def pdate(s):
    s=s.strip()
    if not s: return pd.NaT
    for f in FMTS:
        try: return pd.to_datetime(s,format=f)
        except Exception: pass
    return pd.NaT
def money(s):
    s=str(s).strip()
    if s=='' or s.upper() in('NIL','NA','N/A','NULL','NONE'): return np.nan
    s=re.sub(r'(?i)(₹|rs\.?|inr|,|\s)','',s)
    return float(s)
def norm_oid(s):
    d=re.sub(r'\D','',s); return 'ORD-'+d if d else np.nan

# ---------- ORDERS ----------
n0=len(o)
L('orders','Order dates in 6+ different formats (ISO, dd-Mon-yy, "January 23, 2026 11:41 AM", dd.mm.yyyy, ...)','Parsed all to a single datetime (numeric dates treated as day-first, confirmed by duplicate pairs)',n0)
o['order_date']=o.order_date.map(pdate)
ws=sum((o[c]!=o[c].str.strip()).sum() for c in ['customer_city','product_category','courier_partner'])
for c in ['customer_city','product_category','courier_partner']:
    o[c]=o[c].str.strip()
L('orders','Leading/trailing whitespace in city, category, courier (cell count)','strip()',ws)
cm={'bangalore':'Bengaluru','bengaluru':'Bengaluru','new delhi':'Delhi NCR','delhi ncr':'Delhi NCR','mumbai':'Mumbai','hyderabad':'Hyderabad','pune':'Pune','chennai':'Chennai'}
raw_city=o.customer_city.copy(); o['customer_city']=o.customer_city.str.lower().map(cm)
L('orders','City spelling/case variants (Bangalore/Bengaluru, mumbai , New Delhi/Delhi NCR)','Mapped to 6 canonical cities (New Delhi merged into Delhi NCR)',(raw_city!=o.customer_city).sum())
catm={'electronics':'Electronics','fashion & apparel':'Fashion & Apparel','fashion_apparel':'Fashion & Apparel','home & kitchen':'Home & Kitchen','home_kitchen':'Home & Kitchen','beauty & groceries':'Beauty & Groceries','beauty_groceries':'Beauty & Groceries'}
raw=o.product_category.copy(); o['product_category']=o.product_category.str.lower().map(catm)
L('orders','product_category inconsistent case/underscore/spacing (12 variants)','Mapped to 4 canonical categories',(raw!=o.product_category).sum())
couriers={'shadowfax_local':'Shadowfax_Local','delhivery_express':'Delhivery_Express','bluedart_air':'BlueDart_Air','ecomexpress_surface':'EcomExpress_Surface'}
raw=o.courier_partner.copy(); o['courier_partner']=o.courier_partner.str.lower().map(couriers)
L('orders','courier_partner lowercase / trailing spaces (8 variants)','Mapped to 4 canonical couriers',(raw!=o.courier_partner).sum())
amt_raw=o.order_amount.copy()
o['order_amount']=o.order_amount.map(money)
L('orders','order_amount stored as text with "₹", "INR", commas, ".00"','Stripped symbols and converted to float',(~amt_raw.str.fullmatch(r'\d+\.0')).sum())
o['shipping_fee']=o.shipping_fee.map(money)
bad_amt=(o.order_amount<=0)
L('orders','Invalid sentinel order_amount (-999)','Set to NaN (not a real price); a duplicate row with a valid amount is used if one exists, otherwise the order stays in counts but is excluded from GMV',bad_amt.sum())
o.loc[bad_amt,'order_amount']=np.nan
# dedupe: same order_id appears multiple times (identical except date format)
dups=o.order_id.duplicated(keep=False).sum()
o=o.sort_values(['order_id','order_amount'],na_position='last')
# fill NaN amount from sibling rows, then drop dups
o['order_amount']=o.groupby('order_id').order_amount.transform(lambda s:s.fillna(s.max()))
conf=o.drop_duplicates().groupby('order_id').size().gt(1).sum()
o=o.drop_duplicates('order_id',keep='first').reset_index(drop=True)
L('orders','Duplicate order rows (same order_id repeated, often with date in a different format)','Dropped duplicates after standardising formats; kept one row per order_id',n0-len(o))
still_bad=o.order_amount.isna().sum()

# ---------- TICKETS ----------
m0=len(t)
raw=t.order_id.copy(); t['order_id']=t.order_id.map(norm_oid)
L('tickets','order_id in inconsistent formats ("701922", " ord_700007 ", trailing spaces)','Extracted digits and rebuilt as ORD-xxxxxx',(raw!=t.order_id).sum())
t['ticket_created_at']=t.ticket_created_at.map(pdate); t['ticket_resolved_at']=t.ticket_resolved_at.map(pdate)
L('tickets','Created/resolved timestamps in 6+ formats','Parsed to standard datetime',m0)
t['refund_amount_raw']=t.refund_amount
t['refund_amount']=t.refund_amount.map(money)
L('tickets','refund_amount as text ("Rs. 1099", "₹1,099.00", "NIL", blank)','Stripped currency text; NIL/blank -> 0',(t.refund_amount_raw.str.fullmatch(r'\d+(\.\d+)?')==False).sum())
t['refund_amount']=t.refund_amount.fillna(0.0)
t['csat_score_raw']=t.csat_score
t['csat_score']=pd.to_numeric(t.csat_score,errors='coerce')
inv=t.csat_score.notna()&~t.csat_score.between(1,5)
L('tickets','Invalid CSAT sentinels (99, -1)','Set to NaN (excluded from average)',inv.sum())
t.loc[inv,'csat_score']=np.nan
L('tickets','Blank CSAT (customer did not rate; includes all open tickets)','Left as NaN, not treated as 0',(t.csat_score_raw=='').sum())
t=t.sort_values('ticket_id')
before=len(t); t=t.drop_duplicates('ticket_id',keep='first').reset_index(drop=True)
L('tickets','Duplicate ticket rows (same ticket_id, timestamps in different formats)','Dropped duplicates; kept one row per ticket_id',before-len(t))
neg=(t.ticket_resolved_at<t.ticket_created_at)
t.loc[neg,['ticket_created_at','ticket_resolved_at']]=t.loc[neg,['ticket_resolved_at','ticket_created_at']].values
L('tickets','Resolved timestamp earlier than created timestamp','Assumed swapped entry; swapped the two timestamps',neg.sum())
t['resolution_hours']=(t.ticket_resolved_at-t.ticket_created_at).dt.total_seconds()/3600
t['is_open']=t.resolution_status.str.startswith('Open')
orph=~t.order_id.isin(o.order_id)
L('tickets','Orphan tickets (order_id not in orders.csv) AFTER ID normalisation','None found - every ticket maps to an order once IDs are standardised (444 looked orphaned before the fix)',orph.sum())

# ---------- save cleaned ----------
oc=o.copy(); oc['order_date']=oc.order_date.dt.strftime('%Y-%m-%d %H:%M:%S')
tc=t.drop(columns=['refund_amount_raw','csat_score_raw']).copy()
for c in ['ticket_created_at','ticket_resolved_at']: tc[c]=tc[c].dt.strftime('%Y-%m-%d %H:%M:%S')
oc.to_csv(OUT+'orders_clean.csv',index=False); tc.to_csv(OUT+'support_tickets_clean.csv',index=False)
pd.DataFrame(log).to_csv(OUT+'data_cleaning_log.csv',index=False)

# ---------- A. Overall ----------
R={}
R['unique_orders']=int(o.order_id.nunique()); R['unique_tickets']=int(t.ticket_id.nunique())
R['orders_with_invalid_amount_after_dedupe']=int(still_bad)
R['GMV_all_orders']=float(o.order_amount.sum())
R['GMV_excl_cancelled']=float(o.loc[o.delivery_status!='CANCELLED_BEFORE_SHIP','order_amount'].sum())
R['GMV_delivered_only']=float(o.loc[o.delivery_status=='DELIVERED','order_amount'].sum())
R['shipping_fees_total']=float(o.shipping_fee.sum())
R['total_refunds_cash']=float(t.refund_amount.sum())
R['refund_pct_of_GMV']=R['total_refunds_cash']/R['GMV_all_orders']*100
R['tickets_by_status']=t.resolution_status.value_counts().to_dict()
R['delivery_status_counts']=o.delivery_status.value_counts().to_dict()

# ---------- B. Courier ----------
o['bad_delivery']=o.delivery_status.isin(['LOST_IN_TRANSIT','DELAYED_IN_TRANSIT'])
shipped=o[o.delivery_status!='CANCELLED_BEFORE_SHIP']
cour=pd.DataFrame({
 'orders':o.groupby('courier_partner').size(),
 'lost_delayed':o.groupby('courier_partner').bad_delivery.sum(),
 'lost_delayed_rate_pct_all':o.groupby('courier_partner').bad_delivery.mean()*100,
 'lost_delayed_rate_pct_shipped':shipped.groupby('courier_partner').bad_delivery.mean()*100,
 'lost_pct':o.groupby('courier_partner').delivery_status.apply(lambda s:(s=='LOST_IN_TRANSIT').mean()*100),
 'delayed_pct':o.groupby('courier_partner').delivery_status.apply(lambda s:(s=='DELAYED_IN_TRANSIT').mean()*100)})
tj=t.merge(o[['order_id','courier_partner','delivery_status','order_amount','payment_method','product_category']],on='order_id',how='left')
res=tj[(~tj.is_open)&tj.resolution_hours.notna()]
cour['avg_resolution_hrs']=res.groupby('courier_partner').resolution_hours.mean()
cour['median_resolution_hrs']=res.groupby('courier_partner').resolution_hours.median()
cour['tickets']=tj.groupby('courier_partner').size()
cour['open_tickets']=tj.groupby('courier_partner').is_open.sum()
cour['avg_csat']=tj.groupby('courier_partner').csat_score.mean()
cour=cour.round(2); cour.to_csv(OUT+'courier_summary.csv')
R['courier_table']=cour.reset_index().to_dict('records')

# ---------- C. SLA / CSAT ----------
R['avg_resolution_hrs_resolved']=float(t.loc[~t.is_open,'resolution_hours'].mean())
R['median_resolution_hrs_resolved']=float(t.loc[~t.is_open,'resolution_hours'].median())
R['open_tickets']=int(t.is_open.sum())
R['pct_resolved_over_24h']=float((t.loc[~t.is_open,'resolution_hours']>24).mean()*100)
R['avg_csat_valid']=float(t.csat_score.mean()); R['csat_n']=int(t.csat_score.notna().sum())
R['csat_by_channel']=t.groupby('channel').csat_score.mean().round(2).to_dict()
R['res_hrs_by_channel']=t[~t.is_open].groupby('channel').resolution_hours.mean().round(2).to_dict()
R['res_hrs_by_issue']=t[~t.is_open].groupby('issue_category').resolution_hours.mean().round(2).to_dict()
R['csat_by_late']=t[~t.is_open].assign(late=lambda d:d.resolution_hours>24).groupby('late').csat_score.mean().round(2).to_dict()

# ---------- D. Refund leak (policy violations) ----------
j=tj[tj.order_id.isin(o.order_id)].copy()   # only tickets with a matching order can be policy-checked
oa=j.order_amount; ra=j.refund_amount; st=j.delivery_status; iss=j.issue_category; rs=j.resolution_status
v={}
# Rule 2: replacement AND cash refund (replacement status but refund>0)
v['R2_replacement_plus_cash']=(rs=='Resolved - Replacement Sent')&(ra>0)
# Rule 2b: Damaged ticket where refund != 0 and != full order amount (partial/odd) - informational
v['R2b_damaged_refund_not_0_or_full']=(iss=='Damaged / Defective Item Received')&(ra>0)&(ra.sub(oa).abs()>0.01)&(rs!='Resolved - Replacement Sent')
# Rule 3: COD cancelled before ship must be 0
v['R3_COD_cancelled_refund']=(j.payment_method=='Cash on Delivery (COD)')&(st=='CANCELLED_BEFORE_SHIP')&(ra>0)
# Rule 4: refund > order_amount + 100
v['R4_exceeds_cap']=ra>oa+100+0.01
# Rule 1: DELAYED_IN_TRANSIT must not get full refund (only 100 voucher)
v['R1_delayed_full_refund']=(st=='DELAYED_IN_TRANSIT')&(rs=='Resolved - Full Refund Issued')&(ra>100)
R2b=v.pop('R2b_damaged_refund_not_0_or_full')
V=pd.DataFrame(v)
# Excess (leak) amounts per rule
leak=pd.DataFrame(0.0,index=j.index,columns=V.columns)
leak['R2_replacement_plus_cash']=np.where(V['R2_replacement_plus_cash'],ra,0)
leak['R3_COD_cancelled_refund']=np.where(V['R3_COD_cancelled_refund'],ra,0)
leak['R4_exceeds_cap']=np.where(V['R4_exceeds_cap'],ra-(oa+100),0)
leak['R1_delayed_full_refund']=np.where(V['R1_delayed_full_refund'],ra-100,0)
j['violations']=V.apply(lambda r:','.join(k for k in V.columns if r[k]),axis=1)
j['any_violation']=V.any(axis=1)
# Money lost: per ticket, the largest single-rule excess (rules do not overlap in this data)
j['money_lost']=leak.max(axis=1)
summ=pd.DataFrame({'tickets':V.sum(),'money_lost_inr':leak.sum().round(2)})
R['violation_summary']=summ.reset_index().rename(columns={'index':'rule'}).to_dict('records')
R['note_R2b_damaged_nonstandard_refund_all_also_R4']=int((R2b&V['R4_exceeds_cap']).sum())
R['violating_tickets_unique']=int(j.any_violation.sum()); R['money_lost_unique']=float(j.money_lost.sum())
R['tickets_checked']=int(len(j))
j[j.any_violation].drop(columns=['customer_message'],errors='ignore').to_csv(OUT+'policy_violations.csv',index=False)
summ.to_csv(OUT+'violation_summary.csv')

# extra: Rule 1 late-voucher check & lost/returned underpayment (informational)
lr=j[st.isin(['LOST_IN_TRANSIT','RETURNED_TO_SELLER'])&(j.issue_category=='Item Not Delivered / Delayed')]
R['extra_lost_returned_tickets_not_refunded']=int(((lr.refund_amount<lr.order_amount-0.01)&~lr.is_open).sum())
R['extra_open_tickets_by_courier']=cour['open_tickets'].to_dict()
json.dump(R,open(OUT+'part1_results.json','w'),indent=2,default=str)
pd.DataFrame(log).to_string(open(OUT+'cleaning_log.txt','w'))
print(json.dumps(R,indent=2,default=str)); print(pd.DataFrame(log).to_string())
