"""Add 15 seeded negatives to claims.csv (P1b Phase 2 item 0, KI-49).

Real claims rewritten so the cited passage does not support them:
8 `unsupported` (a fact the passage doesn't contain), 7 `contradicted`
(a value the passage contradicts). Cited passage and question kept.
Marked in the hidden `_seeded` column and shuffled in.
"""

import csv
import random
from pathlib import Path

SHEET = Path("evals/judge_validation/claims.csv")

# (row index, intended verdict, rewritten claim)
SEEDED = [
    (0, "unsupported",
     "Firmware version 3.2.1 or later is required for the enterprise "
     "management protocol, which also supports 5 GHz networks."),
    (1, "unsupported",
     "All models operate on 2.4 GHz with AES-256 encryption and ship with "
     "a leather carrying case."),
    (2, "unsupported",
     "All models require firmware version 3.2.1 or later for the enterprise "
     "management protocol and ship with a spare battery."),
    (4, "contradicted",
     "The AW-2000 battery lasts up to 14 hours of continuous operation on "
     "a full charge."),
    (5, "unsupported",
     "The AW-2000-X takes 1.5 hours to fully charge when using a 30 W "
     "USB-C adapter, faster than any competitor."),
    (6, "unsupported",
     "The maximum number of devices that can be paired with the AW-2000-XE "
     "is 2 under firmware 3.2.1, and pairing is done via NFC."),
    (7, "contradicted", "The AW-2000-XP is rated IP68."),
    (8, "unsupported",
     "IP67 means the device is certified for outdoor use in all weather."),
    (9, "contradicted", "The warranty covers damage from submersion."),
    (12, "contradicted",
     "The warranty on the AW-2000 product family is 36 months from the "
     "date of purchase, covering manufacturing defects."),
    (13, "contradicted", "Legacy units are covered for 24 months."),
    (14, "unsupported",
     "Worn blades are returned to Aurora for a full refund."),
    (16, "contradicted",
     "To lodge a warranty claim in 2025, proof of purchase alone is enough; "
     "no serial number."),
    (19, "contradicted",
     "The part number for the replacement cutting blade for the AW-2000 "
     "family is RP-99."),
    (20, "unsupported",
     "The AW-2000 package contains the widget unit and a spare battery."),
]

VERDICT_LABEL = {"unsupported": "unsupported", "contradicted": "contradicted"}


def main() -> None:
    rows = list(csv.DictReader(SHEET.open(newline="", encoding="utf-8")))
    fields = list(rows[0].keys())
    if "_seeded" not in fields:
        fields.append("_seeded")
        for r in rows:
            r["_seeded"] = ""
    seeded: list[dict[str, str]] = []
    for idx, verdict, new_claim in SEEDED:
        src = rows[idx]
        seeded.append(
            {
                "claim_id": f"20261003-seeded:c{len(seeded) + 1}",
                "question": src["question"],
                "claim": new_claim,
                "cited_passage": src["cited_passage"],
                "human_verdict": "",
                "_reviewer_verdict": "",
                "_reviewer_p_supported": "",
                "_reviewer_engine": "",
                "_answer": "",
                "_notes": f"seeded negative; intended: {VERDICT_LABEL[verdict]}",
                "_seeded": verdict,
            }
        )
    all_rows = rows + seeded
    # A fixed shuffle, not a security draw.
    random.Random(20261003).shuffle(all_rows)  # noqa: S311
    with SHEET.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(all_rows)
    print(f"{len(all_rows)} rows ({len(seeded)} seeded)")


if __name__ == "__main__":
    main()
