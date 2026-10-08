import io
import unittest
from unittest.mock import patch

from app import app


class FakeSnapshot:
    def __init__(self, data):
        self.data = data
        self.exists = data is not None

    def to_dict(self):
        return self.data.copy() if self.data is not None else None


class FakeDocument:
    def __init__(self, data=None):
        self.data = data
        self.updated = None
        self.deleted = False

    def get(self):
        return FakeSnapshot(self.data)

    def update(self, data):
        self.updated = data
        self.data.update(data)

    def delete(self):
        self.deleted = True


class FakeCollection:
    def __init__(self, document):
        self.document_ref = document

    def document(self, _document_id):
        return self.document_ref


class FakeDatabase:
    def __init__(self, contestant):
        self.contestant = contestant

    def collection(self, name):
        if name != "contestants":
            raise AssertionError(f"Unexpected collection: {name}")
        return FakeCollection(self.contestant)


class FakeBlob:
    def __init__(self, name):
        self.name = name
        self.public_url = f"https://storage.example/{name}"
        self.deleted = False

    def upload_from_file(self, _stream, content_type):
        self.content_type = content_type

    def make_public(self):
        pass

    def delete(self):
        self.deleted = True


class FakeBucket:
    def __init__(self):
        self.blobs = {}

    def blob(self, name):
        self.blobs.setdefault(name, FakeBlob(name))
        return self.blobs[name]


class ContestantRealtimeTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session["admin"] = True
        self.contestant_data = {
            "name": "Candidate",
            "category": "mr_freshers",
            "active": True,
            "display_order": 2,
            "photo_url": "https://storage.example/old.jpg",
            "photo_storage_path": "contestants/old.jpg",
        }
        self.document = FakeDocument(self.contestant_data.copy())
        self.database = FakeDatabase(self.document)

    def test_active_voting_allows_name_and_photo_without_changing_identity(self):
        bucket = FakeBucket()
        with patch("app.get_status", side_effect=["active", "active"]), \
             patch("app.get_db", return_value=self.database), \
             patch("app.get_bucket", return_value=bucket):
            response = self.client.post(
                "/api/admin/contestant/candidate-02",
                data={
                    "name": "Rahul",
                    "photo": (io.BytesIO(b"\xff\xd8\xffphoto"), "rahul.jpg", "image/jpeg"),
                },
                content_type="multipart/form-data",
            )

        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["id"], "candidate-02")
        self.assertEqual(body["data"]["name"], "Rahul")
        self.assertNotIn("category", body["data"])
        self.assertNotIn("category", self.document.updated)
        self.assertNotIn("display_order", self.document.updated)
        self.assertNotIn("active", self.document.updated)
        self.assertIn("photo_storage_path", self.document.updated)
        self.assertTrue(bucket.blobs["contestants/old.jpg"].deleted)

    def test_active_voting_rejects_category_change_and_add_or_delete(self):
        with patch("app.get_status", return_value="active"), \
             patch("app.get_db", return_value=self.database):
            changed_category = self.client.post(
                "/api/admin/contestant/candidate-02",
                data={"name": "Candidate", "category": "mrs_freshers"},
            )
            added = self.client.post(
                "/api/admin/contestant/new",
                json={"category": "mr_freshers"},
            )
            deleted = self.client.post(
                "/api/admin/contestant/candidate-02/delete",
            )

        self.assertEqual(changed_category.status_code, 400)
        self.assertEqual(added.status_code, 400)
        self.assertEqual(deleted.status_code, 400)
        self.assertIsNone(self.document.updated)
        self.assertFalse(self.document.deleted)

    def test_closed_voting_accepts_unchecked_ballot_status(self):
        with patch("app.get_status", return_value="closed"), \
             patch("app.get_db", return_value=self.database):
            response = self.client.post(
                "/api/admin/contestant/candidate-02",
                data={
                    "name": "Rahul",
                    "category": "mr_freshers",
                    "display_order": "3",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.document.updated["active"], False)
        self.assertEqual(self.document.data["category"], "mr_freshers")
        self.assertEqual(self.document.data["display_order"], 3)
        self.assertEqual(self.document.data["name"], "Rahul")

    def test_results_keep_counts_attached_to_stable_contestant_id(self):
        contestants = [{
            "id": "candidate-02",
            "name": "Rahul",
            "category": "mr_freshers",
            "active": True,
            "display_order": 2,
        }]
        tallies = {
            "ballots": 5,
            "mr_freshers": {"candidate-02": 5},
        }
        with patch("app.get_status", return_value="active"), \
             patch("app.fetch_tallies", return_value=tallies), \
             patch("app.fetch_contestants", return_value=contestants):
            response = self.client.get("/api/results")

        category = response.get_json()["categories"][0]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(category["items"][0]["id"], "candidate-02")
        self.assertEqual(category["items"][0]["name"], "Rahul")
        self.assertEqual(category["items"][0]["votes"], 5)


if __name__ == "__main__":
    unittest.main()
