import pandas as pd, matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
O='/mnt/user-data/outputs/'
c=pd.read_csv(O+'courier_summary.csv').set_index('courier_partner')
v=pd.read_csv(O+'violation_summary.csv',index_col=0)
t=pd.read_csv(O+'support_tickets_clean.csv')
fig,ax=plt.subplots(2,2,figsize=(13,9))
c.lost_delayed_rate_pct_all.plot.bar(ax=ax[0,0],color='#d9534f'); ax[0,0].set_title('Lost/Delayed rate (% of orders)')
c.avg_resolution_hrs.plot.bar(ax=ax[0,1],color='#f0ad4e'); ax[0,1].set_title('Avg resolution time (hrs), resolved tickets')
t[~t.is_open].groupby('channel').resolution_hours.mean().plot.bar(ax=ax[1,0],color='#5bc0de'); ax[1,0].set_title('Avg resolution hrs by channel')
v[v.tickets>0].money_lost_inr.plot.bar(ax=ax[1,1],color='#6f42c1'); ax[1,1].set_title('Refund leakage by rule (₹)')
for a in ax.flat: a.tick_params(axis='x',rotation=25); a.set_xlabel('')
plt.tight_layout(); plt.savefig(O+'part1_charts.png',dpi=130)
