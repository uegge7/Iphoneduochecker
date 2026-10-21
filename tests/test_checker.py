import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import checker  # noqa: E402

# Nachgebaute (synthetische) Antworten im Format der Apple-Endpunkte
HTML = """<script>window.PRODUCT_SELECTION_BOOTSTRAP = {"products":[
{"partNumber":"MAAA1ZD/A","dimensionCapacity":"256gb","dimensionColor":"black"},
{"partNumber":"MAAA2ZD/A","dimensionCapacity":"512gb","dimensionColor":"silver"},
{"partNumber":"MAAA3ZD/A","dimensionCapacity":"1tb","dimensionColor":"black"}]}</script>"""

PICKUP = {"body": {"stores": [
    {"storeName": "Rosenstraße", "city": "München", "storeDistanceWithUnit": "0,8 km",
     "partsAvailability": {
         "MAAA1ZD/A": {"pickupDisplay": "available", "pickupSearchQuote": "Heute verfügbar"},
         "MAAA2ZD/A": {"pickupDisplay": "unavailable", "pickupSearchQuote": "Derzeit nicht verfügbar"}}},
    {"storeName": "Köln Schildergasse", "city": "Köln", "storeDistanceWithUnit": "456 km",
     "partsAvailability": {"MAAA1ZD/A": {"pickupDisplay": "available"}}},
]}}

# Antwortformat der Shopify-Storefront-API (wie bei epos beobachtet)
SHOPIFY = {"data": {
    "p0": {"title": "iPhone Duo 256 GB Sternenweiß", "variants": {"nodes": [{"sku": "MK2D4ZD/A", "storeAvailability": {"nodes": [
        {"available": True, "pickUpTime": "Usually ready in 2-4 days", "quantityAvailable": 0,
         "location": {"name": "epos Zimbapark", "address": {"city": "Bürs"}}},
        {"available": True, "pickUpTime": "Usually ready in 24 hours", "quantityAvailable": 2,
         "location": {"name": "epos Messepark", "address": {"city": "Dornbirn"}}},
    ]}}]}},
    "p1": None,
}}


class CheckerTest(unittest.TestCase):
    def test_extract_parts_filters_capacity(self):
        parts = checker.extract_parts_from_html(HTML, ["256gb", "512gb"])
        self.assertEqual(set(parts), {"MAAA1ZD/A", "MAAA2ZD/A"})

    def test_parse_pickup_filters_distance(self):
        rows = checker.parse_pickup(PICKUP, max_distance_km=120)
        self.assertEqual(len(rows), 2)
        avail = [r for r in rows if r[3]]
        self.assertEqual(avail[0][:3], ("Rosenstraße", "München", "MAAA1ZD/A"))

    def test_parse_pickup_store_filter(self):
        rows = checker.parse_pickup(PICKUP, store_filter=["München", "Augsburg", "Sindelfingen"])
        self.assertEqual({r[0] for r in rows}, {"Rosenstraße"})

    def test_state_roundtrip(self):
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "state.json")
        self.assertEqual(checker.load_state(path), set())
        checker.save_state(path, {("Zürich", "Rennweg", "MK2D4QL/A")})
        self.assertEqual(checker.load_state(path), {("Zürich", "Rennweg", "MK2D4QL/A")})

    def test_distance_parsing(self):
        self.assertEqual(checker.parse_distance_km({"storeDistanceWithUnit": "12,5 km"}), 12.5)
        self.assertEqual(checker.parse_distance_km({"storedistance": 3}), 3.0)

    def test_fulfillment_url(self):
        url = checker.pickup_url("ch-de", ["A/A", "B/A"], "8001")
        self.assertIn("/ch-de/shop/retail/pickup-message?pl=true", url)
        self.assertIn("parts.1=B%2FA", url)

    def test_shopify_handle_and_query(self):
        region = {"handle_template": "iphone-duo-{part}"}
        self.assertEqual(checker.shopify_handle(region, "MK2D4ZD/A"), "iphone-duo-mk2d4zd-a")
        query, aliases = checker.shopify_query(["MK2D4ZD/A", "MK2G4ZD/A"], region)
        self.assertIn('p1: product(handle: "iphone-duo-mk2g4zd-a")', query)
        self.assertEqual(aliases, {"p0": "MK2D4ZD/A", "p1": "MK2G4ZD/A"})

    def test_parse_shopify_needs_real_stock(self):
        rows = checker.parse_shopify(SHOPIFY, {"p0": "MK2D4ZD/A", "p1": "MK2G4ZD/A"})
        self.assertEqual(len(rows), 2)
        hits = [r for r in rows if r[3]]
        self.assertEqual(hits, [("epos Messepark", "Dornbirn", "MK2D4ZD/A", True, "2 Stück vor Ort")])

    def test_resolve_parts_from_other_region(self):
        parts = checker.resolve_parts({}, {"name": "epos", "parts_from": "Österreich"},
                                      {"Österreich": {"MK2D4ZD/A": "256GB starwhite"}})
        self.assertEqual(parts, {"MK2D4ZD/A": "256GB starwhite"})


if __name__ == "__main__":
    unittest.main()
