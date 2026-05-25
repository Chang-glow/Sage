"""Phase 13 Layer 1 — data foundation: YAML, config, model, loaders."""
import unittest


class TestAgentModelFields(unittest.TestCase):
    """Verify Agent model has world dynamic fields."""

    def test_agent_model_has_hometown(self):
        from app.models.agent import Agent
        self.assertTrue(hasattr(Agent, "hometown"))

    def test_agent_model_has_is_away(self):
        from app.models.agent import Agent
        self.assertTrue(hasattr(Agent, "is_away"))

    def test_agent_model_has_birthday(self):
        from app.models.agent import Agent
        self.assertTrue(hasattr(Agent, "birthday"))


class TestEducationYaml(unittest.TestCase):
    """Verify education.yaml has primary + middle schools."""

    def test_primary_schools_exist(self):
        from app.world.city_data import load_education
        institutions = load_education()
        primary = [i for i in institutions if i["type"] == "小学"]
        self.assertEqual(len(primary), 3)
        names = {i["name"] for i in primary}
        self.assertIn("平陵一小", names)
        self.assertIn("平陵二小", names)
        self.assertIn("平陵实验小学", names)

    def test_middle_schools_exist(self):
        from app.world.city_data import load_education
        institutions = load_education()
        middle = [i for i in institutions if i["type"] == "初中"]
        self.assertEqual(len(middle), 3)
        names = {i["name"] for i in middle}
        self.assertIn("平陵一中初中部", names)
        self.assertIn("平陵二中初中部", names)
        self.assertIn("平陵实验中学", names)

    def test_total_institution_count(self):
        from app.world.city_data import load_education
        institutions = load_education()
        self.assertEqual(len(institutions), 16)

    def test_primary_age_range(self):
        from app.world.city_data import load_education
        institutions = load_education()
        for i in institutions:
            if i["type"] == "小学":
                self.assertEqual(i["age_range"], [6, 12])

    def test_middle_school_age_range(self):
        from app.world.city_data import load_education
        institutions = load_education()
        for i in institutions:
            if i["type"] == "初中":
                self.assertEqual(i["age_range"], [12, 15])


class TestEntertainmentYaml(unittest.TestCase):
    """Verify entertainment.yaml loads correctly."""

    def test_entertainment_file_exists_and_loads(self):
        from app.world.city_data import load_entertainment
        data = load_entertainment()
        self.assertIsInstance(data, dict)
        self.assertIn("venues", data)
        self.assertIn("restaurants", data)

    def test_venues_count(self):
        from app.world.city_data import get_venues
        venues = get_venues()
        self.assertEqual(len(venues), 3)

    def test_venue_structure(self):
        from app.world.city_data import get_venues
        venues = get_venues()
        for v in venues:
            self.assertIn("id", v)
            self.assertIn("name", v)
            self.assertIn("type", v)
            self.assertIn("location", v)
            self.assertIn("district", v)
            self.assertIn("min_age", v)

    def test_restaurants_count(self):
        from app.world.city_data import get_restaurants
        restaurants = get_restaurants()
        self.assertEqual(len(restaurants), 5)

    def test_restaurant_structure(self):
        from app.world.city_data import get_restaurants
        restaurants = get_restaurants()
        for r in restaurants:
            self.assertIn("id", r)
            self.assertIn("name", r)
            self.assertIn("type", r)
            self.assertIn("location", r)
            self.assertIn("note", r)

    def test_venues_by_name(self):
        from app.world.city_data import get_venues
        venues = get_venues()
        names = {v["name"] for v in venues}
        self.assertIn("夜色酒吧", names)
        self.assertIn("星辰网吧", names)
        self.assertIn("好声音KTV", names)

    def test_restaurants_by_name(self):
        from app.world.city_data import get_restaurants
        restaurants = get_restaurants()
        names = {r["name"] for r in restaurants}
        self.assertIn("老杨头炒鸡", names)
        self.assertIn("桥南酱骨架", names)
        self.assertIn("平陵大酒店", names)
        self.assertIn("老刘家羊肉汤", names)
        self.assertIn("胖子酸菜鱼", names)


class TestCityProjectsPool(unittest.TestCase):
    """Verify city project templates."""

    def test_city_projects_pool_exists(self):
        from app.world.city_data import get_city_projects_pool
        pool = get_city_projects_pool()
        self.assertGreaterEqual(len(pool), 4)

    def test_project_template_structure(self):
        from app.world.city_data import get_city_projects_pool
        pool = get_city_projects_pool()
        for p in pool:
            self.assertIn("type", p)
            self.assertIn("template", p)

    def test_infrastructure_events(self):
        from app.world.city_data import get_infrastructure_events
        events = get_infrastructure_events()
        self.assertGreaterEqual(len(events), 5)
        for e in events:
            self.assertIsInstance(e, str)
            self.assertGreater(len(e), 10)


class TestConfigWorldDynamic(unittest.TestCase):
    """Verify config.yaml world_dynamic section."""

    def test_world_dynamic_section_exists(self):
        from app.config import config as yaml_config
        self.assertTrue(hasattr(yaml_config, "world_dynamic"))

    def test_config_keys_exist(self):
        from app.config import config as yaml_config
        wd = yaml_config.world_dynamic
        keys = [
            "education_transfer_probability",
            "education_transfer_cross_city_ratio",
            "education_gaokao_local_ratio",
            "career_job_change_probability",
            "career_unemployment_probability",
            "career_job_search_interval_days",
            "career_unemployed_at_start_ratio",
            "city_project_interval_days",
            "education_mobility_hour",
            "career_mobility_hour",
            "city_development_hour",
        ]
        for key in keys:
            self.assertTrue(hasattr(wd, key), f"Missing config key: world_dynamic.{key}")


class TestEntertainmentCache(unittest.TestCase):
    """Verify entertainment loader caching."""

    def test_load_entertainment_caches(self):
        from app.world import city_data
        city_data._entertainment_cache = None
        data1 = city_data.load_entertainment()
        data2 = city_data.load_entertainment()
        self.assertIs(data1, data2)


if __name__ == "__main__":
    unittest.main()
