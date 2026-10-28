# Method and judgment calls

This kit has one rule: every target comes from the brand's own numbers. This page covers what that means in practice, every choice behind it and what it doesn't handle yet.

## Targets

For period *i*, with *L* periods in a year:

```
anchor  = the same period last year (i − L); for weeks, the average of weeks i−53, i−52 and i−51
growth  = sum of the last T periods ÷ sum of the same T periods a year earlier
target  = anchor × min(1.5, max(0.67, growth))
```

| Grain | L | Anchor | Growth window T | Band window |
|---|---|---|---|---|
| Week | 52 | same week ±1 | 13 weeks | 13 |
| Month | 12 | same month | 3 months | 6 |
| Quarter | 4 | same quarter | 2 quarters | 4 |

- **Seasonal by construction.** Using last year's period carries the season. December is compared with last December scaled by current growth, not with November.
- **Growth from 13 weeks, not 4.** A 4-week window jumps around with a single promotion. 13 weeks is long enough to be stable and short enough to notice a real change in trajectory.
- **Three-week anchor for weeks.** One odd week last year (a stock-out, a site outage) shouldn't set this year's bar. The cost is that event weeks such as Black Friday get a diluted anchor; see *Limits*.
- **Growth is capped between −33% and +50%.** A channel's launch year, or a tiny base, can otherwise produce an absurd growth factor. The cap is a cell on the Settings tab.
- **Ratios of sums.** Conversion rate over 13 weeks is total orders ÷ total sessions, not the average of 13 weekly rates, so a big week counts more than a small one.
- **No target on a half-empty year.** A target appears only once every window it needs has data. With three years of exports, weekly targets start in February 2025.
- **What a target means.** It asks whether this period is in line with the brand's own trajectory for the season. It doesn't encode an ambition. An agreed goal, such as an MER floor, belongs in a separate column so it never gets mistaken for the data-driven target.

## Normal swing and status

The band is the interquartile range of the KPI's own misses (actual ÷ target − 1) over the previous 13 weeks (6 months, 4 quarters), kept between 2% and 40%. Half of it is the KPI's normal swing, which the report shows next to every status.

| Status | Miss |
|---|---|
| On track | within the normal swing |
| Watch | up to twice the normal swing |
| Off track | more than twice the normal swing |

- **Each KPI gets its own swing.** This store's weekly revenue usually swings about ±5–6% around target, while conversion rate swings about ±2%. Over the last 52 weeks, a flat 5% rule would flag revenue 17 times, against 5 Off track weeks from its own swing. It would catch only 7 conversion misses to the swing's 9.
- **Interquartile range, not standard deviation.** One Black Friday miss in the window would blow a standard deviation wide open. The interquartile range shrugs it off.
- **Lower-is-better KPIs flip the sign.** CAC and refund rate flip, so a negative miss always means worse.
- **Ad spend is paced, not judged.** It shows Above plan or Below plan against its trajectory; spending more isn't good or bad by itself.
- **New KPIs use a default.** A KPI without a full window of past misses uses a 10% band, a ±5% normal swing.

## Data choices

- **Refunds count on the day they're issued**, as in Shopify's own sales reports. Booking them back to the order date would match spend and revenue more tightly, but recent weeks would keep changing as refunds arrive. A weekly report needs weeks that are final when they close.
- **Totals use Shopify, not the ad platforms.** MER (net revenue ÷ ad spend) and new-customer CAC (ad spend ÷ new customers) drive the targets and actions. Meta, Google and TikTok each claim credit for overlapping orders, so platform ROAS is shown only to split budget between channels.
- **Conversion rate is Shopify orders ÷ GA4 sessions.** GA4 loses purchases to consent banners. GA4 transactions are used only to compare devices with each other.
- **Customer metrics start 26 weeks in.** "New" means a customer's first order in the exports. Someone who first bought before the exports began would look new, so new customers, CAC, returning share and repeat rate start on 29 April 2024.
- **The 90-day repeat rate looks back one cohort.** Weekly figures use customers who first bought 13 weeks earlier (monthly 3 months, quarterly 1 quarter), so every customer counted has had about 90 days to come back.
- **COGS is net of restocked returns.** Items that aren't restocked keep their cost.
- **A SKU missing from the cost sheet is costed at 40% of its net price.** The Data checks tab flags it.

## Actions

Each report section ends with up to three actions. Every action is a rule with the numbers written in:

| Section | Rule |
|---|---|
| Revenue | If revenue misses, split it into orders and order value. If refunds are high, name the SKU refunded most above the range's own rate. If order value is up, name the SKU whose share of sales grew most against last year. |
| Site & conversion | If conversion misses, compare devices against the last 13 weeks. Devices with fewer than 50 transactions are ignored as noise. If one device fell and the others held, find the week it started. |
| Acquisition | If CAC or MER misses, find the channel with a sizable share of spend whose platform ROAS fell most. Move 15% of its spend to the best remaining prospecting channel; brand search and retargeting are excluded because they harvest demand that already exists. Add a creative refresh if its CPMs rose more than 10%. |
| Retention | If returning share is up only because new customers fell, say so. If the repeat rate slips, size the win-back audience: customers whose last order was 90 to 180 days ago. |
| Profit | If contribution margin misses, name the cost line that grew most as a share of net revenue. |

Breakdowns are compared with the same period last year where seasonality matters (product mix, traffic sources). They're compared with the trailing window where it doesn't (device conversion, channel efficiency, cost shares).

## Limits

- **Event weeks.** Black Friday week is judged against an anchor diluted by its neighbours, and the event drifts between ISO weeks 47 and 48 across years. The fix is an event calendar that anchors event weeks to the same event last year.
- **Ad accounts.** Each platform comes from one ad account in one currency. Multiple stores or currencies need an extra key on every table.
- **Sizes of change.** The action rules recommend direction and a starting amount, such as 15% of a channel's spend. They don't model diminishing returns.
- **Synthetic data.** The synthetic exports reproduce the structure of real exports, not every column. Real exports will need their column names mapped in `clean.py`.
