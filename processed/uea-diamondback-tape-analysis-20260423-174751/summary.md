# UEA Diamondback raw quote batch summary

## Summary
- **Project:** UEA Diamondback raw quote batch
- **Vendor / source ecosystem:** IBM configurator outputs supplied via TD SYNNEX email context
- **Primary pricing basis actually readable in this bundle:** the IBM configurator TXT/CSV/XML exports for the Diamondback library, SAN24B-7 switches, and LTO-10 media
- **Intended spreadsheet source present but unreadable:** `230427CSI UEA deal reg Quotes.xlsx` is included in the bundle, but the prepared input explicitly says it could not be read because of invalid XML
- **Currency:** GBP
- **Revision / date evidenced in the raw quote files:** 22 April 2026

## Best-evidenced commercial totals from the raw configurator outputs
The readable IBM configurator outputs show three separate components in this batch:

1. **Diamondback library config** (`44422669Russ 220426 CSI-UEA Diamondback 8xLTO10-FC 3yr`)
   - OTC / system total: **GBP 3,076,942.08**
   - Monthly maintenance: **GBP 2,900.54 / month**
   - Non-discountable shipping: **GBP 9,085.84**

2. **SAN switch config** (`44422669Russ 220426 CSI-UEA 2x 2xSAN24B-7 3yrECA`)
   - OTC / system total: **GBP 257,082.32**
   - Non-discountable shipping: **GBP 928.48**

3. **LTO-10 media config** (`44422669Russ 220426 CSI-UEA 2x300 LTO-10 30TB NO-VOLSER`)
   - OTC / system total: **GBP 603,768.00**
   - Non-discountable shipping: **GBP 59.64**

### Combined batch values from the readable configurator files
- **Subtotal / OTC before shipping:** **GBP 3,937,792.40**
- **Non-discountable shipping total:** **GBP 10,073.96**
- **Combined total including shipping:** **GBP 3,947,866.36**
- **VAT:** **not evidenced** in the readable raw quote files; the configurator outputs explicitly say applicable taxes are not shown

## Lead time / date
- The raw configurator files repeatedly show **Customer Requested Arrival Date: 2026/05/06**.
- That is a **requested arrival date**, not a clearly stated committed lead time.

## What the bundle clearly includes
- **2 x Diamondback tape library systems**
- **10 x LTO10 FH Fibre Channel drives per library** (**20 drives total** in the readable library config)
- **4 x SAN24B-7 switches total** (two systems, each containing two SAN24B-7 builds)
- **40 x OM3 LC/LC 10 m FC cables total** (10 per switch across 4 switches)
- **2 x 300 LTO-10 cartridges** in the media config, evidenced as two line groups of **15 x 20-packs**, for **600 cartridges total**
- **Custom VOLSER selections are evidenced** in the media config despite the filename containing `NO-VOLSER`
- **Library monthly maintenance / warranty content** is evidenced on the Diamondback configuration

## Exclusions / not evidenced clearly
- No readable final customer-facing spreadsheet pricing from the included `.xlsx`, because that workbook could not be parsed in the prepared bundle
- No VAT value
- No explicit final quoted customer discount / sell price in the readable IBM configurator outputs
- No explicit committed lead time beyond the requested arrival date
- The library config explicitly includes **`No Host/SAN Cable from Plant`**, so host/SAN cabling is not part of the library config itself

## Discrepancies and risks
- **Drive-count mismatch:** the request in the email says **8 x LTO10 drives per library**, but the readable Diamondback config shows **10 x AGH4 LTO10 drives per library**.
- **Filename mismatch on media:** the media filename says **`NO-VOLSER`**, but the readable media config clearly includes VOLSER character selections (`D`, `U`, `M`, `0`, `0`, `0`) and base-10 sequence labeling.
- **Switch-population/licensing wording is not fully explicit in the raw config files:** the bundle supports the presales note of **8-port base bundle + first 8-port uplift bundle** and includes **2 x LW SFPs per switch**, but the exact customer wording **14 ports licensed and populated with 12 x SW SFPs and 2 x LW SFPs** is not spelled out cleanly in one line of the readable config output.
- **Spreadsheet dependency remains unresolved:** the included deal-reg workbook may have contained customer-facing rollup or pricing logic, but in this prepared bundle it is unreadable, so this summary must rely on the raw IBM configurator outputs instead.
- **Configurator prices are informational / list-style outputs:** the readable files explicitly warn that informational totals do not necessarily reflect the prices actually paid by the customer.

## Best overall assessment
Using only the readable evidence in this prepared bundle, the raw quote batch does evidence a commercially coherent IBM/TD SYNNEX package for:
- 2 Diamondback libraries,
- 4 SAN24B-7 switches,
- 40 x 10m FC cables,
- and 600 LTO-10 cartridges.

But it is **not clean enough to treat as a final customer-ready quote without caveats**, because:
- the library drive count in the readable config is **10 per library**, not 8,
- the switch licensing / population wording is **credible but not fully explicit** against the customer request wording,
- the media filename is misleading about VOLSER,
- and the included spreadsheet source could not be read from the prepared bundle.
