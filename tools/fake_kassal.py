#!/usr/bin/env python3
"""Atrapa Kassalapp do testów cen: lokalny serwer z /api/v1/products i /api/v1/products/prices-bulk.
Port z FAKE_KASSAL_PORT (domyślnie 8110). FAKE_KASSAL_LOG=plik -> dopisuje tam każde zapytanie (metoda i ścieżka).
Wymaga nagłówka 'Authorization: Bearer test', inaczej 401. Daty cen liczy od dzisiaj, żeby test nie starzał się."""
import json, os
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

TODAY = date.today()
FRESH, OLD = str(TODAY - timedelta(days=1)), "2023-04-13"
VEG = [{"name": "Frukt & grønt"}, {"name": "Grønnsaker"}]


def prod(ean, name, store, price, weight, unit, day=FRESH, cat=VEG):
    return {"ean": ean, "name": name, "current_price": price, "current_unit_price": None, "weight": weight,
            "weight_unit": unit, "store": {"code": store, "name": store}, "category": cat,
            "price_history": [{"price": price, "date": day + "T08:00:00.000000Z"}]}


# 'gulrot' to składnik przepisu z atrapy modelu (2 stk). Dobre są tylko dwa pierwsze produkty.
GULROT = [
    prod("7000000001001", "Gulrot 750g Beger", "MENY_NO", 34.9, 750, "g"),
    prod("7000000001001", "Gulrot 750g Beger", "SPAR_NO", 29.9, 750, "g"),          # ten sam EAN taniej: wygrywa 29,90
    prod("7000000001002", "Gulrot 400g Gartner", "SPAR_NO", 18.9, 400, "g"),
    prod("7000000001003", "Gulrotkake 396 g", "ODA_NO", 49.4, 0, "g", cat=[{"name": "Bakevarer og kjeks"}]),  # inne słowo
    prod("7000000001004", "Gulrot 1kg", "KIWI", 17.9, 1000, "g", day=OLD),          # sieć bez świeżych cen
    prod("7000000001005", "Gulrot 500g Gammel pris", "MENY_NO", 9.9, 500, "g", day=OLD),  # cena sprzed lat
    prod("7000000001006", "Smoothie Gulrot 150 g", "ODA_NO", 20.2, 0, "g", cat=[{"name": "Barneprodukter"}]),
]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, body):
        b = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def handle_any(self, method):
        u = urlparse(self.path)
        if os.getenv("FAKE_KASSAL_LOG"):
            with open(os.environ["FAKE_KASSAL_LOG"], "a") as f:
                f.write(f"{method} {self.path}\n")
        if self.headers.get("Authorization") != "Bearer test":
            return self.reply(401, {"message": "Unauthenticated."})
        if method == "GET" and u.path == "/api/v1/products":
            q = parse_qs(u.query)
            text, page = q.get("search", [""])[0].lower(), int(q.get("page", ["1"])[0])
            return self.reply(200, {"data": GULROT if "gulrot" in text and page == 1 else []})
        if method == "POST" and u.path == "/api/v1/products/prices-bulk":
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            data = [{"ean": e, "name": "x", "weight": 750, "weight_unit": "g", "price_history": [], "stores": [
                {"store": "SPAR_NO", "name": "SPAR", "current_price": "27.90", "last_checked": str(TODAY) + "T08:00:00Z"},
                {"store": "KIWI", "name": "KIWI", "current_price": "1.00", "last_checked": OLD + "T08:00:00Z"},
                {"store": "MENY_NO", "name": "Meny", "current_price": "33.90", "last_checked": str(TODAY) + "T08:00:00Z"}]}
                    for e in body.get("eans", []) if e == "7000000001001"]
            return self.reply(200, {"data": data})
        self.reply(404, {"message": "not found"})

    def do_GET(self):
        self.handle_any("GET")

    def do_POST(self):
        self.handle_any("POST")


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(os.getenv("FAKE_KASSAL_PORT", "8110"))), H).serve_forever()
