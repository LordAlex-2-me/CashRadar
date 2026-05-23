"""
parse_email.py — FirstBank Nigeria email parser.

Unchanged from original. Extracts amount, DR/CR type,
narration description, and cleared balance from the email body.
"""

import re


def extract_transaction(email_body: str) -> dict:
    transaction = {
        "type":        None,
        "amount":      None,
        "description": None,
        "balance":     None,
    }

    # Amount + type: matches '1,000.00 DR' or '50,000.00 CR'
    amount_pattern = r"Amount:\s*([\d,]+\.\d{2})\s*(DR|CR)"
    match = re.search(amount_pattern, email_body, re.IGNORECASE)
    if match:
        transaction["amount"] = float(match.group(1).replace(",", ""))
        transaction["type"]   = "debit" if match.group(2).upper() == "DR" else "credit"

    # Narration line
    desc_match = re.search(r"Narration:\s*(.+)", email_body)
    if desc_match:
        transaction["description"] = desc_match.group(1).strip()

    # Cleared balance: matches 'Cleared Balance: NGN8,578.49'
    balance_pattern = r"Cleared Balance:\s*NGN([\d,]+\.\d{2})"
    balance_match   = re.search(balance_pattern, email_body, re.IGNORECASE)
    if balance_match:
        transaction["balance"] = float(balance_match.group(1).replace(",", ""))

    return transaction
