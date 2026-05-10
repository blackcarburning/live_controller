# UEA Diamondback batch commercial summary

## Overall status
There is **no final TD SYNNEX quote or pricing spreadsheet** in this bundle. The best available pricing basis is the set of **IBM configurator exports dated 22 Apr 2026** (TXT files, cross-checked against the matching XML files), which were emailed by **TD SYNNEX** on **23 Apr 2026** **for review prior to quoting**.

## Source-of-truth pricing basis
- **Supplier / channel:** TD SYNNEX
- **Pricing artefact actually present:** IBM ECMSSD configurator outputs
- **Most reliable pricing files in the bundle:**
  - `44422669Russ 220426 CSI-UEA Diamondback 8xLTO10-FC 3yr.txt`
  - `44422669Russ 220426 CSI-UEA 2x300 LTO-10 30TB NO-VOLSER.txt`
  - `44422669Russ 220426 CSI-UEA 2x 2xSAN24B-7 3yrECA.txt`
- Matching XML files support the same pricing/shipping figures.

## Commercial summary (best available from bundle)
- **One-time list-price subtotal (excl. shipping, excl. VAT):** **GBP 3,937,792.40**
- **Non-discountable shipping & handling:** **GBP 10,073.96**
- **One-time total before VAT (incl. shipping):** **GBP 3,947,866.36**
- **Recurring monthly maintenance:** **GBP 2,900.54**
- **VAT:** Not stated anywhere in the bundle, so no VAT-inclusive grand total can be confirmed.

## Date / revision
- IBM configurator files generated on **22 Apr 2026** at:
  - 15:32:08 (`Diamondback 8xLTO10-FC 3yr`)
  - 15:34:23 (`2x300 LTO-10 30TB NO-VOLSER`)
  - 15:40:17 (`2x 2xSAN24B-7 3yrECA`)
- TD SYNNEX covering email sent **23 Apr 2026 09:00**.

## Lead time
- **No committed lead time is stated.**
- The only timing field evidenced in the bundle is **Customer Requested Arrival Date: 2026/05/06**.

## What appears to be included
- **2 x Diamondback Tape Library 3yr** configurations.
- **Recurring maintenance on the Diamondback libraries:** GBP 1,450.27 per month each, GBP 2,900.54 per month total.
- **2 x media bundles**, each showing **15 x 20-pack LTO-10 cartridges** (= **300 cartridges per bundle**, **600 total**).
- **4 x SAN24B-7 switch configurations appear intended**, based on:
  - the customer request for 4 switches,
  - the filename `2x 2xSAN24B-7`, and
  - the overall switch total of GBP 257,082.32, which equals **4 x GBP 64,270.58**.
- **40 x 10m OM3 LC/LC cables total appear intended**, based on 10 cables shown per visible switch system and the original request for 40 cables.
- Switch support includes **3 year IBM Storage Expert Care Advanced** and **Support Line for Storage - 3 Year (N/C)**.
- Library config includes **4883-L9A SP Warranty and Maintenance 3Y 24x7 Same Day ORT**.

## Explicit exclusions / missing commercial items
- No final **TD SYNNEX quote**, discount schedule, or deal-registration-backed sell price.
- No VAT line.
- No committed lead time.
- No installation / implementation statement beyond the IBM service/warranty lines shown.
- Diamondback config explicitly shows **"No Host/SAN Cable from Plant"**.
- No spreadsheet found in batch.

## Assumptions used for this summary
- This summary covers the **whole UEA Diamondback batch** in the supplied bundle, not a single attachment in isolation.
- Totals are treated as **IBM list/configurator pricing**, not reseller discounted quote pricing.
- Switch quantity of **4** is inferred from the overall total plus the request/email because the extracted TXT detail cuts off after `System 2`.
- Shipping is treated separately, then added to the one-time subtotal to produce the best available **pre-VAT** total.

## Risks, discrepancies, and points needing confirmation
1. **Diamondback drive count discrepancy:**
   - Email request: **8 x LTO10 drives** per library.
   - Filename: `Diamondback 8xLTO10-FC 3yr`.
   - Visible config line: **`AGH4 LTO10 FH Fibre Channel Drive Qty 10`** per system.
   - This needs confirmation before quoting.

2. **Media VOLSER discrepancy / missing location-specific start values:**
   - Email note says **"LTO-10 media requires starting VOLSER for each location"**.
   - Media filename says **`NO-VOLSER`**.
   - Visible media features actually encode a starting sequence of **D/U/M/0/0/0** (`DUM000`) and both visible bundles show the **same starting sequence**.
   - This should be confirmed to avoid duplicate or wrong labels across locations.

3. **Switch configuration may not cleanly evidence the requested 14-port population:**
   - Request asks for **14 ports licensed and populated with 12 x SW SFPs and 2 x LW SFPs**.
   - Visible config shows **1 x 8-port SW SFP bundle**, **1 x 8-port SW upgrade**, and **2 x LW SFPs**.
   - Presales note says **"8-port base bundle + first 8-port uplift bundle"**.
   - The exact licensed/populated port outcome should be confirmed in the final quote.

4. **Bundle is pre-quote, not final commercial paper:**
   - TD SYNNEX email says the configs are **for review by BP prior to quoting**.
   - Best discounts are explicitly still pending deal registration approval/reference.

5. **Custom services warning on Diamondback:**
   - The Diamondback config says **ServicePacs option has been selected and cannot be combined with any additional Services Offerings** and **Custom ServicePacs require scoping assistance**.
   - Any added services could require re-scoping.

## Source files used
- `UEA_tdsyn.txt`
- `44422669Russ 220426 CSI-UEA Diamondback 8xLTO10-FC 3yr.txt`
- `44422669Russ 220426 CSI-UEA Diamondback 8xLTO10-FC 3yr.xml`
- `44422669Russ 220426 CSI-UEA 2x300 LTO-10 30TB NO-VOLSER.txt`
- `44422669Russ 220426 CSI-UEA 2x300 LTO-10 30TB NO-VOLSER.xml`
- `44422669Russ 220426 CSI-UEA 2x 2xSAN24B-7 3yrECA.txt`
- `44422669Russ 220426 CSI-UEA 2x 2xSAN24B-7 3yrECA.xml`
