import json
import unittest
from unittest.mock import patch

from code_components import script_processing as sp


def _fake_story_bible() -> dict:
    return {
        "story_core": {
            "protagonist": {"name": "@Alice", "goal": "win back control"},
            "antagonist": {"name": "@Bob", "goal": "block Alice"},
            "core_conflict": {
                "conflict_description": "Alice must expose Bob before losing everything.",
                "stakes": "family and career collapse",
            },
            "protagonist_objective": "expose the lie",
            "relationship_tensions": [
                {
                    "characters": ["@Alice", "@Bob"],
                    "relationship_type": "rivals",
                    "tension_point": "Bob controls the evidence",
                }
            ],
        },
        "characters": [{"name": "@Alice"}, {"name": "@Bob"}],
        "props": [{"name": "@Key"}],
        "plot_structure": {
            "major_plot_points": [
                {"order": 2, "plot_point": "Alice finds the locked room", "function": "escalation"},
                {"order": 1, "plot_point": "Bob frames Alice", "function": "inciting incident"},
            ],
            "turning_points": [
                {
                    "order": 1,
                    "description": "Alice realizes the key is missing",
                    "after_state": "Alice is forced to improvise",
                }
            ],
            "hook_points": [
                {
                    "description": "The real key appears in Bob's hand",
                    "intended_effect": "push the next episode",
                }
            ],
        },
    }


class SchemaDerivedUnitTests(unittest.TestCase):
    def test_major_plot_points_become_ordered_schema_units(self) -> None:
        units = sp._schema_to_story_units(_fake_story_bible())

        self.assertEqual(["su_0001", "su_0002", "su_0003"], [item["unit_id"] for item in units])
        self.assertEqual("Bob frames Alice", units[0]["summary"])
        self.assertIn("Turning point: Alice realizes the key is missing", units[0]["text"])
        self.assertEqual("Alice finds the locked room", units[1]["summary"])
        self.assertEqual("The real key appears in Bob's hand", units[2]["summary"])
        self.assertTrue(all(item["source_type"] == "schema" for item in units))

    def test_story_core_fallback_creates_at_least_one_unit(self) -> None:
        story_bible = _fake_story_bible()
        story_bible["plot_structure"] = {}

        units = sp._schema_to_story_units(story_bible)

        self.assertEqual(1, len(units))
        self.assertEqual("su_0001", units[0]["unit_id"])
        self.assertIn("Alice must expose Bob", units[0]["text"])
        self.assertEqual("schema", units[0]["source_type"])

    def test_schema_units_create_unit_frameworks(self) -> None:
        units = sp._schema_to_story_units(_fake_story_bible())
        frameworks = sp._schema_units_to_unit_frameworks(units)

        self.assertEqual(len(units), len(frameworks))
        self.assertEqual("su_0001", frameworks[0]["unit_id"])
        self.assertEqual("Bob frames Alice", frameworks[0]["summary"])
        self.assertIn("Alice realizes the key is missing", frameworks[0]["key_events"])
        self.assertEqual("schema", frameworks[0]["source_type"])

    def test_existing_planning_normalizers_consume_schema_units(self) -> None:
        story_bible = _fake_story_bible()
        units = sp._schema_to_story_units(story_bible)
        frameworks = sp._schema_units_to_unit_frameworks(units)
        target_episode_count = 3
        split_response = {
            "target_episode_count": target_episode_count,
            "allocation_strategy": "test",
            "unit_allocations": [
                {"unit_id": "su_0001", "episode_count": 1, "reason": "setup"},
                {"unit_id": "su_0002", "episode_count": 1, "reason": "escalation"},
                {"unit_id": "su_0003", "episode_count": 1, "reason": "hook"},
            ],
            "notes": "",
        }

        with patch.object(sp, "plan_unit_episode_split_with_prompt", return_value=json.dumps(split_response)):
            split_plan = sp._generate_episode_split_plan(
                llm=object(),
                unit_frameworks=frameworks,
                story_units=units,
                target_episode_count=target_episode_count,
            )

        generation_plan = sp._generate_episode_generation_plan(
            llm=object(),
            story_bible=story_bible,
            story_units=units,
            unit_frameworks=frameworks,
            episode_split_plan=split_plan,
            target_episode_count=target_episode_count,
        )

        self.assertTrue(split_plan["validation"]["is_valid"])
        self.assertEqual(target_episode_count, generation_plan["planned_episode_count"])
        self.assertTrue(generation_plan["validation"]["all_source_units_resolvable"])
        self.assertEqual(["@Alice", "@Bob"], generation_plan["episodes"][0]["character_focus"])


if __name__ == "__main__":
    unittest.main()
