# Controlled source manifest

manifest.json records acquired public sources within the existing pilot seed.
The first source is the three-page Premier Energies addendum/corrigendum linked
from SEBI's26August2024 filing page. The original196270 bytes have SHA256
a15329da96a20117a5cfaccf535ab3dc805c6ed195e392bb5ec6131f8f246347 and remain
under ignored data/raw. Do not commit the PDF or derived render artifacts.

The source listing date and24August2024 signed document date are recorded
separately; neither is silently used as a financial period/effective date. The
referenced20August2024 RHP is not acquired/registered, so parent_filing_id is null.
Filing/version IDs remain null until application ingestion registers them. The
raw CIN is source metadata, not completed entity resolution.

pypdf confirms three native-text pages; bundled Poppler rendered all three, and
each was inspected. Reader warnings concern the original xref/hint tables;
original bytes were retained unchanged. No Docling/OCR, persisted evidence,
accepted observation, corpus publication or reviewed gold annotation is claimed
by this source acquisition step.

Primary sources: [SEBI filing page](https://www.sebi.gov.in/filings/public-issues/aug-2024/premier-energies-limited-addendum-to-rhp_86351.html),
[SEBI original PDF](https://www.sebi.gov.in/sebi_data/attachdocs/aug-2024/1725009610554.PDF).
