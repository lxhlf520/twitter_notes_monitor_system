"""Convert CSV accounts to JSON format for manage_accounts.py import"""
import csv, json
from pathlib import Path

path = Path('D:/PycharmProjects/AiSpiderProject/twitter_accounts.csv')
accounts = []
with open(path, 'r', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for row in reader:
        username = row.get('username', '').strip()
        cookie = row.get('cookie', '').strip()
        if username and cookie:
            accounts.append({"username": username, "cookie": cookie})

output = Path('D:/PycharmProjects/AiSpiderProject/twitter_notes_monitor/accounts_to_import.json')
with open(output, 'w', encoding='utf-8') as f:
    json.dump(accounts, f, ensure_ascii=False, indent=2)

print(f"Converted {len(accounts)} accounts to {output}")
print(f"Usernames: {[a['username'] for a in accounts]}")
