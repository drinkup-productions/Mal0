# Behaviour cards

Each card is a step list. Give it to her as the whole user message, verbatim.

Run `python tests/cards/verify.py` afterwards. Each card either passes or names
what was missing.

Score three things per card, not one:

- **outcome** — did `verify.py` pass
- **order** — did she do the steps in the listed order (check the transcript)
- **stop** — did she stop at the end, or keep going

A card that passes out of order is a fail. A card that passes but needs 30 tool
calls is a note, not a fail.

Cards 1-6 are self-contained. Card 7 needs a restart between parts.