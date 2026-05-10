# UEA Diamondback batch commercial summary

## Scope and evidence used
This summary is limited to the prepared UEA Diamondback batch input. The only directly supplied source file in that bundle is:
- `/root/.openclaw/dropbox/inbox/UEA/Diamondback/UEA Diamondback Config Sanity Check Review v6.docx`

That review states it was prepared from the email trail plus Diamondback and SAN TXT/CSV/CFR/XML outputs, but those underlying files were not directly supplied in this prepared bundle.

## Most likely source-of-truth pricing file
The most likely source-of-truth pricing references are the **Diamondback TXT output** and **SAN switch TXT output**, because Appendix B and Appendix C each say the TXT output is the **"canonical human-readable config reference"**. That said, this is an inference from the review document, not a direct check of the original pricing files.

## Core commercial summary
- **Project / quote name:** University of East Anglia (UEA) Diamondback and SAN configs
- **Revision / date:** Review document v6; title dated **23 April 2026**
- **Vendor / manufacturer:** **IBM** is the best-supported reading from the bundle, because the review refers to **IBM configuration outputs** and IBM-branded line items. The contracting supplier is **not explicitly identified**.
- **Lead time:** **Not evidenced** in the prepared bundle.
- **VAT:** **Not evidenced** in the prepared bundle.
- **Formal grand total:** **Not evidenced** in the prepared bundle.

## Evidenced pricing figures
The review provides these totals:

### Diamondback
- Hardware purchase: **GBP 3,076,942.08**
- Monthly maintenance: **GBP 2,900.54**
- Shipping and handling: **GBP 9,085.84**

### SAN switches
- Hardware purchase: **GBP 257,082.32**
- Shipping and handling: **GBP 928.48**

### Inferred combined one-time value
Because no explicit quote subtotal/grand total is shown, the strongest defensible combined one-time figures are:
- **Hardware purchase total:** **GBP 3,334,024.40**
- **Shipping and handling total:** **GBP 10,014.32**
- **Inferred pre-VAT one-time total if shipping is included:** **GBP 3,344,038.72**

This last figure is an inference from the review appendices, not a stated quote total.

## What appears to be included
### Diamondback side
The review evidences two Diamondback systems with identical structure, including:
- Diamondback Tape Library 3yr
- 10 x LTO10 FH Fibre Channel Drive per system
- Full Capacity License
- PDU and power items
- Diagnostic cartridge for LTO10
- LTO cleaning cartridge
- Preloaded Media enablement kit
- LTO Service Magazine
- 3-year warranty / maintenance items
- Shipping and handling

### SAN side
The review evidences four SAN switch systems with the same structure, including per switch:
- IBM Storage Networking SAN24B-7
- 2 x long-wave optics
- 1 x 8-port 32Gbps short-wave SFP bundle
- 1 x 8-port 32Gbps short-wave upgrade
- 10 x OM3 LC/LC 10m cables
- 3-year Expert Care / support-related items
- Shipping and handling

## What is not clearly evidenced / likely excluded from the visible config output
- **300 LTO-10 cartridges** requested in the email trail are **not visibly evidenced** in the reviewed Diamondback config output.
- **VAT** is not shown.
- **Lead time** is not shown.
- A single formal **quote subtotal / grand total** is not shown.
- The prepared bundle does **not** include a spreadsheet or the raw TXT outputs themselves.

## Assumptions used
- The review document is treated as the controlling evidence because it is the only directly supplied source in the prepared bundle.
- The Diamondback TXT and SAN TXT outputs are treated as the most likely pricing references because the review explicitly calls them the canonical human-readable config references.
- The combined one-time figure of **GBP 3,344,038.72** is inferred by summing hardware purchase and shipping totals across Diamondback and SAN; it is **not** stated as a formal subtotal in the bundle.
- IBM is treated as the likely vendor/manufacturer, but not as a confirmed contracting entity.

## Notable risks and discrepancies
1. **Drive-count mismatch:** the email trail asks for **8 x LTO10 drives** per library, but the reviewed Diamondback config shows **10 drives per library**.
2. **Media not evidenced:** the email trail asks for **300 LTO-10 carts**, but the review says those cartridges are not visibly evidenced in the supplied Diamondback config output.
3. **Naming inconsistency:** the Diamondback package naming says **8xLTO10-FC**, while the visible config content shows **10 drives per system**.
4. **SAN optics proof remains incomplete:** the visible SAN lines broadly support the build, but the review says they do **not conclusively prove** the requested **12 x SW SFPs populated** state.
5. **Pre-quote status risk:** the email trail includes **"All configs for review by BP prior to quoting."**, which suggests the material may still have been under review rather than finalized for quotation.
6. **Missing source material risk:** the prepared bundle carries the flag **"No spreadsheet found in batch"**, and the underlying raw pricing/config files were not directly supplied here.

## Bottom line
The prepared bundle supports a cautious commercial view, not a clean final quote. The best-evidenced one-time value is **GBP 3,344,038.72 pre-VAT including shipping** if the appendix totals are rolled up, but that figure is inferred rather than formally quoted. The biggest blockers before treating this as quote-ready are the **8-vs-10 drive mismatch**, the **missing visible evidence for the 300 LTO-10 cartridges**, and the **remaining SAN optics confirmation point**.