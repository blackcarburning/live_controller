# UEA Diamondback commercial summary

## Source-of-truth assessment
- The original workbook `230427CSI UEA deal reg Quotes.xlsx` could not be read because of invalid XML, so it is not a usable pricing source from the extracted bundle.
- The most likely source-of-truth pricing file is `44422669Russ 220426 CSI-UEA Diamondback 8xLTO10-FC 3yr.csv` because it is the only extracted file that explicitly names Diamondback and it contains a complete system total, shipping charge, and related warranty/service line.
- The SAN and media CSVs appear to be supporting quotes in the same UEA Diamondback batch and were used to infer an overall batch value.

## Pricing summary
- Revision/date: 22 Apr 2026 (CSV build times run from 15:32:08 to 15:40:17 BST).
- Vendor: IBM (inferred from IBM configurator output and IBM-branded product descriptions; no separate reseller/supplier name is visible in the extracted bundle).
- Main Diamondback system total: **GBP 1,538,471.04**.
- Main Diamondback shipping: **GBP 4,542.92**.
- Main Diamondback monthly maintenance: **GBP 1,450.27** (shown separately as a recurring charge, not included in the system total).
- Supporting SAN quote system total: **GBP 64,270.58**; shipping **GBP 232.12**.
- Supporting media quote system total: **GBP 603,768.00**; shipping **GBP 59.64**.
- Inferred batch subtotal (sum of the three CSV system totals, excluding shipping and VAT): **GBP 2,206,509.62**.
- Inferred batch amount before VAT including stated shipping: **GBP 2,211,344.30**.
- VAT: not shown in the source files.
- Lead time: not stated in the extracted bundle.

## Inclusions
- `4883-L9A` Diamondback Tape Library 3yr base system.
- `AGH4` LTO10 FH Fibre Channel Drive, qty 10.
- `1600` Full Capacity License.
- `1529` Preloaded Media enablement kit.
- `1414` Diagnostic Cartridge for LTO10 and `8750` LTO Cleaning Cartridge.
- `1853` 1x PDU in Frame, qty 2; `9956` IEC 309 Power Cord, qty 2; `9990` Dual 2.8m power cord PDU to PSU.
- `AGL2` LTO Service Magazine.
- `6661-D10` 4883-L9A SP Warranty and Maintenance 3Y 24x7 Same Day ORT.
- SAN quote items including `8969-P24` IBM Storage Networking SAN24B-7, 32G LWL SFPs, 8-port SFP bundle, 8-port upgrade, 10x OM3 LC/LC 10m cables, and 3-year IBM Storage Expert Care Advanced.
- Media quote items including labeled 30 TB LTO10 tape cartridges. Based on the duplicated 15x20-pack block and the doubled total, the file appears to cover two identical 300-cartridge lots in the batch.

## Exclusions / missing items
- VAT / taxes are not shown anywhere in the extracted source.
- Lead time / delivery schedule is not stated.
- Host/SAN cable from plant is explicitly excluded on the Diamondback quote (`9700 No Host/SAN Cable from Plant`).
- The extracted bundle does not provide a readable combined workbook summary, so there is no directly extracted batch cover sheet to confirm the rolled-up commercial total.

## Assumptions used
- Batch values were inferred by summing the three extracted CSV `System Total` figures because the original workbook could not be read.
- `System Total` was treated as excluding shipping and VAT because each CSV lists shipping separately and also states that taxes are not shown.
- The Diamondback monthly maintenance figure was treated as a separate recurring charge because it is listed separately from `System Total`.
- IBM was treated as the vendor because all available extracts are IBM configurator outputs and IBM-branded line items; no alternative supplier name is visible.

## Risks / discrepancies
- The original workbook is unreadable due to invalid XML, so the intended master summary cannot be verified directly.
- The media filename says `NO-VOLSER`, but the line items show labeled cartridges with explicit VOLSER characters (`D`, `U`, `M`, `0`, `0`, `0`) and a base-10 sequence. That mismatch should be checked before order placement.
- The SAN filename includes `2x 2xSAN24B-7`, but the extracted rows show one `8969-P24` base system. The intended SAN quantity/design should be confirmed.
- The Diamondback and media files both warn that ServicePacs cannot be combined with additional services, and the Diamondback file says custom ServicePacs require scoping assistance.
- The IBM configurator text says the prices are for proposal usage only, subject to change, and should not be committed without sales manual verification.

## Source files used
- `/root/.openclaw/dropbox/inbox/UEA/Diamondback/230427CSI UEA deal reg Quotes.xlsx` (attempted, but unreadable due to invalid XML)
- `/root/.openclaw/dropbox/inbox/UEA/Diamondback/44422669Russ 220426 CSI-UEA Diamondback 8xLTO10-FC 3yr/44422669Russ 220426 CSI-UEA Diamondback 8xLTO10-FC 3yr.csv`
- `/root/.openclaw/dropbox/inbox/UEA/Diamondback/44422669Russ 220426 CSI-UEA 2x300 LTO-10 30TB NO-VOLSER/44422669Russ 220426 CSI-UEA 2x300 LTO-10 30TB NO-VOLSER.csv`
- `/root/.openclaw/dropbox/inbox/UEA/Diamondback/44422669Russ 220426 CSI-UEA 2x 2xSAN24B-7 3yrECA/44422669Russ 220426 CSI-UEA 2x 2xSAN24B-7 3yrECA.csv`
