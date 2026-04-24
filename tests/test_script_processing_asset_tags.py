import unittest

from code_components import script_processing as sp


class StoryBibleAssetTagTests(unittest.TestCase):
    def test_tag_story_bible_asset_names_is_idempotent(self) -> None:
        story_bible = {
            "characters": [
                {"name": "Alice", "aliases": ["Al"], "summary": "Alice summary"},
                {"name": "@Bob", "aliases": ["Bobby"], "summary": "Bob summary"},
            ],
            "props": [
                {"name": "Key", "evidence": ["Key appears"]},
                {"name": "@Map", "evidence": ["Map appears"]},
            ],
        }

        tagged = sp._tag_story_bible_asset_names(story_bible)
        tagged_again = sp._tag_story_bible_asset_names(tagged)

        self.assertEqual(["@Alice", "@Bob"], [item["name"] for item in tagged_again["characters"]])
        self.assertEqual(["@Key", "@Map"], [item["name"] for item in tagged_again["props"]])
        self.assertEqual(["Al"], tagged_again["characters"][0]["aliases"])
        self.assertEqual(["Bobby"], tagged_again["characters"][1]["aliases"])
        self.assertEqual(["Key appears"], tagged_again["props"][0]["evidence"])

    def test_storyboard_validation_accepts_tagged_and_untagged_names(self) -> None:
        story_bible = {
            "characters": [{"name": "@Alice", "aliases": []}],
            "props": [{"name": "@Key"}],
        }
        episode_payload = {
            "generated_content": {"script": ""},
            "episode_plan": {"props_used": ["Key"]},
        }
        storyboard = {
            "scenes": [
                {
                    "shots": [
                        {
                            "characters": ["Alice"],
                            "visual": "Close shot; 道具:@Key",
                            "dialogue": "",
                        }
                    ]
                }
            ]
        }

        validation = sp._validate_storyboard(
            storyboard=storyboard,
            episode_payload=episode_payload,
            story_bible=story_bible,
        )

        self.assertEqual([], validation["unknown_characters"])
        self.assertEqual([], validation["missing_required_props"])
        self.assertEqual([], validation["unknown_props"])


if __name__ == "__main__":
    unittest.main()
