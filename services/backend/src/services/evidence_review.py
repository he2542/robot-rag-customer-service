"""Version-bound exclusions confirmed against the corpus and answer policy."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewDecision:
    id: str
    filename: str
    document_hash: str
    start_line: int
    entry_hash: str
    reason: str


REVIEW_DECISIONS = (
    ReviewDecision(
        "EV-001", "扫地机器人100问2.txt",
        "e66c7436903e3a25062f646e9922c37c3f500a03f543e406aa9fc83fa8357327", 85,
        "39a7acafc8486e487f5fa1b7185cbeaa07795d4cfe1e75a7cc5bb4699cd1b36a",
        "Battery fault advice asks the user to unplug the battery before professional inspection.",
    ),
    ReviewDecision(
        "EV-002", "扫拖一体机器人100问.txt",
        "716518b4405efe288f622317c6055184b1ec68e3cb0b98f8279d3504a3b6e1ce", 93,
        "44b33897eb7aa74aafa74fa1194290218fe573df35976072e7f7be087676994a",
        "Motor-bearing inspection and lubrication require professional handling.",
    ),
    ReviewDecision(
        "EV-003", "故障排除.txt",
        "352d8a9c426bfa408692d69046a503673e282811ee8233800b0cf1a367c67d8b", 3,
        "37368f3b6af80121b45176d9e542ff1587f0aee8daf5deb7a441f9a366f16d09",
        "A second source repeats user battery-unplugging advice.",
    ),
    ReviewDecision(
        "EV-004", "故障排除.txt",
        "352d8a9c426bfa408692d69046a503673e282811ee8233800b0cf1a367c67d8b", 179,
        "b7d75605e0651aceefb2c523a92c3d2167f09f796888ff94f81724fddf696a6b",
        "The proposed workaround disables collision protection.",
    ),
    ReviewDecision(
        "EV-005", "故障排除.txt",
        "352d8a9c426bfa408692d69046a503673e282811ee8233800b0cf1a367c67d8b", 355,
        "de5e1fb623310f6f3c3687da2ce4c34dbc8594059cacace75894518cfa007bcc",
        "Internal motor-bearing servicing and motor replacement require professional handling.",
    ),
)
