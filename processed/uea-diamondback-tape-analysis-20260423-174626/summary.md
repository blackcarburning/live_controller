# UEA Diamondback tape batch summary

## Summary
This batch appears to cover the University of East Anglia Diamondback tape solution request shared by TD SYNNEX on 23 Apr 2026. The readable pricing evidence is a set of three IBM ECMSSD configuration outputs dated 22 Apr 2026, not a final distributor quote.

## Most likely source of truth
There is **no single readable consolidated quote file** in the bundle. The workbook listed as the nominal quote source (`230427CSI UEA deal reg Quotes.xlsx`) is unreadable due to invalid XML. The strongest usable pricing evidence is therefore the **three IBM ECMSSD configuration summary files dated 22 Apr 2026**, cross-checked between their TXT/CSV/XML exports:

- `44422669Russ 220426 CSI-UEA Diamondback 8xLTO10-FC 3yr`
- `44422669Russ 220426 CSI-UEA 2x300 LTO-10 30TB NO-VOLSER`
- `44422669Russ 220426 CSI-UEA 2x 2xSAN24B-7 3yrECA`

## Commercial summary
| Field | Value |
|---|---|
| Project | UEA Diamondback tape solution batch |
| Customer | University of East Anglia |
| Supplier / vendor | IBM configuration outputs shared by TD SYNNEX; final discounted TD SYNNEX quote is not present in the bundle |
| Revision / date | 22 Apr 2026, ECMSSD version 31, price file date 2026-04-22 |
| Subtotal | **GBP 3,937,792.40 ex VAT** (sum of system totals, excluding shipping) |
| Non-discountable shipping | **GBP 10,073.96** |
| VAT | **Not shown in the source files** |
| Grand total | **GBP 3,947,866.36 ex VAT** if the stated shipping charges are added; VAT still not shown |
| Recurring charges | **GBP 2,900.54 per month** maintenance on the Diamondback library configuration |
| Lead time | **Not stated**; only a customer requested arrival date of **2026/05/06** is shown |

## Included scope identified from the readable bundle
- **2 x Diamondback Tape Library systems** from `...Diamondback 8xLTO10-FC 3yr`, with combined OTC value **GBP 3,076,942.08** and combined monthly maintenance **GBP 2,900.54**.
- Each Diamondback system explicitly includes: Full Capacity License, 10 x LTO10 FH Fibre Channel Drive line items, 2 x PDUs in frame, IEC 309 power cords, dual 2.8m power cord PDU-to-PSU, fiber tape drive wrap tool, diagnostic cartridge for LTO10, cleaning cartridge, service magazine, and a 3-year ServicePac warranty/maintenance line.
- **2 x lots of 300 LTO-10 30TB cartridges** from `...2x300 LTO-10 30TB NO-VOLSER`, giving a combined OTC value of **GBP 603,768.00**.
- The media configuration explicitly uses labeled cartridges with starting sequence **DUM000** and red / vibrant label settings.
- **4 x SAN24B-7 switch builds** from `...2x 2xSAN24B-7 3yrECA`, giving a combined OTC value of **GBP 257,082.32**.
- Each switch build explicitly includes: SAN24B-7 base unit, 2 x long-wave secure SFPs, 1 x 8-port 32Gbps SW SFP bundle, 1 x 8-port 32Gbps SW upgrade, 10 x OM3 LC/LC 10m cables, and 3-year IBM Storage Expert Care Advanced.

## Exclusions / not evidenced
- VAT or any tax amount.
- Any final reseller discounting or deal-registration pricing outcome.
- A confirmed supplier lead time.
- A final consolidated quote document with commercial terms.
- Host/SAN cable from plant on the Diamondback library config (`No Host/SAN Cable from Plant` is explicit).
- Additional services beyond the selected ServicePac / Expert Care combinations.

## Assumptions and caveats
- IBM configurator notes state these are **informational list prices**, subject to change, and may not reflect the price actually paid by the customer.
- Shipping is shown separately and is **non-discountable**.
- The summary above treats the three readable configuration outputs as one commercial batch because that is how the email context frames the request.
- Because the XLSX deal-reg workbook is unreadable, this summary is based on the IBM-generated TXT/CSV/XML exports only.

## Key discrepancies and risks
1. **Primary workbook unavailable:** `230427CSI UEA deal reg Quotes.xlsx` could not be read, so there is no readable single-file commercial source of truth.
2. **Drive-count discrepancy:** the Diamondback file name says `8xLTO10-FC`, and the email request also asks for 8 LTO10 drives, but the readable configuration line item shows **10 x `AGH4 LTO10 FH Fibre Channel Drive` per system**. This needs confirmation.
3. **Switch population ambiguity:** the request email asks for 12 x SW SFPs and 2 x LW SFPs per switch, but the readable switch config explicitly shows **2 LW SFPs**, **1 x 8-port SW SFP bundle**, and **1 x 8-port SW upgrade**. The exact short-wave SFP count is therefore not explicit in the readable lines.
4. **Media labelling/location dependency:** the presales note says LTO-10 media requires a starting VOLSER for each location. The readable media config hard-codes a `DUM000` starting sequence, so multiple locations or alternative label sequences may require rework.
5. **Service scope warning:** the Diamondback and media configs state that selected ServicePacs cannot be combined with additional service offerings, and the Diamondback config also says custom ServicePacs require scoping assistance.
6. **Lead time missing:** only a requested arrival date is present; no actual supplier lead time is stated.

## Source files used
- `230427CSI UEA deal reg Quotes.xlsx` (only as evidence that the nominal workbook source is unreadable)
- `44422669Russ 220426 CSI-UEA Diamondback 8xLTO10-FC 3yr.txt`
- `44422669Russ 220426 CSI-UEA Diamondback 8xLTO10-FC 3yr.csv`
- `44422669Russ 220426 CSI-UEA Diamondback 8xLTO10-FC 3yr.xml`
- `44422669Russ 220426 CSI-UEA 2x300 LTO-10 30TB NO-VOLSER.txt`
- `44422669Russ 220426 CSI-UEA 2x300 LTO-10 30TB NO-VOLSER.csv`
- `44422669Russ 220426 CSI-UEA 2x300 LTO-10 30TB NO-VOLSER.xml`
- `44422669Russ 220426 CSI-UEA 2x 2xSAN24B-7 3yrECA.txt`
- `44422669Russ 220426 CSI-UEA 2x 2xSAN24B-7 3yrECA.csv`
- `44422669Russ 220426 CSI-UEA 2x 2xSAN24B-7 3yrECA.xml`
- `UEA_tdsyn.txt`
