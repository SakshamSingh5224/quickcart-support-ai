# QuickCart – Part 1: Data Cleaning Log & Key Numbers

## Data Cleaning Log
**orders.csv (6,500 rows → 6,245 unique orders)**
- Dates in 6+ formats → parsed to one datetime (numeric dates are day-first; confirmed because duplicate pairs only match that way).
- City / category / courier: case, whitespace, underscore variants → 6 cities, 4 categories, 4 couriers (Bangalore=Bengaluru, New Delhi=Delhi NCR).
- order_amount text ("₹1,199.00", "INR 1199") → numeric; sentinel `-999` (45 orders) → blank, excluded from GMV.
- 255 duplicate order rows (same order, different date format) → deduplicated on order_id.

**support_tickets.csv (5,550 rows → 5,200 unique tickets)**
- Ticket order_id messy ("701922", " ord_700007 ", trailing spaces) → standardised to `ORD-xxxxxx`; 444 apparent orphans then all matched.
- Timestamps in 6+ formats → parsed; 38 tickets had resolved < created → swapped.
- refund_amount text ("Rs. 1099", "₹1,099.00", "NIL", blank) → numeric, NIL/blank = 0.
- CSAT: 99 and -1 are invalid → blank (31); blank CSAT (2,342, incl. all open tickets) kept blank, not 0.
- 350 duplicate ticket rows → deduplicated on ticket_id.

## Answers
**A. Overall:** 6,245 unique orders; 5,200 unique tickets; GMV ₹2,28,63,850 (₹2.29 Cr; ₹2.04 Cr excl. cancelled; 45 orders lack a valid amount); total refunds issued ₹1,00,09,538 (~43.8% of GMV).

**B. Courier:** Shadowfax_Local is worst on both: Lost/Delayed rate 30.7% (others ~18%) and slowest resolution 32.4 hrs (others ~19 hrs); also lowest CSAT (3.41).

**C. SLA & CSAT:** average resolution 24.5 hrs for resolved tickets (median 19.8; 40% take >24h); 582 tickets still open; true average CSAT 3.70 (2,957 valid ratings).

**D. Refund leak:** 145 tickets, ₹4,67,654 lost:
- Rule 2 (replacement + cash refund): 40 tickets, ₹1,32,510
- Rule 3 (COD cancelled-before-ship refunded): 55 tickets, ₹2,48,995
- Rule 4 (refund > order + ₹100): 50 tickets, ₹86,149 (excess over the cap)
- Rule 1 (delayed order fully refunded): 0 tickets

## Extra insights
- Email & Phone resolve ~38 hrs vs In-App Chat ~15 hrs; CSAT 3.0 / 3.1 vs 4.1.
- Late (>24h) tickets: CSAT 3.07 vs 4.14 on-time.
- Shadowfax carries 225 of the 582 open tickets.
