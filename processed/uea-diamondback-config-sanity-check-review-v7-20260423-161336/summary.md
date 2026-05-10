# UEA Diamondback commercial summary

## Basis and source-of-truth view
- Prepared evidence available for this run consists of the extracted text from `UEA Diamondback Config Sanity Check Review v7.docx` only.
- Based on that review, the most likely source-of-truth pricing file is `230427CSI UEA deal reg Quotes.xlsx`, because the review says it directly states `Total Customer Price GBP 986,776.84` and that all prices are without taxes such as VAT.
- Important limitation: that spreadsheet was not included in the prepared bundle available here, and the input flags also say `No spreadsheet found in batch`. So pricing is being taken from the v7 review's cited findings, not independently re-verified from the raw spreadsheet in this run.

## Commercial summary
- **Project / quote:** UEA Diamondback Config Sanity Check Review v7
- **Vendor / supplier:** IBM / CSI **uncertain**. IBM is explicit in the cited configuration outputs, while `CSI` appears in filenames and in the cited spreadsheet name. The contracting / quoting entity is not explicit in the prepared bundle alone.
- **Revision / date:** v7 dated 23 April 2026
- **Subtotal (most likely ex VAT):** GBP 986,776.84
- **VAT:** Not evidenced. The review says: `All prices are without taxes, such as VAT.`
- **Grand total:** GBP 986,776.84 excluding VAT is the most supportable total from the prepared bundle. No VAT-inclusive grand total is evidenced.
- **Lead time:** Not evidenced in the prepared bundle.

## What appears to be included
- **Diamondback libraries:** The batch evidence cited in the review shows **2 libraries**, but each is configured with **10 LTO-10 Fibre Channel drives**, not 8.
- **LTO-10 media:** A separate media quote shows **two repeated blocks** of `15 x 30 TB LTO10 Tape Cartridge Labeled 20-pack`, which the review interprets as **300 cartridges per block** and **600 total across the batch**. That is consistent with the emailed requirement for **2 lots**, each with **300 cartridges**.
- **VOLSER selections:** The media quote reportedly includes starting characters `DUM000` plus `Base 10 Count Lbl Sequence`, which supports the presales note that LTO-10 media needs starting VOLSER for each location.
- **SAN switches and cables:** The review cites **4 switch systems**. Per switch, the visible evidence reportedly shows `2` LW SFPs, `1` x `8 x 32Gbps SW SFP Bundle`, `1` x `8 Port 32Gbps SW Upgrade`, and `10` x `OM3 Cable LC/LC 10 m`, which directly supports **40 x 10 m cables** across the batch.

## What is not evidenced or remains uncertain
- **Lead time** is not stated.
- **VAT amount** is not stated.
- The prepared bundle does **not** contain the raw spreadsheet or IBM TXT outputs, only a review document that cites them.
- The review says the switch build is **credible**, but the visible lines do **not** literally state `12 x SW populated` or `14 ports licensed`, so that point is not fully proved from the supplied evidence alone.
- The exact one-to-one mapping of each **300-cartridge** media block to a specific physical library is inferred from repeated structure and naming, not explicitly labelled as `Library 1` and `Library 2`.

## Key discrepancies and risks
1. **Drive-count mismatch:** The email requirement cited in the review asks for **8 drives per library**, but the Diamondback config reportedly shows **10 drives per library**. This is the clearest commercial / technical mismatch.
2. **Separate media quote:** The requested 300 cartridges are evidenced only in a **separate media quote**, not in the Diamondback library config itself. That linkage should stay attached to the main quote.
3. **Package naming inconsistency:** The library folder name says `8xLTO10-FC`, but the cited config content shows 10 drives.
4. **VOLSER naming inconsistency:** The media folder name says `NO-VOLSER`, but the cited content reportedly includes explicit VOLSER character selections.
5. **Pricing evidence gap:** The spreadsheet appears to be the best pricing authority, but it was not present in the prepared bundle for independent checking here.
6. **IBM totals are not customer-paid totals:** The review says IBM note 4 states the IBM TXT totals are informational and do not reflect what the customer actually pays.

## Pricing detail cited in the review
- **Most likely one-time customer total:** GBP 986,776.84
- **Tax basis:** Excluding VAT / taxes
- **Internal cross-check cited by the review:**
  - Total list price in the spreadsheet: GBP 3,947,866.36
  - Combined IBM purchase-plus-shipping total inferred across the three config outputs: GBP 3,947,866.36
  - This match is presented in the review as a consistency check.
- **Monthly maintenance:** GBP 2,900.54 per month is cited for Diamondback in the IBM outputs, but the review says this does **not** visibly flow into the spreadsheet's stated total customer price.

## Bottom line
The strongest commercial reading from the prepared bundle is that the batch points to a **one-time customer total of GBP 986,776.84 excluding VAT**, most likely sourced from `230427CSI UEA deal reg Quotes.xlsx`. However, the quote package is **not clean**: the Diamondback library configuration appears to miss the emailed requirement by showing **10 drives per library instead of 8**, the media proof sits in a **separate quote**, and the switch population / licensing point remains **credible but not fully explicit** on the visible evidence cited in the review.

## Source files used for this run
- `/root/.openclaw/dropbox/inbox/UEA/Diamondback/UEA Diamondback Config Sanity Check Review v7.docx` (via the prepared extract embedded in `summary_input.json`)
