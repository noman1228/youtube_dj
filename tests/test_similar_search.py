from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from app.main_window import MainWindow
from app.models import Track
from app.search_dialog import SearchDialog
from app.similar_search import SimilarSearchTask, similarity_weight, view_count, youtube_id


class SimilarSearchTest(unittest.TestCase):
    def test_radio_excludes_seed_queue_duplicates_and_previous_result(self):
        task = SimilarSearchTask(Track("Seed", "https://youtu.be/seed"), "left", 1, {"queued"})
        with patch("ytmusicapi.YTMusic") as client, patch("app.similar_search.random.choices", side_effect=lambda candidates, **kw: [candidates[0]]) as choose:
            client.return_value.get_watch_playlist.return_value = {"tracks": [
                {"videoId": "seed", "title": "Seed", "year": "1995"},
                {"videoId": "queued", "title": "Already queued"},
                {"videoId": "new", "title": "New", "year": "1996", "length": "3:21"},
                {"videoId": "new", "title": "Duplicate"},
                {"videoId": "unavailable", "title": "Unavailable", "isAvailable": False},
            ]}
            results = task.find_tracks()
            self.assertEqual(len(results), 1)
            result = results[0]
            self.assertEqual(result.video_id, "new")
            self.assertEqual(result.duration_seconds, 201)
            self.assertEqual(choose.call_count, 1)
            client.return_value.get_watch_playlist.assert_called_once_with(videoId="seed", radio=True, limit=40)

    def test_closer_era_and_popularity_are_favored(self):
        seed = {"year": "1995", "views": "2M"}
        near = {"year": "1996", "views": "3M"}
        far = {"year": "2025", "views": "2K"}
        self.assertGreater(similarity_weight(seed, near, 0), similarity_weight(seed, far, 0))
        self.assertEqual(similarity_weight({}, {}, 0), 1)
        self.assertEqual(view_count("6.6K views"), 6600)
        self.assertIsNone(view_count("Unknown"))

    def test_empty_radio_and_local_files_fail_clearly(self):
        with patch("ytmusicapi.YTMusic") as client:
            client.return_value.get_watch_playlist.return_value = {"tracks": []}
            with self.assertRaisesRegex(ValueError, "No new related"):
                SimilarSearchTask(Track("Seed", "https://youtu.be/seed"), "left", 1, set()).find_tracks()
            with self.assertRaisesRegex(ValueError, "Local files"):
                SimilarSearchTask(Track("Local", "file:///song.mp3"), "left", 1, set()).find_tracks()

    def test_returns_ten_unique_recommendations(self):
        task = SimilarSearchTask(Track("Seed", "https://youtu.be/seed"), "left", 1, set())
        with patch("ytmusicapi.YTMusic") as client:
            client.return_value.get_watch_playlist.return_value = {"tracks": [
                {"videoId": str(index), "title": f"Song {index}"} for index in range(25)
            ]}
            results = task.find_tracks()
        self.assertEqual(len(results), 10)
        self.assertEqual(len({track.video_id for track in results}), 10)
        self.assertEqual(youtube_id(Track("Seed", "https://www.youtube.com/watch?v=seed")), "seed")

    def test_snapshot_does_not_change_when_deck_changes(self):
        seed = Track("Seed", "https://youtu.be/seed")
        task = SimilarSearchTask(seed, "left", 1, set())
        seed.title = "Changed"
        self.assertEqual(task.track.title, "Seed")


class SimilarSearchUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_buttons_identify_their_respective_deck(self):
        dialog = SearchDialog()
        sides = []
        dialog.similarRequested.connect(sides.append)
        for label in ("SIMILAR TO LEFT", "SIMILAR TO RIGHT"):
            next(button for button in dialog.findChildren(QPushButton) if button.text() == label).click()
        self.assertEqual(sides, ["left", "right"])
        dialog.close()

    def test_current_engine_track_is_used_for_each_deck(self):
        left, right = Track("Left", "https://youtu.be/left"), Track("Right", "https://youtu.be/right")
        dialog = Mock()
        dialog._seen_results = set()
        main = SimpleNamespace(
            left=SimpleNamespace(engine=SimpleNamespace(track=left), tracks=[left]),
            right=SimpleNamespace(engine=SimpleNamespace(track=right), tracks=[right]),
            _search_dialog=dialog,
        )
        MainWindow._search_similar(main, "right")
        dialog.search_similar.assert_called_once_with(right, "right", {"right"})
        MainWindow._search_similar(main, "left")
        self.assertEqual(dialog.search_similar.call_args.args, (left, "left", {"left"}))

    def test_late_suggestion_cannot_replace_newer_search(self):
        dialog = SearchDialog()
        dialog._pool = Mock()
        dialog.search_similar(Track("Seed", "https://youtu.be/seed"), "left", set())
        old = dialog._search_generation
        dialog.search_edit.setText("new query")
        dialog.search()
        dialog._append_result(old, Track("Old", "https://youtu.be/old"))
        self.assertEqual(dialog._result_count, 0)
        self.assertEqual(dialog._similar_side, "")
        dialog.close()


if __name__ == "__main__":
    unittest.main()
