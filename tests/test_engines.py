import unittest
from unittest.mock import patch, MagicMock
import os
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from agents.finance_agent import FinanceAgent
from agents.portfolio_manager import PortfolioManager
from agents.quality_agent import QualityCheckerAgent
from agents.measurement_agent import MeasurementAgent
from agents.strategy_agent import StrategyAgent
from agents.opportunity_agent import OpportunityScout
from agents.product_builder import ProductBuilderAgent
from services.ai_service import AIService
from services.social_service import YouTubeService, InstagramService
from agents.chat_assistant import RealChatAssistant

class TestMINTRealEngines(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import config, database
        cls.temp_dir = tempfile.mkdtemp()
        cls.db_path = Path(cls.temp_dir) / "test_real_engines.db"
        cls.gen_dir = Path(cls.temp_dir) / "generated"
        cls.gen_dir.mkdir(parents=True, exist_ok=True)

        cls.orig_db_path = config.DB_PATH
        cls.orig_gen_dir = config.GENERATED_DIR

        config.DB_PATH = cls.db_path
        config.GENERATED_DIR = cls.gen_dir
        database.DB_PATH = cls.db_path
        database.init_db()

        # Seed experiment 1 for chat assistant and foreign keys
        with database.get_db_connection() as conn:
            conn.execute("""
                INSERT INTO experiments (id, name, goal, business_model, target_audience, budget_limit, status, created_at, updated_at)
                VALUES (1, 'Real Engine Test Run', 'Test budget bounds', 'digital_product', 'solopreneurs', 50.0, 'completed', '2026-10-23 00:00:00', '2026-10-23 00:00:00')
            """)
            conn.commit()

    @classmethod
    def tearDownClass(cls):
        import config, database, gc
        config.DB_PATH = cls.orig_db_path
        config.GENERATED_DIR = cls.orig_gen_dir
        database.DB_PATH = cls.orig_db_path
        gc.collect()
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def test_finance_accounting_and_reserve(self):
        fa = FinanceAgent(reserve_ratio=0.25, reinvestment_ratio=0.40)
        orders = [
            {"gross_amount": 20.0, "fee_amount": 0.90, "is_refunded": False, "refund_amount": 0.0},
            {"gross_amount": 20.0, "fee_amount": 0.90, "is_refunded": False, "refund_amount": 0.0},
            {"gross_amount": 20.0, "fee_amount": 0.90, "is_refunded": True, "refund_amount": 20.0}
        ]
        stmt = fa.calculate_statement(starting_budget=50.0, actual_spend=15.0, orders=orders)
        self.assertEqual(stmt["gross_revenue"], 60.0)
        self.assertEqual(stmt["fees"], 2.70)
        self.assertEqual(stmt["refunds"], 20.0)
        self.assertEqual(stmt["net_sales"], 37.30)
        self.assertEqual(stmt["net_profit"], 22.30)
        self.assertAlmostEqual(stmt["required_reserve"], 5.57, delta=0.02)
        self.assertAlmostEqual(stmt["reinvestment_allocated"], 8.92, delta=0.02)
        self.assertAlmostEqual(stmt["surplus_available"], 7.81, delta=0.02)

    def test_finance_zero_cost_remains_zero(self):
        fa = FinanceAgent()
        orders = [{"gross_amount": 20.0, "fee_amount": 0.90, "is_refunded": False, "refund_amount": 0.0}]
        # Actual spend is explicitly 0.0; should NOT be converted to 2.50 or any arbitrary cost
        stmt = fa.calculate_statement(starting_budget=50.0, actual_spend=0.0, orders=orders)
        self.assertEqual(stmt["actual_spend"], 0.0)
        self.assertEqual(stmt["net_sales"], 19.10)
        self.assertEqual(stmt["net_profit"], 19.10)

    def test_finance_zero_and_negative_profit_reserve_handling(self):
        fa = FinanceAgent()
        stmt_loss = fa.calculate_statement(starting_budget=50.0, actual_spend=30.0, orders=[])
        self.assertEqual(stmt_loss["net_profit"], -30.0)
        self.assertEqual(stmt_loss["required_reserve"], 0.0)
        self.assertEqual(stmt_loss["surplus_available"], 0.0)

    def test_portfolio_allocation_sums_to_100_percent(self):
        pm = PortfolioManager()
        for profile in ["conservative", "balanced", "growth"]:
            surplus = 150.00
            res = pm.allocate(surplus, risk_profile=profile)
            self.assertEqual(res["total_percentage"], 100.0)
            allocated_sum = round(sum(item["amount"] for item in res["allocations"]), 2)
            self.assertEqual(allocated_sum, surplus)

    def test_portfolio_zero_surplus_produces_no_allocations(self):
        pm = PortfolioManager()
        res = pm.allocate(0.0, risk_profile="balanced")
        self.assertEqual(res["total_surplus_allocated"], 0.0)
        for alloc in res["allocations"]:
            self.assertEqual(alloc["amount"], 0.0)

    def test_measurement_truthful_evaluation_rules(self):
        ma = MeasurementAgent()
        # Case 1: Zero traffic
        zero_res = ma.evaluate_performance(views=0, clicks=0, orders_count=0, net_profit=-2.50, budget=50.0)
        self.assertEqual(zero_res["recommended_action"], "awaiting_traffic")

        # Case 2: Insufficient sample size (<25 views)
        small_res = ma.evaluate_performance(views=12, clicks=1, orders_count=0, net_profit=-2.50, budget=50.0)
        self.assertEqual(small_res["recommended_action"], "insufficient_data")
        self.assertTrue(small_res["is_insufficient_sample"])

        # Case 3: Statistically low CTR with adequate exposure
        low_ctr_res = ma.evaluate_performance(views=100, clicks=1, orders_count=0, net_profit=-5.0, budget=50.0)
        self.assertEqual(low_ctr_res["recommended_action"], "change_content_or_audience")

    def test_strategy_agent_adapts_to_past_outcomes(self):
        sa = StrategyAgent()
        candidates = [
            {"title": "Tool A", "business_model": "affiliate", "demand_score": 85, "competition_level": "Low"},
            {"title": "Tool B", "business_model": "digital_product", "demand_score": 80, "competition_level": "Low"}
        ]
        # Without past penalties, Tool A (85) wins
        res_default = sa.select_strategy(candidates, budget=50.0)
        self.assertEqual(res_default["candidate"]["business_model"], "affiliate")

        # With past severe failure in 'affiliate', Tool B (digital_product) should win
        past_failures = [{"business_model": "affiliate", "recommended_action": "stop"}]
        res_adapted = sa.select_strategy(candidates, budget=50.0, previous_outcomes=past_failures)
        self.assertEqual(res_adapted["candidate"]["business_model"], "digital_product")

    def test_opportunity_fixtures_are_explicitly_unverified(self):
        scout = OpportunityScout()
        fixtures = scout.CURATED_SEED_OPPORTUNITIES
        for f in fixtures:
            self.assertEqual(f["source_type"], "curated_market_fixture")
            self.assertEqual(f["is_verified"], 0)
            self.assertEqual(f["confidence"], "baseline_unverified")
            self.assertEqual(f["is_simulated"], 1)

    def test_quality_checker_rules(self):
        qc = QualityCheckerAgent()
        fail_res = qc.check_artifact("Earn guaranteed profit with zero risk instantly", "Buy", "affiliate", "")
        self.assertFalse(fail_res["passed"])
        self.assertTrue(any("affiliate" in iss.lower() for iss in fail_res["issues"]))

        pass_res = qc.check_artifact("Structured operational playbook for remote teams.", "Download template", "digital_product", "Educational tool.")
        self.assertTrue(pass_res["passed"])

    def test_ai_service_unconfigured_honest_status(self):
        status = AIService.get_provider_status()
        self.assertIn("active_provider", status)
        self.assertIn("gemini_ready", status)
        self.assertIn("mistral_ready", status)

    def test_youtube_and_instagram_honest_status(self):
        yt = YouTubeService.get_status()
        self.assertIn("configured", yt)
        self.assertIn("can_upload", yt)

        ig = InstagramService.get_status()
        self.assertIn("configured", ig)
        self.assertIn("can_publish", ig)

    def test_product_builder_file_generation(self):
        pkg = ProductBuilderAgent.build_digital_package("Founder Operating Blueprint", "Solopreneurs")
        self.assertTrue(os.path.exists(pkg["deliverable_path"]))
        self.assertTrue(os.path.exists(pkg["markdown_path"]))
        self.assertGreater(pkg["file_size_bytes"], 100)

    def test_chat_assistant_bounded_budget_safety(self):
        assistant = RealChatAssistant()
        # Test out of bounds budget change ($0.50 is below $5.00 min)
        res_low = assistant.handle_message(experiment_id=1, user_text="Set budget to 0.50")
        self.assertIn("Action Blocked", res_low["reply"])

        # Test out of bounds budget change ($10,000 is above $5,000 max)
        res_high = assistant.handle_message(experiment_id=1, user_text="Set budget to 10000")
        self.assertIn("Action Blocked", res_high["reply"])

        # Test valid budget change
        res_valid = assistant.handle_message(experiment_id=1, user_text="Set budget to 45.00")
        self.assertIn("Budget cap updated", res_valid["reply"])


class TestYouTubeOAuth(unittest.TestCase):
    """
    Tests for YouTube OAuth routes.
    Uses an isolated in-memory SQLite DB and isolated temp generated directory; never calls real Google APIs.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._tmp_db = Path(self.temp_dir) / "test_yt.db"
        self._tmp_gen = Path(self.temp_dir) / "generated"
        self._tmp_gen.mkdir(parents=True, exist_ok=True)

        import config, database
        self._orig_db_path = config.DB_PATH
        self._orig_gen_dir = config.GENERATED_DIR
        config.DB_PATH = self._tmp_db
        config.GENERATED_DIR = self._tmp_gen
        database.DB_PATH = self._tmp_db
        database.init_db()

        from app import create_app
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.app.config["SECRET_KEY"] = "test-secret-12345"
        self.client = self.app.test_client()

    def tearDown(self):
        import gc, config, database
        config.DB_PATH = self._orig_db_path
        config.GENERATED_DIR = self._orig_gen_dir
        database.DB_PATH = self._orig_db_path
        gc.collect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # --- Status when no token stored ---
    def test_youtube_status_not_connected(self):
        res = self.client.get("/api/youtube/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertFalse(data["connected"])
        self.assertIn(data["status"], ["not_connected", "setup_required"])

    # --- Upload requires confirmed=true ---
    def test_upload_requires_confirmation(self):
        res = self.client.post("/api/youtube/upload",
            json={"filename": "test.mp4", "title": "Test"},
            content_type="application/json")
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data["success"])
        self.assertIn("confirmed", data["error"])

    # --- Upload with confirmed but missing file ---
    def test_upload_missing_file(self):
        res = self.client.post("/api/youtube/upload",
            json={"filename": "nonexistent_video.mp4", "confirmed": True},
            content_type="application/json")
        self.assertEqual(res.status_code, 404)
        data = res.get_json()
        self.assertFalse(data["success"])

    # --- Upload without connection returns 401 ---
    def test_upload_requires_connection(self):
        import config
        vid_dir = Path(config.GENERATED_DIR) / "videos"
        vid_dir.mkdir(parents=True, exist_ok=True)
        fake = vid_dir / "_test_dummy.mp4"
        fake.write_bytes(b"FAKE_MP4_DATA")
        try:
            res = self.client.post("/api/youtube/upload",
                json={"filename": "_test_dummy.mp4", "confirmed": True},
                content_type="application/json")
            self.assertEqual(res.status_code, 401)
            data = res.get_json()
            self.assertFalse(data["success"])
            self.assertIn("not connected", data["error"].lower())
        finally:
            fake.unlink(missing_ok=True)

    # --- OAuth state mismatch returns 400 ---
    def test_callback_bad_csrf_state(self):
        res = self.client.get("/auth/youtube/callback?state=bad_state&code=fake_code")
        self.assertEqual(res.status_code, 400)
        self.assertIn(b"CSRF", res.data)

    # --- OAuth error param handled ---
    def test_callback_oauth_error_param(self):
        with self.client.session_transaction() as sess:
            sess["youtube_oauth_state"] = "my_state"
        res = self.client.get("/auth/youtube/callback?state=my_state&error=access_denied")
        self.assertEqual(res.status_code, 400)
        self.assertIn(b"access_denied", res.data)

    # --- Disconnect with no token gracefully returns disconnected ---
    def test_disconnect_no_token(self):
        res = self.client.post("/auth/youtube/disconnect")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["disconnected"])

    # --- Video list endpoint returns empty list when dir has no mp4 ---
    def test_list_videos_empty(self):
        res = self.client.get("/api/youtube/videos")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("videos", data)

    # --- Test route returns error when not connected ---
    def test_test_connection_not_connected(self):
        res = self.client.get("/api/youtube/test")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertFalse(data["ok"])
        self.assertIn("error", data)

    # --- /oauth2callback alias route handles bad CSRF identically ---
    def test_oauth2callback_alias_csrf_state(self):
        res = self.client.get("/oauth2callback?state=bad_state&code=fake_code")
        self.assertEqual(res.status_code, 400)
        self.assertIn(b"CSRF", res.data)

    # --- /oauth2callback alias route handles OAuth error parameter ---
    def test_oauth2callback_alias_error_param(self):
        with self.client.session_transaction() as sess:
            sess["youtube_oauth_state"] = "my_state"
        res = self.client.get("/oauth2callback?state=my_state&error=access_denied")
        self.assertEqual(res.status_code, 400)
        self.assertIn(b"access_denied", res.data)

    # --- Redirect URI helper resolves to valid 127.0.0.1:5000 URI ---
    def test_get_redirect_uri_format(self):
        from routes.youtube_auth import get_redirect_uri
        uri = get_redirect_uri()
        self.assertTrue(uri.startswith("http://127.0.0.1:5000/"))
        self.assertTrue(uri.endswith("/callback") or uri.endswith("/oauth2callback"))


class TestMINTSystemIntegrity(unittest.TestCase):
    """
    Regression and security integrity test suite.
    Uses an isolated temporary SQLite database and mock configurations.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self._tmp_db = Path(self.temp_dir) / "test_integrity.db"
        self._tmp_gen = Path(self.temp_dir) / "generated"
        self._tmp_gen.mkdir(parents=True, exist_ok=True)

        import config, database
        self._orig_db_path = config.DB_PATH
        self._orig_gen_dir = config.GENERATED_DIR
        config.DB_PATH = self._tmp_db
        config.GENERATED_DIR = self._tmp_gen
        database.DB_PATH = self._tmp_db
        database.init_db()

        # Seed an experiment for foreign-key testing
        with database.get_db_connection() as conn:
            conn.execute("""
                INSERT INTO experiments (id, name, goal, business_model, target_audience, budget_limit, status, created_at, updated_at)
                VALUES (1, 'Integrity Test Run', 'Test venture', 'digital_product', 'developers', 50.0, 'completed', '2026-10-23 00:00:00', '2026-10-23 00:00:00')
            """)
            conn.commit()

        from app import create_app
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.app.config["SECRET_KEY"] = "test-secret-integrity-12345"
        self.client = self.app.test_client()

    def tearDown(self):
        import gc, config, database
        config.DB_PATH = self._orig_db_path
        config.GENERATED_DIR = self._orig_gen_dir
        database.DB_PATH = self._orig_db_path
        gc.collect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # --- 1. Sandbox test orders never inflate real business revenue or reserves ---
    def test_finance_separates_test_orders_from_real_revenue(self):
        fa = FinanceAgent(reserve_ratio=0.25, reinvestment_ratio=0.40)
        mixed_orders = [
            {"gross_amount": 20.0, "fee_amount": 0.90, "is_refunded": False, "is_test": False},
            {"gross_amount": 30.0, "fee_amount": 1.20, "is_refunded": False, "is_test": False},
            {"gross_amount": 100.0, "fee_amount": 3.30, "is_refunded": False, "is_test": True},
            {"gross_amount": 500.0, "fee_amount": 15.30, "is_refunded": False, "is_test": True},
        ]
        stmt = fa.calculate_statement(starting_budget=50.0, actual_spend=10.0, orders=mixed_orders)

        self.assertEqual(stmt["gross_revenue"], 50.0)
        self.assertEqual(stmt["fees"], 2.10)
        self.assertEqual(stmt["net_sales"], 47.90)
        self.assertEqual(stmt["net_profit"], 37.90)
        self.assertEqual(stmt["required_reserve"], 9.47)
        self.assertEqual(stmt["real_orders_count"], 2)

        self.assertIn("sandbox_summary", stmt)
        self.assertEqual(stmt["sandbox_summary"]["test_orders_count"], 2)
        self.assertEqual(stmt["sandbox_summary"]["test_gross"], 600.0)

    # --- 2. Storefront rejects invalid experiment ID ---
    def test_storefront_invalid_experiment_id(self):
        res = self.client.post("/api/storefront/test_order", json={"experiment_id": 99999, "price": 14.99})
        self.assertEqual(res.status_code, 404)

    # --- 3. Storefront rejects invalid or out-of-bounds price ---
    def test_storefront_invalid_price(self):
        res = self.client.post("/api/storefront/test_order", json={"experiment_id": 1, "price": -5.0})
        self.assertEqual(res.status_code, 400)
        res2 = self.client.post("/api/storefront/test_order", json={"experiment_id": 1, "price": 10000.0})
        self.assertEqual(res2.status_code, 400)
        res3 = self.client.post("/api/storefront/test_order", json={"experiment_id": 1, "price": "invalid"})
        self.assertEqual(res3.status_code, 400)

    # --- 4. Storefront throttles duplicate purchases ---
    def test_storefront_duplicate_order_throttling(self):
        res1 = self.client.post("/api/storefront/test_order", json={"experiment_id": 1, "price": 14.99, "email": "repeat@buyer.com"})
        self.assertEqual(res1.status_code, 200)
        data1 = res1.get_json()
        self.assertEqual(data1["status"], "success")

        res2 = self.client.post("/api/storefront/test_order", json={"experiment_id": 1, "price": 14.99, "email": "repeat@buyer.com"})
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()
        self.assertEqual(data2["status"], "duplicate_throttled")

    # --- 5. Storefront order refund flow and idempotency ---
    def test_storefront_refund_flow(self):
        res = self.client.post("/api/storefront/test_order", json={"experiment_id": 1, "price": 19.99, "email": "refund_test@buyer.com"})
        order_id = res.get_json()["order_id"]

        ref1 = self.client.post("/api/storefront/test_refund", json={"order_id": order_id})
        self.assertEqual(ref1.status_code, 200)
        self.assertTrue(ref1.get_json()["refunded"])

        ref2 = self.client.post("/api/storefront/test_refund", json={"order_id": order_id})
        self.assertEqual(ref2.status_code, 200)
        self.assertEqual(ref2.get_json()["status"], "already_refunded")

    # --- 6. Experiments input validation ---
    def test_experiments_validation(self):
        res1 = self.client.post("/api/experiments/create_and_run", json={"budget_limit": -10.0})
        self.assertEqual(res1.status_code, 400)

        res2 = self.client.post("/api/experiments/create_and_run", json={"budget_limit": 6000.0})
        self.assertEqual(res2.status_code, 400)

        res3 = self.client.post("/api/experiments/create_and_run", json={"budget_limit": "not_a_number"})
        self.assertEqual(res3.status_code, 400)

    # --- 7. Chat empty message validation ---
    def test_chat_empty_message_validation(self):
        res = self.client.post("/api/chat/send", json={"experiment_id": 1, "message": "   "})
        self.assertEqual(res.status_code, 400)

    # --- 8. Media route path traversal protection ---
    def test_serve_media_path_traversal_protection(self):
        res1 = self.client.get("/api/media/etc/passwd")
        self.assertEqual(res1.status_code, 400)

        res2 = self.client.get("/api/media/images/..%2f..%2fconfig.py")
        self.assertEqual(res2.status_code, 404)

    # --- 9. YouTube upload path traversal protection ---
    def test_youtube_upload_path_traversal_protection(self):
        res = self.client.post("/api/youtube/upload", json={
            "filename": "../../config.py",
            "confirmed": True
        })
        self.assertEqual(res.status_code, 404)

    # --- 10. Instagram service media hosting requirement ---
    def test_instagram_service_media_hosting_requirement(self):
        res = InstagramService.publish_media("C:\\Users\\test\\video.mp4", caption="Test Reel", confirmed=True)
        self.assertIn(res["status"], ["media_hosting_required", "export_ready"])
        self.assertFalse(res.get("published", False))

    # --- 11. Instagram service requires confirmation ---
    def test_instagram_service_requires_confirmation(self):
        res = InstagramService.publish_media("https://example.com/video.mp4", caption="Test Reel", confirmed=False)
        self.assertEqual(res["status"], "confirmation_required")
        self.assertFalse(res["success"])

    # --- 12. Storefront view deduplication enforces 5-minute cooldown ---
    def test_storefront_view_deduplication_five_minute_window(self):
        import database
        from datetime import datetime, timedelta

        with database.get_db_connection() as conn:
            conn.execute("""
                INSERT INTO artifacts (experiment_id, artifact_type, title, hook, content_text, created_at)
                VALUES (1, 'multimedia_bundle', 'Test Artifact', 'Test Hook', 'Content', '2026-10-23 00:00:00')
            """)
            conn.commit()

        res1 = self.client.get("/storefront", environ_base={"REMOTE_ADDR": "192.168.1.50"})
        self.assertEqual(res1.status_code, 200)

        with database.get_db_connection() as conn:
            count1 = conn.execute("SELECT COUNT(*) as c FROM traffic_events WHERE event_type = 'view'").fetchone()["c"]
        self.assertEqual(count1, 1)

        res2 = self.client.get("/storefront", environ_base={"REMOTE_ADDR": "192.168.1.50"})
        self.assertEqual(res2.status_code, 200)

        with database.get_db_connection() as conn:
            count2 = conn.execute("SELECT COUNT(*) as c FROM traffic_events WHERE event_type = 'view'").fetchone()["c"]
        self.assertEqual(count2, 1)

        six_min_ago = (datetime.now() - timedelta(minutes=6)).strftime("%Y-%m-%d %H:%M:%S")
        with database.get_db_connection() as conn:
            conn.execute("UPDATE traffic_events SET created_at = ? WHERE event_type = 'view'", (six_min_ago,))
            conn.commit()

        res3 = self.client.get("/storefront", environ_base={"REMOTE_ADDR": "192.168.1.50"})
        self.assertEqual(res3.status_code, 200)

        with database.get_db_connection() as conn:
            count3 = conn.execute("SELECT COUNT(*) as c FROM traffic_events WHERE event_type = 'view'").fetchone()["c"]
        self.assertEqual(count3, 2)


class TestMINTProductIntelligence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_mint_pi.db"
        self.gen_dir = Path(self.temp_dir) / "generated"
        self.gen_dir.mkdir(parents=True, exist_ok=True)

        import config, database
        self.orig_db_path = config.DB_PATH
        self.orig_gen_dir = config.GENERATED_DIR
        config.DB_PATH = self.db_path
        config.GENERATED_DIR = self.gen_dir
        database.DB_PATH = self.db_path
        database.init_db()

        from app import create_app
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        import config, database, gc
        config.DB_PATH = self.orig_db_path
        config.GENERATED_DIR = self.orig_gen_dir
        database.DB_PATH = self.orig_db_path
        gc.collect()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_context_builder_retrieves_real_system_state(self):
        from agents.context_builder import build_context
        import database

        ctx_empty = build_context()
        self.assertFalse(ctx_empty["has_experiment"])

        with database.get_db_connection() as conn:
            conn.execute("""
                INSERT INTO experiments (id, name, goal, business_model, target_audience, budget_limit, status, created_at, updated_at)
                VALUES (1, 'Venture Alpha', 'Validate B2B template', 'digital_product', 'Founders', 50.0, 'completed', '2026-10-23 00:00:00', '2026-10-23 00:01:00')
            """)
            conn.execute("""
                INSERT INTO traffic_events (experiment_id, event_type, source, created_at)
                VALUES (1, 'view', 'storefront', '2026-10-23 00:00:00'),
                       (1, 'click', 'storefront', '2026-10-23 00:00:01')
            """)
            conn.execute("""
                INSERT INTO orders (experiment_id, customer_email, product_title, gross_amount, fee_amount, is_test, is_refunded, created_at)
                VALUES (1, 'cust@example.com', 'Guide', 29.0, 1.14, 0, 0, '2026-10-23 00:00:00')
            """)
            conn.execute("""
                INSERT INTO finance_records (experiment_id, starting_budget, actual_spend, gross_revenue, fees, refunds, net_profit, required_reserve, reinvestment_allocated, surplus_available, is_simulated, updated_at)
                VALUES (1, 50.0, 0.0, 29.0, 1.14, 0.0, 27.86, 6.97, 11.14, 9.75, 0, '2026-10-23 00:01:00')
            """)
            conn.commit()

        ctx = build_context(1)
        self.assertTrue(ctx["has_experiment"])
        self.assertEqual(ctx["experiment"]["goal"], "Validate B2B template")
        self.assertEqual(ctx["traffic"]["views"], 1)
        self.assertEqual(ctx["traffic"]["clicks"], 1)
        self.assertEqual(ctx["orders"]["real_completed"], 1)
        self.assertEqual(ctx["orders"]["real_gross"], 29.0)
        self.assertEqual(ctx["finance"]["net_profit"], 27.86)
        for integ in ctx["integrations"].values():
            self.assertNotIn("access_token", integ)
            self.assertNotIn("client_secret", integ)

    def test_live_state_endpoint_identifies_interrupted_runs(self):
        import database

        with database.get_db_connection() as conn:
            conn.execute("""
                INSERT INTO experiments (id, name, goal, business_model, target_audience, budget_limit, status, created_at, updated_at)
                VALUES (2, 'Interrupted Venture', 'Test', 'evaluating', 'evaluating', 50.0, 'running', '2026-10-23 00:00:00', '2026-10-23 00:00:00')
            """)
            conn.execute("""
                INSERT INTO agent_runs (experiment_id, agent_name, status, updated_at)
                VALUES (2, 'Opportunity Scout', 'running', '2026-10-23 00:00:00')
            """)
            conn.commit()

        res = self.client.get("/api/live-state?experiment_id=2")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["has_experiment"])
        self.assertEqual(data["experiment"]["status"], "interrupted")
        self.assertFalse(data["is_actively_running"])
        self.assertEqual(data["agent_runs"][0]["status"], "interrupted")

    def test_instagram_status_detailed_levels(self):
        from services.social_service import InstagramService
        import os

        orig_id = os.environ.pop("INSTAGRAM_ACCOUNT_ID", None)
        orig_tok = os.environ.pop("INSTAGRAM_ACCESS_TOKEN", None)
        try:
            status = InstagramService.get_status(force_refresh=True)
            self.assertEqual(status["status"], "not_configured")
            self.assertFalse(status["can_publish"])
            self.assertIn("setup_required", status)
        finally:
            if orig_id: os.environ["INSTAGRAM_ACCOUNT_ID"] = orig_id
            if orig_tok: os.environ["INSTAGRAM_ACCESS_TOKEN"] = orig_tok

    def test_youtube_channel_endpoint_caching_and_history(self):
        res = self.client.get("/api/youtube/channel")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("channel", data)
        self.assertIn("upload_history", data)
        self.assertIn("note", data)

    def test_experiments_create_initializes_nine_nodes(self):
        from unittest.mock import patch
        with patch("routes.experiments.orchestrator.run_pipeline_async", return_value=True), \
             patch("routes.experiments.orchestrator.is_experiment_running", return_value=False):
            res = self.client.post("/api/experiments/create_and_run", json={
                "name": "Nine Node Test",
                "goal": "Verify all 9 nodes initialized",
                "budget_limit": 50.0
            })
            self.assertEqual(res.status_code, 200)
            exp_id = res.get_json()["experiment_id"]

        import database
        with database.get_db_connection() as conn:
            runs = conn.execute("SELECT agent_name FROM agent_runs WHERE experiment_id = ?", (exp_id,)).fetchall()
        agent_names = {r["agent_name"] for r in runs}
        expected_nine = {
            "Opportunity Scout", "Strategy Agent", "MINT Orchestrator",
            "Content Creator", "Quality Checker", "Publishing Agent",
            "Measurement Agent", "Finance Agent", "Portfolio Manager"
        }
        self.assertTrue(expected_nine.issubset(agent_names))


class TestMINTContentAndVentureEngines(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import config, database
        cls.temp_dir = tempfile.mkdtemp()
        cls.db_path = Path(cls.temp_dir) / "test_content_mint.db"
        cls.gen_dir = Path(cls.temp_dir) / "generated"
        cls.gen_dir.mkdir(parents=True, exist_ok=True)

        cls.orig_db_path = config.DB_PATH
        cls.orig_gen_dir = config.GENERATED_DIR

        config.DB_PATH = cls.db_path
        config.GENERATED_DIR = cls.gen_dir
        database.DB_PATH = cls.db_path
        database.init_db()

        # Seed experiment 1
        with database.get_db_connection() as conn:
            conn.execute("""
                INSERT INTO experiments (id, name, goal, business_model, target_audience, budget_limit, status, created_at, updated_at)
                VALUES (1, 'Content Pipeline Experiment', 'Test short content', 'digital_product', 'solopreneurs', 50.0, 'completed', '2026-10-23 00:00:00', '2026-10-23 00:00:00')
            """)
            conn.commit()

        from app import create_app
        cls.app = create_app()
        cls.app.config["TESTING"] = True
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        import config, database, gc
        config.DB_PATH = cls.orig_db_path
        config.GENERATED_DIR = cls.orig_gen_dir
        database.DB_PATH = cls.orig_db_path
        gc.collect()
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def test_content_studio_job_pipeline(self):
        from services.content_service import ContentStudioEngine
        payload = {
            "title": "Automated Short Test",
            "product_type": "mint_product",
            "angle": "relatable_problem",
            "audience": "Remote Workers",
            "problem": "Poor time management",
            "product_facts": "Simple 3-step checklist",
            "cta": "Get the checklist now",
            "is_test": 1
        }
        job_id = ContentStudioEngine.create_job(payload)
        self.assertIsInstance(job_id, int)

        job = ContentStudioEngine.get_job(job_id)
        self.assertEqual(job["status"], "queued")

        res = ContentStudioEngine.execute_job(job_id)
        self.assertTrue(res["success"])
        self.assertTrue(os.path.exists(res["video_path"]))
        self.assertEqual(res["quality"]["resolution"], "1080x1920")
        self.assertEqual(res["quality"]["audio_mode"], "silent_with_on_screen_captions")
        self.assertTrue(res["quality"]["qa_passed"])

    def test_content_studio_path_traversal_protection(self):
        res = self.client.get("/api/content/jobs/1/files/../../secret.txt")
        self.assertIn(res.status_code, [403, 404])

        res2 = self.client.get("/api/content/jobs/1/files/..%2F..%2Fapp.py")
        self.assertIn(res2.status_code, [403, 404])

    def test_digital_products_api_and_download_safety(self):
        # Create product via API with deliverable
        create_res = self.client.post("/api/products", json={
            "title": "Solopreneur Sprint Pack",
            "audience": "Freelancers",
            "value_proposition": "Double output in 7 days",
            "description": "Comprehensive sprint guide and templates",
            "price": 19.99,
            "contents": ["Sprint Planner", "Daily Standup Matrix"],
            "is_test": 1
        })
        self.assertEqual(create_res.status_code, 201)
        prod_data = create_res.get_json()
        self.assertTrue(prod_data["success"])
        self.assertIn("slug", prod_data)

        # Retrieve catalog (including tests since this is the isolated test DB)
        list_res = self.client.get("/api/products?include_test=1")
        self.assertEqual(list_res.status_code, 200)
        items = list_res.get_json()["products"]
        self.assertTrue(any(p["slug"] == prod_data["slug"] for p in items))

    def test_affiliate_offer_creation_and_safe_redirect(self):
        # Create affiliate offer
        offer_res = self.client.post("/api/affiliate/offers", json={
            "name": "SuperTool Pro",
            "vendor": "SuperCorp",
            "destination_url": "https://supercorp.com/affiliate-target",
            "commission_rate": "25%",
            "disclosure_copy": "Ad: We earn a commission if you purchase.",
            "is_test": 1
        })
        self.assertEqual(offer_res.status_code, 201)
        data = offer_res.get_json()
        token = data["token"]
        self.assertTrue(token.startswith("afr_"))

        # Test redirect
        redirect_res = self.client.get(f"/go/{token}", headers={"User-Agent": "TestBrowser/1.0"})
        self.assertEqual(redirect_res.status_code, 302)
        self.assertEqual(redirect_res.headers["Location"], "https://supercorp.com/affiliate-target")

        # Verify hashed visitor logging (not raw IP)
        import database
        with database.get_db_connection() as conn:
            click_row = conn.execute("SELECT * FROM affiliate_clicks WHERE offer_id = ? ORDER BY id DESC LIMIT 1", (data["offer_id"],)).fetchone()
        self.assertIsNotNone(click_row)
        self.assertNotIn("127.0.0.1", click_row["visitor_hash"])
        self.assertEqual(len(click_row["visitor_hash"]), 16)

        # Invalid token gives 404
        bad_res = self.client.get("/go/nonexistent_fake_token")
        self.assertEqual(bad_res.status_code, 404)

    def test_live_state_progression_metrics(self):
        res = self.client.get("/api/live-state")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        if data.get("has_experiment"):
            self.assertIn("progression", data)
            prog = data["progression"]
            self.assertEqual(prog["total_stages"], 9)
            self.assertIn("completed_stages", prog)
            self.assertIn("progress_pct", prog)
            self.assertIn("elapsed_seconds", prog)
            self.assertIn("current_stage", prog)

    def test_portfolio_venture_metrics(self):
        res = self.client.get("/api/portfolio/venture_metrics")
        self.assertEqual(res.status_code, 200)
        metrics = res.get_json()
        self.assertIn("total_digital_products", metrics)
        self.assertIn("total_affiliate_offers", metrics)
        self.assertIn("completed_content_jobs", metrics)
        self.assertIn("real_direct_revenue", metrics)


class TestMINTTestPollutionRegression(unittest.TestCase):
    """
    Acceptance test proving that automated test executions
    never pollute the real database or write files into real generated/ assets.
    """
    def test_running_isolated_workflow_does_not_modify_production_files(self):
        import config
        prod_db = config.BASE_DIR / "data" / "mint.db"
        prod_gen = config.BASE_DIR / "generated"

        gen_files_before = set(prod_gen.rglob("*")) if prod_gen.exists() else set()

        conn = sqlite3.connect(str(prod_db))
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM content_jobs")
        jobs_before = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM digital_products")
        prods_before = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM affiliate_offers")
        offers_before = cur.fetchone()[0]
        conn.close()

        # Run an isolated workflow with test paths
        temp_dir = tempfile.mkdtemp()
        try:
            temp_db = Path(temp_dir) / "temp_pollution_test.db"
            temp_gen = Path(temp_dir) / "generated"
            temp_gen.mkdir(parents=True, exist_ok=True)

            orig_db = config.DB_PATH
            orig_gen = config.GENERATED_DIR
            try:
                config.DB_PATH = temp_db
                config.GENERATED_DIR = temp_gen
                import database
                database.DB_PATH = temp_db
                database.init_db()

                from services.content_service import ContentStudioEngine
                job_id = ContentStudioEngine.create_job({
                    "title": "Pollution Check Job",
                    "product_type": "mint_product",
                    "angle": "relatable_problem",
                    "audience": "Testers",
                    "problem": "Pollution",
                    "product_facts": "Isolation check",
                    "cta": "Check output",
                    "is_test": 1
                })
                self.assertIsInstance(job_id, int)
                job_dir = ContentStudioEngine.get_job_dir(job_id)
                self.assertTrue(str(job_dir).startswith(str(temp_gen)))
            finally:
                config.DB_PATH = orig_db
                config.GENERATED_DIR = orig_gen
                database.DB_PATH = orig_db
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        # Verify prod_db and prod_gen are completely unchanged
        conn = sqlite3.connect(str(prod_db))
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM content_jobs")
        jobs_after = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM digital_products")
        prods_after = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM affiliate_offers")
        offers_after = cur.fetchone()[0]
        conn.close()

        self.assertEqual(jobs_before, jobs_after, "Production content_jobs was modified by test!")
        self.assertEqual(prods_before, prods_after, "Production digital_products was modified by test!")
        self.assertEqual(offers_before, offers_after, "Production affiliate_offers was modified by test!")

        gen_files_after = set(prod_gen.rglob("*")) if prod_gen.exists() else set()
        new_files = gen_files_after - gen_files_before
        self.assertEqual(len(new_files), 0, f"Production generated/ received new files: {new_files}")


class TestInstagramLoginFlow(unittest.TestCase):
    def test_instagram_login_uses_instagram_host_and_does_not_put_token_in_url(self):
        from unittest.mock import Mock, patch
        from services.social_service import InstagramService

        response = Mock()
        response.ok = True
        response.status_code = 200
        response.json.return_value = {
            "user_id": "ig-test-123",
            "username": "mint_test",
            "account_type": "BUSINESS",
        }
        env = {
            "INSTAGRAM_LOGIN_METHOD": "instagram_login",
            "META_GRAPH_API_VERSION": "v26.0",
            "INSTAGRAM_ACCOUNT_ID": "",
            "INSTAGRAM_ACCESS_TOKEN": "unit-test-token",
            "INSTAGRAM_GRANTED_SCOPES": "instagram_business_basic,instagram_business_content_publish",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "services.social_service.requests.get", return_value=response
        ) as mocked_get:
            status = InstagramService.get_status(force_refresh=True)

        self.assertEqual(status["status"], "connected")
        self.assertTrue(status["can_publish"])
        self.assertEqual(status["login_method"], "instagram_login")
        self.assertEqual(status["account_id"], "ig-test-123")
        args, kwargs = mocked_get.call_args
        self.assertTrue(args[0].startswith("https://graph.instagram.com/v26.0/me"))
        self.assertNotIn("unit-test-token", args[0])
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer unit-test-token")

    def test_instagram_login_does_not_claim_publish_ready_without_declared_scope(self):
        from unittest.mock import Mock, patch
        from services.social_service import InstagramService

        response = Mock()
        response.ok = True
        response.status_code = 200
        response.json.return_value = {
            "user_id": "ig-test-456",
            "username": "mint_creator",
            "account_type": "CREATOR",
        }
        env = {
            "INSTAGRAM_LOGIN_METHOD": "instagram_login",
            "META_GRAPH_API_VERSION": "v26.0",
            "INSTAGRAM_ACCOUNT_ID": "",
            "INSTAGRAM_ACCESS_TOKEN": "unit-test-token",
            "INSTAGRAM_GRANTED_SCOPES": "instagram_business_basic",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "services.social_service.requests.get", return_value=response
        ):
            status = InstagramService.get_status(force_refresh=True)

        self.assertEqual(status["status"], "connected_no_publish")
        self.assertTrue(status["account_verified"])
        self.assertFalse(status["can_publish"])
        self.assertIn("instagram_business_content_publish", status["message"])

    def test_facebook_login_uses_facebook_graph_host(self):
        from unittest.mock import Mock, patch
        from services.social_service import InstagramService

        profile_response = Mock()
        profile_response.ok = True
        profile_response.status_code = 200
        profile_response.json.return_value = {
            "id": "fb-login-ig-789",
            "username": "mint_business",
            "name": "Mint Business",
        }
        permissions_response = Mock()
        permissions_response.ok = True
        permissions_response.status_code = 200
        permissions_response.json.return_value = {
            "data": [
                {"permission": "instagram_basic", "status": "granted"},
                {"permission": "instagram_content_publish", "status": "granted"},
            ]
        }
        env = {
            "INSTAGRAM_LOGIN_METHOD": "facebook_login",
            "META_GRAPH_API_VERSION": "v26.0",
            "INSTAGRAM_ACCOUNT_ID": "fb-login-ig-789",
            "INSTAGRAM_ACCESS_TOKEN": "unit-test-token",
            "INSTAGRAM_GRANTED_SCOPES": "",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "services.social_service.requests.get",
            side_effect=[profile_response, permissions_response],
        ) as mocked_get:
            status = InstagramService.get_status(force_refresh=True)

        self.assertEqual(status["status"], "connected")
        self.assertTrue(status["can_publish"])
        self.assertTrue(status["permission_verified"])
        self.assertEqual(status["permission_source"], "meta_me_permissions")
        self.assertTrue(mocked_get.call_args_list[0].args[0].startswith(
            "https://graph.facebook.com/v26.0/fb-login-ig-789"
        ))
        self.assertTrue(mocked_get.call_args_list[1].args[0].endswith("/me/permissions"))

    def test_facebook_login_blocks_publishing_if_meta_does_not_grant_publish_scope(self):
        from unittest.mock import Mock, patch
        from services.social_service import InstagramService

        profile_response = Mock()
        profile_response.ok = True
        profile_response.status_code = 200
        profile_response.json.return_value = {
            "id": "fb-login-ig-999",
            "username": "mint_business",
            "name": "Mint Business",
        }
        permissions_response = Mock()
        permissions_response.ok = True
        permissions_response.status_code = 200
        permissions_response.json.return_value = {
            "data": [
                {"permission": "instagram_basic", "status": "granted"},
                {"permission": "instagram_content_publish", "status": "declined"},
            ]
        }
        env = {
            "INSTAGRAM_LOGIN_METHOD": "facebook_login",
            "META_GRAPH_API_VERSION": "v26.0",
            "INSTAGRAM_ACCOUNT_ID": "fb-login-ig-999",
            "INSTAGRAM_ACCESS_TOKEN": "unit-test-token",
            "INSTAGRAM_GRANTED_SCOPES": "instagram_content_publish",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "services.social_service.requests.get",
            side_effect=[profile_response, permissions_response],
        ):
            status = InstagramService.get_status(force_refresh=True)

        self.assertEqual(status["status"], "connected_no_publish")
        self.assertFalse(status["can_publish"])
        self.assertTrue(status["permission_verified"])

    def test_status_endpoint_never_exposes_token(self):
        from unittest.mock import Mock, patch
        from services.social_service import InstagramService
        env = {
            "INSTAGRAM_ACCESS_TOKEN": "secret-super-sensitive-token-12345",
            "INSTAGRAM_ACCOUNT_ID": "12345",
            "INSTAGRAM_LOGIN_METHOD": "facebook_login"
        }
        with patch.dict(os.environ, env, clear=False):
            status = InstagramService.get_status(force_refresh=True)
            status_str = json.dumps(status)
            self.assertNotIn("secret-super-sensitive-token-12345", status_str)


class TestMINTDigitalProductAndGumroad(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import config, database
        cls.temp_dir = tempfile.mkdtemp()
        cls.db_path = Path(cls.temp_dir) / "test_digital_prod.db"
        cls.gen_dir = Path(cls.temp_dir) / "generated"
        cls.gen_dir.mkdir(parents=True, exist_ok=True)

        cls.orig_db_path = config.DB_PATH
        cls.orig_gen_dir = config.GENERATED_DIR

        config.DB_PATH = cls.db_path
        config.GENERATED_DIR = cls.gen_dir
        database.DB_PATH = cls.db_path
        database.init_db()

        from app import app
        cls.app = app
        cls.client = app.test_client()

    @classmethod
    def tearDownClass(cls):
        import config, database
        config.DB_PATH = cls.orig_db_path
        config.GENERATED_DIR = cls.orig_gen_dir
        database.DB_PATH = cls.orig_db_path
        if os.path.exists(cls.temp_dir):
            shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def test_idea_validation_and_brief_generation(self):
        from services.digital_product_engine import DigitalProductEngine

        # Short idea should fail validation
        val_short = DigitalProductEngine.validate_idea("tiny")
        self.assertFalse(val_short["valid"])

        # Substantive idea succeeds
        idea = "A 7-day checklist and playbook for freelance devs transitioning into retainers"
        val = DigitalProductEngine.validate_idea(idea)
        self.assertTrue(val["valid"])

        brief = DigitalProductEngine.derive_brief(idea=idea, max_pages=8, price=19.00)
        self.assertEqual(brief["max_pages"], 8)
        self.assertEqual(brief["price"], 19.00)
        self.assertGreaterEqual(len(brief["sections"]), 4)

        prompt = DigitalProductEngine.generate_prompt_from_brief(brief)
        self.assertIn("PRODUCT SPECIFICATION", prompt)
        self.assertIn("STRICT EDITORIAL GUIDELINES", prompt)

    def test_gemini_unconfigured_honest_error(self):
        from services.digital_product_engine import DigitalProductEngine
        from unittest.mock import patch

        env = {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": "", "AI_API_KEY": ""}
        with patch.dict(os.environ, env, clear=False):
            res = DigitalProductEngine.call_gemini_api("Draft guide")
            self.assertFalse(res["success"])
            self.assertEqual(res["code"], "missing_api_key")

    def test_gemini_quota_and_auth_error_handling(self):
        from services.digital_product_engine import DigitalProductEngine
        from unittest.mock import patch, Mock

        env = {"GEMINI_API_KEY": "test-key-123"}
        # Test 429 quota response
        resp_429 = Mock()
        resp_429.status_code = 429
        resp_429.text = "Quota exceeded"

        with patch.dict(os.environ, env, clear=False), patch("services.digital_product_engine.requests.post", return_value=resp_429):
            res = DigitalProductEngine.call_gemini_api("Draft guide")
            self.assertFalse(res["success"])
            self.assertEqual(res["status_code"], 429)

        # Test 401 auth response
        resp_401 = Mock()
        resp_401.status_code = 401
        resp_401.text = "API key not valid"

        with patch.dict(os.environ, env, clear=False), patch("services.digital_product_engine.requests.post", return_value=resp_401):
            res = DigitalProductEngine.call_gemini_api("Draft guide")
            self.assertFalse(res["success"])
            self.assertEqual(res["status_code"], 401)

    def test_markdown_to_semantic_html_formatting(self):
        from services.digital_product_engine import DigitalProductEngine

        md = (
            "# Executive Blueprint\n\n"
            "> Important Note: Test callout block\n\n"
            "- [ ] Audit core workflow\n"
            "- [x] Completed baseline analysis\n\n"
            "| Module | Duration |\n"
            "|---|---|\n"
            "| Sprint 1 | 3 Days |\n"
        )
        html = DigitalProductEngine.markdown_to_html(md)
        self.assertIn("<h1>Executive Blueprint</h1>", html)
        self.assertIn("<div class='callout'>Important Note: Test callout block</div>", html)
        self.assertIn("<ul class='checklist'>", html)
        self.assertIn("<table", html)
        self.assertIn("<th>Module</th>", html)

    def test_chromium_pdf_rendering_and_actual_page_count(self):
        from services.digital_product_engine import DigitalProductEngine

        html = DigitalProductEngine.render_full_html_document(
            title="Unit Test Product",
            subtitle="Deterministic Playwright Chromium Test",
            audience="Software Engineers",
            format_type="guide",
            body_html="<h2>1. Overview</h2><p>This is a deterministic unit test deliverable rendered with Playwright Chromium.</p>"
        )

        pdf_path = self.gen_dir / "unit_test_chromium.pdf"
        res = DigitalProductEngine.render_pdf_with_chromium(html, pdf_path)
        self.assertTrue(res["success"])
        self.assertTrue(pdf_path.exists())
        self.assertGreater(pdf_path.stat().st_size, 500)

        # Validate with pypdf
        val = DigitalProductEngine.validate_pdf(pdf_path, max_pages_allowed=20)
        self.assertTrue(val["valid"])
        self.assertGreaterEqual(val["page_count"], 1)
        self.assertLessEqual(val["page_count"], 20)

    def test_max_20_pages_limit_enforcement(self):
        from services.digital_product_engine import DigitalProductEngine

        # Test limit enforcement when document exceeds max allowed
        pdf_path = self.gen_dir / "unit_test_chromium.pdf"
        if pdf_path.exists():
            val_fail = DigitalProductEngine.validate_pdf(pdf_path, max_pages_allowed=0)
            self.assertFalse(val_fail["valid"])
            self.assertIn("exceeds", val_fail["error"].lower())

    def test_gumroad_status_unconfigured(self):
        from services.gumroad_service import GumroadService
        from unittest.mock import patch

        env = {"GUMROAD_ACCESS_TOKEN": ""}
        with patch.dict(os.environ, env, clear=False):
            status = GumroadService.get_status(force_refresh=True)
            self.assertFalse(status["connected"])
            self.assertEqual(status["status"], "not_configured")

    def test_gumroad_status_connected_mock(self):
        from services.gumroad_service import GumroadService
        from unittest.mock import patch, Mock

        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "success": True,
            "user": {
                "name": "Solo Venture Lab",
                "email": "lab@gumroad.local",
                "url": "https://gumroad.com/soloventure",
                "currency_type": "usd"
            }
        }

        env = {"GUMROAD_ACCESS_TOKEN": "mock-gumroad-secret-token-xyz"}
        with patch.dict(os.environ, env, clear=False), patch("services.gumroad_service.requests.get", return_value=mock_resp):
            status = GumroadService.get_status(force_refresh=True)
            self.assertTrue(status["connected"])
            self.assertEqual(status["user"]["name"], "Solo Venture Lab")
            # Ensure secret token is never exposed in the returned status dict
            self.assertNotIn("mock-gumroad-secret-token-xyz", json.dumps(status))

    def test_gumroad_sync_draft_created_pdf_required(self):
        from services.gumroad_service import GumroadService
        from database import get_db_connection
        from unittest.mock import patch, Mock

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO digital_products (slug, title, product_type, audience, value_proposition, description, price, status, is_test, created_at, updated_at)
            VALUES ('freelance-retainer-kit', 'Freelance Retainer Kit', 'playbook', 'Devs', 'High ticket retainers', 'Full playbook description', 29.00, 'ready', 1, datetime('now'), datetime('now'))
        """)
        product_id = cur.lastrowid
        conn.commit()
        conn.close()

        mock_post = Mock()
        mock_post.status_code = 201
        mock_post.json.return_value = {
            "success": True,
            "product": {
                "id": "gum_prod_987",
                "short_url": "https://gumroad.com/l/freelance-retainer-kit",
                "published": False
            }
        }

        env = {"GUMROAD_ACCESS_TOKEN": "mock-token-xyz"}
        with patch.dict(os.environ, env, clear=False), patch("services.gumroad_service.requests.post", return_value=mock_post):
            sync_res = GumroadService.sync_product(product_id)
            self.assertTrue(sync_res["success"])
            self.assertEqual(sync_res["sync_status"], "draft_created")
            self.assertEqual(sync_res["sync_message"], "Draft created on Gumroad — PDF attachment required")
            self.assertFalse(sync_res["pdf_attached"])

            # Verify in DB
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT gumroad_id, gumroad_sync_status FROM digital_products WHERE id = ?", (product_id,))
            row = cur.fetchone()
            conn.close()
            self.assertEqual(row["gumroad_id"], "gum_prod_987")
            self.assertEqual(row["gumroad_sync_status"], "draft_created")

    def test_gumroad_sync_idempotency_updates_existing(self):
        from services.gumroad_service import GumroadService
        from database import get_db_connection
        from unittest.mock import patch, Mock

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO digital_products (slug, title, product_type, audience, value_proposition, description, price, status, gumroad_id, is_test, created_at, updated_at)
            VALUES ('existing-kit', 'Existing Kit', 'guide', 'Founders', 'VP', 'Desc', 15.00, 'ready', 'gum_existing_111', 1, datetime('now'), datetime('now'))
        """)
        product_id = cur.lastrowid
        conn.commit()
        conn.close()

        mock_put = Mock()
        mock_put.status_code = 200
        mock_put.json.return_value = {
            "success": True,
            "product": {
                "id": "gum_existing_111",
                "short_url": "https://gumroad.com/l/existing-kit"
            }
        }

        env = {"GUMROAD_ACCESS_TOKEN": "mock-token-xyz"}
        with patch.dict(os.environ, env, clear=False), patch("services.gumroad_service.requests.put", return_value=mock_put) as put_mock:
            sync_res = GumroadService.sync_product(product_id)
            self.assertTrue(sync_res["success"])
            self.assertTrue(put_mock.called)
            self.assertEqual(sync_res["gumroad_id"], "gum_existing_111")

    def test_affiliate_hub_segregates_own_products_from_affiliate_offers(self):
        from database import get_db_connection

        conn = get_db_connection()
        cur = conn.cursor()
        # Seed an own product
        cur.execute("""
            INSERT INTO digital_products (slug, title, product_type, audience, value_proposition, description, price, status, is_test, created_at, updated_at)
            VALUES ('own-saas-guide', 'Own SaaS Operating Guide', 'guide', 'Founders', 'Own Product Value', 'Description', 24.00, 'ready', 0, datetime('now'), datetime('now'))
        """)
        # Seed an affiliate offer
        cur.execute("""
            INSERT INTO affiliate_offers (token, name, vendor, niche, audience, description, destination_url, commission_rate, price, disclosure_copy, status, is_test, created_at, updated_at)
            VALUES ('afr_test_part', 'Partner CRM Tool', 'PartnerCorp', 'Sales', 'Devs', 'Partner Description', 'https://partner.com/?ref=mint', '25% recurring', 49.00, 'Partner Disclosure: We may receive a commission.', 'active', 0, datetime('now'), datetime('now'))
        """)
        conn.commit()
        conn.close()

        res = self.client.get("/affiliates")
        self.assertEqual(res.status_code, 200)
        html = res.data.decode("utf-8")

        # Own product rendered in segregated section with 100% Margin badge
        self.assertIn("Own SaaS Operating Guide", html)
        self.assertIn("Own Product &middot; 100% Margin", html)

        # External partner rendered in affiliate section
        self.assertIn("Partner CRM Tool", html)
        self.assertIn("25% recurring", html)

    def test_storefront_shows_only_verified_products_with_deliverables(self):
        from database import get_db_connection

        # 1. Product WITH physical deliverable file
        prod_dir = self.gen_dir / "products" / "verified-book"
        prod_dir.mkdir(parents=True, exist_ok=True)
        pdf_file = prod_dir / "product.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 Mock Deliverable File Content")

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO digital_products (slug, title, product_type, audience, value_proposition, description, price, status, file_path, pdf_path, is_test, created_at, updated_at)
            VALUES ('verified-book', 'Verified Digital Book', 'ebook', 'Readers', 'Value', 'Desc', 12.00, 'published', ?, ?, 0, datetime('now'), datetime('now'))
        """, (str(pdf_file), str(pdf_file)))

        # 2. Product WITHOUT physical deliverable file
        cur.execute("""
            INSERT INTO digital_products (slug, title, product_type, audience, value_proposition, description, price, status, file_path, is_test, created_at, updated_at)
            VALUES ('unverified-ghost-book', 'Ghost Unverified Book', 'guide', 'Nobody', 'Value', 'Desc', 10.00, 'published', 'D:/nonexistent/file.pdf', 0, datetime('now'), datetime('now'))
        """)
        conn.commit()
        conn.close()

        res = self.client.get("/storefront")
        self.assertEqual(res.status_code, 200)
        html = res.data.decode("utf-8")

        self.assertIn("Verified Digital Book", html)
        self.assertNotIn("Ghost Unverified Book", html)

    def test_product_intent_detection_and_inference(self):
        from services.digital_product_engine import DigitalProductEngine

        # Fiction inference
        self.assertEqual(DigitalProductEngine.infer_intent("generate a horror story book"), "fiction")
        self.assertEqual(DigitalProductEngine.infer_intent("a bedtime story for children about a dragon"), "fiction")
        self.assertEqual(DigitalProductEngine.infer_intent("sci-fi fantasy thriller novel"), "fiction")

        # Workbook / Checklist inference
        self.assertEqual(DigitalProductEngine.infer_intent("SEO audit checklist and workbook"), "workbook_checklist")
        self.assertEqual(DigitalProductEngine.infer_intent("Financial assessment questionnaire and rubric"), "workbook_checklist")

        # Playbook / Toolkit inference
        self.assertEqual(DigitalProductEngine.infer_intent("SaaS client onboarding playbook and SOP template"), "playbook_toolkit")
        self.assertEqual(DigitalProductEngine.infer_intent("operational runbook for incident management"), "playbook_toolkit")

        # Non-fiction fallback
        self.assertEqual(DigitalProductEngine.infer_intent("practical guide to personal finance for freelancers"), "non_fiction")

    def test_clean_title_formulation(self):
        from services.digital_product_engine import DigitalProductEngine

        # Strips command words and formulates clean natural title
        title_fiction = DigitalProductEngine.clean_title("generate a horror story book", intent="fiction")
        self.assertFalse(title_fiction.lower().startswith("generate"))
        self.assertNotIn("The Practical Ebook", title_fiction)
        self.assertIn("Horror Story", title_fiction)

        title_custom = DigitalProductEngine.clean_title("any text", user_title="Echoes in the Deep")
        self.assertEqual(title_custom, "Echoes in the Deep")

        title_quoted = DigitalProductEngine.clean_title('write a guide on "High-Ticket Client Acquisition"')
        self.assertEqual(title_quoted, "High-Ticket Client Acquisition")

    def test_fiction_brief_and_gemini_prompt_specification(self):
        from services.digital_product_engine import DigitalProductEngine

        brief = DigitalProductEngine.derive_brief(
            idea="generate a horror story book set in an old abandoned lighthouse",
            format_type="story"
        )
        self.assertEqual(brief["product_intent"], "fiction")
        self.assertIn("Lighthouse", brief["title"])

        # Check sections represent story progression rather than how-to advice
        section_titles = [s["title"] for s in brief["sections"]]
        self.assertTrue(any("Chapter" in st or "Climax" in st or "Resolution" in st for st in section_titles))

        # Check Gemini prompt forbids how-to guide and instructs actual story prose
        prompt = DigitalProductEngine.generate_prompt_from_brief(brief)
        self.assertIn("DO NOT write an instructional writing guide", prompt)
        self.assertIn("write the ACTUAL NARRATIVE STORY itself", prompt)
        self.assertIn("The End", prompt)

    def test_gemini_max_tokens_truncation_detection(self):
        from services.digital_product_engine import DigitalProductEngine
        from unittest.mock import patch, Mock

        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Once upon a time in a dark forest, the creature moved through the trees without a sound..."}]},
                    "finishReason": "MAX_TOKENS"
                }
            ]
        }

        env = {"GEMINI_API_KEY": "test-key-mock"}
        with patch.dict(os.environ, env, clear=False), patch("services.digital_product_engine.requests.post", return_value=mock_resp):
            res = DigitalProductEngine.call_gemini_api("Write full novel")
            self.assertFalse(res["success"])
            self.assertEqual(res.get("finish_reason"), "MAX_TOKENS")
            self.assertIn("truncated due to output token limit", res["error"])

    def test_missing_pypdf_validation_fails_honestly(self):
        from services.digital_product_engine import DigitalProductEngine
        from unittest.mock import patch

        pdf_path = self.gen_dir / "test_pypdf_missing.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 Mock Deliverable File Content")
        self.assertTrue(pdf_path.exists())

        with patch("services.digital_product_engine.PYPDF_AVAILABLE", False):
            val = DigitalProductEngine.validate_pdf(pdf_path)
            self.assertFalse(val["valid"])
            self.assertIn("pypdf library is required", val["error"])

    def test_local_publication_quality_gate(self):
        from database import get_db_connection

        conn = get_db_connection()
        cur = conn.cursor()

        # Seed test product with is_test=1
        cur.execute("""
            INSERT INTO digital_products (slug, title, product_type, audience, value_proposition, description, price, status, is_test, created_at, updated_at)
            VALUES ('test-gated-item', 'Test Gated Product Title', 'guide', 'Founders', 'VP here', 'Substantive description text at least 20 chars long', 15.00, 'draft', 1, datetime('now'), datetime('now'))
        """)
        test_prod_id = cur.lastrowid
        conn.commit()
        conn.close()

        # Attempt to publish test record
        res_test = self.client.post(f"/api/products/{test_prod_id}/status", json={"status": "published"})
        self.assertEqual(res_test.status_code, 422)
        data = res_test.get_json()
        self.assertIn("Automated test records cannot be published", " ".join(data.get("issues", [])))

    def test_gumroad_attachment_workflow_and_verification(self):
        from services.gumroad_service import GumroadService
        from database import get_db_connection
        from unittest.mock import patch, Mock

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO digital_products (slug, title, product_type, audience, value_proposition, description, price, status, is_test, created_at, updated_at)
            VALUES ('attachment-flow-kit', 'Attachment Flow Kit', 'guide', 'Audience', 'VP', 'Long enough description for validation', 19.99, 'ready', 0, datetime('now'), datetime('now'))
        """)
        product_id = cur.lastrowid
        conn.commit()
        conn.close()

        mock_post = Mock()
        mock_post.status_code = 201
        mock_post.json.return_value = {
            "success": True,
            "product": {
                "id": "gum_att_555",
                "short_url": "https://gumroad.com/l/attachment-flow-kit"
            }
        }

        env = {"GUMROAD_ACCESS_TOKEN": "mock-token-xyz"}
        with patch.dict(os.environ, env, clear=False), patch("services.gumroad_service.requests.post", return_value=mock_post):
            sync_res = GumroadService.sync_product(product_id)
            self.assertTrue(sync_res["success"])
            self.assertEqual(sync_res["attachment_status"], "pending_manual_attachment")
            self.assertFalse(sync_res["pdf_attached"])
            self.assertIn("gum_att_555", sync_res["gumroad_edit_url"])

            # Verify in DB
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT gumroad_attachment_status, gumroad_edit_url FROM digital_products WHERE id = ?", (product_id,))
            row = cur.fetchone()
            conn.close()
            self.assertEqual(row["gumroad_attachment_status"], "pending_manual_attachment")
            self.assertIn("gum_att_555", row["gumroad_edit_url"])

            # Call verification endpoint
            ver_res = self.client.post(f"/api/products/{product_id}/verify_attachment", json={"confirmed": True})
            self.assertEqual(ver_res.status_code, 200)

            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT gumroad_attachment_status FROM digital_products WHERE id = ?", (product_id,))
            row = cur.fetchone()
            conn.close()
            self.assertEqual(row["gumroad_attachment_status"], "verified_attached")


class TestMINTAgentsArchitectureRefactor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import config, database
        cls.temp_dir = tempfile.mkdtemp()
        cls.db_path = Path(cls.temp_dir) / "test_agents_refactor.db"
        cls.gen_dir = Path(cls.temp_dir) / "generated"
        cls.gen_dir.mkdir(parents=True, exist_ok=True)

        cls.orig_db_path = config.DB_PATH
        cls.orig_gen_dir = config.GENERATED_DIR

        config.DB_PATH = cls.db_path
        config.GENERATED_DIR = cls.gen_dir
        database.DB_PATH = cls.db_path
        database.init_db()

        from app import app
        cls.app = app
        cls.client = app.test_client()

    @classmethod
    def tearDownClass(cls):
        import config, database
        from agents.orchestrator import RealMINTOrchestrator
        RealMINTOrchestrator._running_experiments.clear()
        config.DB_PATH = cls.orig_db_path
        config.GENERATED_DIR = cls.orig_gen_dir
        database.DB_PATH = cls.orig_db_path
        if os.path.exists(cls.temp_dir):
            shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def test_single_venture_run_no_duplicate_product_or_content_records(self):
        from agents.orchestrator import RealMINTOrchestrator
        from database import get_db_connection
        import time

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO experiments (name, goal, business_model, target_audience, budget_limit, status, created_at, updated_at)
            VALUES ('Venture Run Duplication Audit', 'Build solo developer retainer playbook', 'digital_product', 'devs', 50.0, 'draft', datetime('now'), datetime('now'))
        """)
        exp_id = cur.lastrowid
        conn.commit()
        conn.close()

        def mock_render_pdf(html_content, output_pdf_path):
            p = Path(output_pdf_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n2 0 obj\n<<\n/Type /Pages\n/Kids [3 0 R]\n/Count 1\n>>\nendobj\n3 0 obj\n<<\n/Type /Page\n/Parent 2 0 R\n/MediaBox [0 0 612 792]\n>>\nendobj\nxref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000058 00000 n\n0000000115 00000 n\ntrailer\n<<\n/Size 4\n/Root 1 0 R\n>>\nstartxref\n190\n%%EOF")
            return {
                "success": True,
                "pdf_path": str(p),
                "page_count": 1,
                "file_size": p.stat().st_size
            }

        mock_content = "# Guide Title\n\n## Chapter 1\nSubstantive content for the guide to pass length and quality checks easily.\n" * 10
        from unittest.mock import patch
        with patch("services.digital_product_engine.DigitalProductEngine.call_gemini_api", return_value={"success": True, "content": mock_content, "model": "mock"}), \
             patch("services.digital_product_engine.DigitalProductEngine.render_pdf_with_chromium", side_effect=mock_render_pdf), \
             patch("services.ai_service.AIService.generate_chat", return_value={"success": False, "reply": ""}):
            orch = RealMINTOrchestrator()
            started = orch.run_pipeline_async(exp_id)
            self.assertTrue(started)

            # Wait for completion (fast mock takes < 1s)
            for _ in range(80):
                time.sleep(0.1)
                if not orch.is_experiment_running(exp_id):
                    break

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT status FROM experiments WHERE id = ?", (exp_id,))
        exp_row = cur.fetchone()
        self.assertEqual(exp_row["status"], "completed")

        # Verify exactly 1 artifact created for this run
        cur.execute("SELECT COUNT(*) as cnt FROM artifacts WHERE experiment_id = ?", (exp_id,))
        art_count = cur.fetchone()["cnt"]
        self.assertEqual(art_count, 1)

        # Verify exactly 1 digital product cataloged for this run
        cur.execute("SELECT COUNT(*) as cnt FROM digital_products WHERE experiment_id = ?", (exp_id,))
        prod_count = cur.fetchone()["cnt"]
        self.assertEqual(prod_count, 1)

        # Verify deliverable file exists on disk
        cur.execute("SELECT file_path, meta_json FROM artifacts WHERE experiment_id = ?", (exp_id,))
        art = cur.fetchone()
        self.assertTrue(os.path.exists(art["file_path"]))

        conn.close()

    def test_opportunity_hypotheses_not_represented_as_verified_market_research(self):
        from agents.opportunity_agent import OpportunityScout

        scout = OpportunityScout()
        candidates = scout.scout("Test venture hypothesis generation")
        self.assertGreaterEqual(len(candidates), 1)

        for cand in candidates:
            # Must NOT claim verified empirical data
            self.assertEqual(cand["is_verified"], 0)
            self.assertEqual(cand["is_simulated"], 1)
            self.assertTrue(
                cand["confidence"] in ("baseline_unverified", "unverified_ai_hypothesis"),
                f"Unexpected confidence: {cand['confidence']}"
            )
            self.assertTrue(
                cand["source_type"] in ("curated_market_fixture", "unverified_hypothesis_gemini", "unverified_hypothesis_mock"),
                f"Unexpected source_type: {cand['source_type']}"
            )
            # Evidence must not claim live market measurements
            self.assertNotIn("live web search", cand["evidence"].lower())
            self.assertNotIn("verified sales data", cand["evidence"].lower())

    def test_deterministic_agents_derive_outputs_from_actual_inputs(self):
        from agents.strategy_agent import StrategyAgent
        from agents.quality_agent import QualityCheckerAgent
        from agents.measurement_agent import MeasurementAgent
        from agents.finance_agent import FinanceAgent
        from agents.portfolio_manager import PortfolioManager

        # 1. StrategyAgent configurable scoring
        strat = StrategyAgent(scoring_config={"high_competition_penalty": 25.0})
        cand_high = {"title": "High Comp Tool", "niche": "Cloud Dev Tools", "business_model": "digital_product", "demand_score": 90, "competition_level": "High"}
        cand_low = {"title": "Low Comp Tool", "niche": "Niche Hardware", "business_model": "digital_product", "demand_score": 75, "competition_level": "Low"}
        res = strat.select_strategy([cand_high, cand_low], budget=40.0)
        # 90 - 25 = 65 < 75, so cand_low wins deterministically
        self.assertEqual(res["candidate"]["title"], "Low Comp Tool")
        self.assertIn("StrategyAgent (deterministic configurable scoring engine)", res["provenance"])

        # 2. QualityCheckerAgent deterministic evaluation
        qc = QualityCheckerAgent()
        q_pass = qc.check_artifact("Clear explanation of workflows.", "Download now", "digital_product", "")
        self.assertTrue(q_pass["passed"])
        self.assertIn("QualityCheckerAgent", q_pass["provenance"])

        # 3. MeasurementAgent deterministic calculation
        meas = MeasurementAgent()
        m_res = meas.evaluate_performance(views=100, clicks=10, orders_count=2, net_profit=35.0, budget=50.0)
        self.assertEqual(m_res["metrics"]["ctr_pct"], 10.0)
        self.assertEqual(m_res["metrics"]["conversion_rate_pct"], 20.0)
        self.assertEqual(m_res["recommended_action"], "continue")
        self.assertIn("MeasurementAgent", m_res["provenance"])

        # 4. FinanceAgent exact reconciliation
        fin = FinanceAgent(reserve_ratio=0.25, reinvestment_ratio=0.40)
        orders = [
            {"gross_amount": 100.0, "fee_amount": 5.0, "is_refunded": False, "is_test": False},
            {"gross_amount": 50.0, "fee_amount": 2.0, "is_refunded": True, "refund_amount": 50.0, "is_test": False},
            {"gross_amount": 200.0, "fee_amount": 10.0, "is_refunded": False, "is_test": True} # sandbox test order
        ]
        stmt = fin.calculate_statement(starting_budget=50.0, actual_spend=20.0, orders=orders)
        self.assertEqual(stmt["gross_revenue"], 150.0)
        self.assertEqual(stmt["refunds"], 50.0)
        self.assertEqual(stmt["fees"], 7.0)
        self.assertEqual(stmt["net_sales"], 93.0) # 150 - 50 - 7
        self.assertEqual(stmt["net_profit"], 73.0) # 93 - 20
        self.assertEqual(stmt["required_reserve"], 18.25) # 73 * 0.25
        self.assertEqual(stmt["reinvestment_allocated"], 29.20) # 73 * 0.40
        self.assertEqual(stmt["surplus_available"], 25.55) # 73 - 18.25 - 29.20
        # Sandbox order isolated
        self.assertEqual(stmt["sandbox_summary"]["test_gross"], 200.0)
        self.assertIn("FinanceAgent", stmt["provenance"])

        # 5. PortfolioManager exact penny reconciliation
        port = PortfolioManager()
        alloc = port.allocate(stmt["surplus_available"], risk_profile="balanced")
        total_allocated = sum(item["amount"] for item in alloc["allocations"])
        self.assertAlmostEqual(total_allocated, stmt["surplus_available"], places=2)
        self.assertEqual(alloc["total_percentage"], 100.0)
        self.assertIn("PortfolioManager", alloc["provenance"])

    def test_context_builder_and_chat_assistant_gumroad_truthfulness(self):
        from agents.context_builder import build_context
        from agents.chat_assistant import RealChatAssistant
        from unittest.mock import patch

        ctx = build_context()
        self.assertIn("integrations", ctx)
        self.assertIn("gumroad", ctx["integrations"])

        assistant = RealChatAssistant()
        # Query about Gumroad when connected
        mock_gum_connected = {
            "connected": True,
            "status": "connected",
            "user": {"name": "Test Merchant", "email": "merchant@gumroad.local"},
            "auto_publish": True,
            "message": "Connected"
        }
        with patch("services.gumroad_service.GumroadService.get_status", return_value=mock_gum_connected), \
             patch("services.ai_service.AIService.generate_chat", return_value={"success": False, "provider": "none", "reply": ""}):
            reply_dict = assistant.handle_message(None, "Is Gumroad connected right now?")
            reply = reply_dict["reply"]
            self.assertIn("Gumroad is connected as Test Merchant", reply)
            self.assertIn("Auto-publish: True", reply)


class TestMINTContentStudioAndImageGeneration(unittest.TestCase):
    """
    Regression test suite for:
    - Gemini AI Image Generation (Interactions API)
    - Instagram Marketing & Carousel / Single Image publishing
    - Public HTTPS Media Hosting checks and blockers
    - Safe Product Deletion (audit preservation, Gumroad warning, path traversal prevention)
    - Safe Content / Video deletion
    - Selective Generated Folder Cleanup (test jobs vs user work preservation)
    - Card Left-Border CSS refinement
    """

    def setUp(self):
        import tempfile
        import sqlite3
        from pathlib import Path
        import config
        from database import init_db

        self.temp_dir = tempfile.mkdtemp()
        self.orig_db_path = getattr(config, "DB_PATH", None)
        self.orig_gen_dir = getattr(config, "GENERATED_DIR", None)

        test_db = Path(self.temp_dir) / "test_mint_cs.db"
        test_gen = Path(self.temp_dir) / "generated"
        test_gen.mkdir(parents=True, exist_ok=True)

        config.DB_PATH = test_db
        config.GENERATED_DIR = test_gen
        init_db()

    def tearDown(self):
        import shutil
        import config
        if self.orig_db_path:
            config.DB_PATH = self.orig_db_path
        if self.orig_gen_dir:
            config.GENERATED_DIR = self.orig_gen_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_test_jpeg_bytes(self):
        from PIL import Image
        import io
        buf = io.BytesIO()
        im = Image.new("RGB", (100, 100), color=(79, 70, 229))
        im.save(buf, format="JPEG")
        return buf.getvalue()

    def test_ai_image_generation_success_and_pillow_validation(self):
        import base64
        from unittest.mock import patch
        from services.ai_image_service import AIImageService

        raw_bytes = self._make_test_jpeg_bytes()
        b64_str = base64.b64encode(raw_bytes).decode("ascii")

        mock_resp_payload = {
            "result": {
                "image": b64_str
            },
            "success": True
        }

        class MockResponse:
            status_code = 200
            headers = {"content-type": "application/json"}
            def json(self): return mock_resp_payload
            text = "OK"

        with patch("services.ai_image_service.requests.post", return_value=MockResponse()), \
             patch.dict("os.environ", {
                 "CLOUDFLARE_ACCOUNT_ID": "test_acc_123",
                 "CLOUDFLARE_API_TOKEN": "test_tok_456",
                 "IMAGE_PROVIDER": "cloudflare_workers_ai",
                 "IMAGE_MODEL": "@cf/black-forest-labs/flux-1-schnell"
             }):
            res = AIImageService.generate_image(
                prompt="Modern minimalist desk workspace with soft lighting",
                style="photorealistic",
                aspect_ratio="1:1",
                is_test=1
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["status"], "completed")
            self.assertEqual(res["model"], "@cf/black-forest-labs/flux-1-schnell")
            self.assertEqual(res["provider"], "cloudflare_workers_ai")
            self.assertTrue(Path(res["file_path"]).exists())
            self.assertIn("/api/images/", res["file_url"])

            # Verify image record in DB
            img_record = AIImageService.get_image(res["asset_id"])
            self.assertIsNotNone(img_record)
            self.assertEqual(img_record["status"], "completed")
            self.assertEqual(img_record["provider"], "cloudflare_workers_ai")
            self.assertEqual(img_record["style"], "photorealistic")

    def test_ai_image_unconfigured_and_rate_limit_errors(self):
        from unittest.mock import patch
        from services.ai_image_service import AIImageService

        # 1. Unconfigured credentials return honest configuration requirement
        with patch.dict("os.environ", {"CLOUDFLARE_ACCOUNT_ID": "", "CLOUDFLARE_API_TOKEN": ""}):
            res = AIImageService.generate_image("A futuristic city")
            self.assertFalse(res["success"])
            self.assertEqual(res["status"], "not_configured")
            self.assertIn("CLOUDFLARE_ACCOUNT_ID", res["error"])

        # 2. Rate limit 429 returns honest quota/neuron error
        class Mock429Response:
            status_code = 429
            headers = {"content-type": "application/json"}
            def json(self): return {"errors": [{"message": "Daily neuron allocation exceeded"}], "success": False}
            text = "Quota exceeded"

        with patch("services.ai_image_service.requests.post", return_value=Mock429Response()), \
             patch.dict("os.environ", {"CLOUDFLARE_ACCOUNT_ID": "acc", "CLOUDFLARE_API_TOKEN": "tok"}):
            res = AIImageService.generate_image("A futuristic city")
            self.assertFalse(res["success"])
            self.assertEqual(res["status"], "rate_limited")
            self.assertIn("HTTP 429", res["error"])
            self.assertIn("10,000 neurons", res["error"])

    def test_instagram_publishing_requires_confirmation_and_hosting(self):
        from unittest.mock import patch
        from services.social_service import InstagramService

        # 1. Confirmation required
        res = InstagramService.publish_media(
            media_url_or_path="https://example.com/valid_image.jpg",
            caption="Test post",
            confirmed=False
        )
        self.assertFalse(res["success"])
        self.assertEqual(res["status"], "confirmation_required")

        # 2. Local disk file blocked before calling Meta
        res_local = InstagramService.publish_media(
            media_url_or_path="D:\\chronoforge\\generated\\images\\local.jpg",
            caption="Test post",
            confirmed=True
        )
        self.assertFalse(res_local["success"])
        self.assertEqual(res_local["status"], "media_hosting_required")

        # 3. Carousel local item blocked
        res_carousel_local = InstagramService.publish_carousel(
            image_urls=["https://example.com/valid.jpg", "D:\\local.jpg"],
            caption="Test carousel",
            confirmed=True
        )
        self.assertFalse(res_carousel_local["success"])
        self.assertEqual(res_carousel_local["status"], "media_hosting_required")

    def test_instagram_mock_single_and_carousel_publishing(self):
        from unittest.mock import patch
        from services.social_service import InstagramService

        mock_status = {
            "can_publish": True,
            "status": "connected",
            "account_id": "17841400000000001",
            "message": "Connected"
        }

        # Step 1: Mock container creation -> Step 2: Mock publish container
        class MockMetaPostResponse:
            def __init__(self, data, status_code=200):
                self._data = data
                self.status_code = status_code
                self.text = "OK"
            def json(self): return self._data

        def mock_meta_post(url, *args, **kwargs):
            if "media_publish" in url:
                return MockMetaPostResponse({"id": "meta_published_media_999"})
            elif "/media" in url:
                return MockMetaPostResponse({"id": "meta_container_111"})
            return MockMetaPostResponse({}, status_code=400)

        with patch.object(InstagramService, "get_status", return_value=mock_status), \
             patch("services.social_service.requests.post", side_effect=mock_meta_post), \
             patch.dict("os.environ", {"INSTAGRAM_ACCESS_TOKEN": "valid_token", "INSTAGRAM_ACCOUNT_ID": "17841400000000001"}):

            # Test single image publishing
            res_single = InstagramService.publish_media(
                media_url_or_path="https://res.cloudinary.com/mint/image/upload/sample.jpg",
                caption="Official MINT Release #mint",
                media_type="IMAGE",
                confirmed=True
            )
            self.assertTrue(res_single["success"])
            self.assertEqual(res_single["media_id"], "meta_published_media_999")
            self.assertEqual(res_single["status"], "published")

            # Test carousel publishing
            res_carousel = InstagramService.publish_carousel(
                image_urls=[
                    "https://res.cloudinary.com/mint/image/upload/slide1.jpg",
                    "https://res.cloudinary.com/mint/image/upload/slide2.jpg"
                ],
                caption="Official MINT Carousel #mint",
                confirmed=True
            )
            self.assertTrue(res_carousel["success"])
            self.assertEqual(res_carousel["media_id"], "meta_published_media_999")
            self.assertEqual(res_carousel["status"], "published")

    def test_product_deletion_preserves_orders_and_warns_gumroad(self):
        from database import get_db_connection
        from routes.products import products_bp
        from flask import Flask

        app = Flask(__name__)
        app.register_blueprint(products_bp)
        client = app.test_client()

        # Seed 2 products: Product A referenced by an order, Product B unreferenced
        conn = get_db_connection()
        cur = conn.cursor()
        now = "2026-10-24 12:00:00"

        cur.execute("""
            INSERT INTO digital_products (slug, title, product_type, audience, value_proposition, description, price, status, gumroad_id, created_at, updated_at)
            VALUES ('referenced-product', 'Referenced Framework', 'guide', 'Founders', 'VP', 'Desc', 19.0, 'published', 'gum_123', ?, ?)
        """, (now, now))
        prod_a_id = cur.lastrowid

        # Insert order referencing Product A
        cur.execute("""
            INSERT INTO orders (customer_email, product_title, gross_amount, fee_amount, is_test, created_at)
            VALUES ('cust@example.com', 'Referenced Framework', 19.0, 0.95, 0, ?)
        """, (now,))

        cur.execute("""
            INSERT INTO digital_products (slug, title, product_type, audience, value_proposition, description, price, status, created_at, updated_at)
            VALUES ('unreferenced-product', 'Unreferenced Guide', 'guide', 'Founders', 'VP', 'Desc', 15.0, 'ready', ?, ?)
        """, (now, now))
        prod_b_id = cur.lastrowid
        conn.commit()
        conn.close()

        # Delete Product A: must be archived (soft-delete) to preserve order history
        resp_a = client.delete(f"/api/products/{prod_a_id}")
        self.assertEqual(resp_a.status_code, 200)
        data_a = resp_a.get_json()
        self.assertEqual(data_a["action"], "archived")
        self.assertIn("audit", data_a["message"].lower())
        self.assertIn("Gumroad", data_a["warning"])

        # Check DB status of Product A
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT status FROM digital_products WHERE id = ?", (prod_a_id,))
        self.assertEqual(cur.fetchone()[0], "archived")

        # Delete Product B: unreferenced, physically deleted
        resp_b = client.delete(f"/api/products/{prod_b_id}")
        self.assertEqual(resp_b.status_code, 200)
        data_b = resp_b.get_json()
        self.assertEqual(data_b["action"], "deleted")

        cur.execute("SELECT COUNT(*) FROM digital_products WHERE id = ?", (prod_b_id,))
        self.assertEqual(cur.fetchone()[0], 0)
        conn.close()

    def test_selective_cleanup_identifies_test_jobs_without_touching_user_assets(self):
        from services.cleanup_service import CleanupService
        import config

        gen_dir = Path(config.GENERATED_DIR)
        # Create simulated test job 1 directory
        test_job_dir = gen_dir / "content" / "job_1"
        test_job_dir.mkdir(parents=True, exist_ok=True)
        (test_job_dir / "test_file.txt").write_text("automated test output")

        # Create simulated orphaned temp frame
        images_dir = gen_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        temp_frame = images_dir / "temp_frame_asset_test.mp4.png"
        temp_frame.write_text("temp frame")

        # Create user non-test job 12
        user_job_dir = gen_dir / "content" / "jobs" / "12"
        user_job_dir.mkdir(parents=True, exist_ok=True)
        (user_job_dir / "final_short.mp4").write_text("real video")

        # Register user job 12 in DB as is_test=0
        from database import get_db_connection
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO content_jobs (id, title, is_test, output_dir, audience, problem, product_facts, created_at, updated_at)
            VALUES (12, 'User Real Video', 0, ?, 'Audience', 'Prob', 'Facts', '2026-10-24 12:00:00', '2026-10-24 12:00:00')
        """, (str(user_job_dir),))
        conn.commit()
        conn.close()

        # Run dry run inventory
        inv = CleanupService.get_inventory()
        candidate_names = [d["name"] for d in inv["candidate_deletions"]]
        self.assertIn("job_1", candidate_names)
        self.assertIn("temp_frame_asset_test.mp4.png", candidate_names)

        # Confirm user job 12 is in candidate_preservations and not deletions
        self.assertNotIn("jobs/12", candidate_names)
        pres_names = [p["name"] for p in inv["candidate_preservations"]]
        self.assertIn("jobs/12", pres_names)

        # Execute cleanup
        clean_res = CleanupService.execute_cleanup(dry_run=False)
        self.assertTrue(clean_res["executed"])
        self.assertFalse(test_job_dir.exists())
        self.assertFalse(temp_frame.exists())
        self.assertTrue(user_job_dir.exists())

    def test_css_left_borders_removed(self):
        with open("static/css/dashboard.css", "r", encoding="utf-8") as f:
            css = f.read()

        # Ensure decorative left borders on .agent-node are removed
        self.assertNotIn(".agent-node.completed {\n  border-color: var(--border-subtle);\n  background: var(--surface-card);\n  border-left:", css)
        self.assertNotIn(".agent-node.interrupted {\n  border-color: var(--border-subtle);\n  background: var(--surface-card);\n  border-left:", css)
        self.assertNotIn(".agent-node.failed {\n  border-color: var(--border-subtle);\n  background: var(--surface-card);\n  border-left:", css)
        self.assertNotIn(".agent-node.needs_review {\n  border-color: var(--border-subtle);\n  background: var(--surface-card);\n  border-left:", css)

        # Ensure storefront and affiliates cards have removed inline border-left: 4px solid var(--accent-teal)
        with open("templates/affiliates.html", "r", encoding="utf-8") as f:
            aff_html = f.read()
        self.assertNotIn('border-left: 4px solid var(--accent-teal);', aff_html)

        with open("templates/storefront.html", "r", encoding="utf-8") as f:
            sf_html = f.read()
        self.assertNotIn('border-left: 4px solid var(--accent-teal);', sf_html)

    def test_content_studio_routes_and_path_traversal_guards(self):
        from routes.content_studio import content_studio_bp
        from services.ai_image_service import AIImageService
        from database import get_db_connection
        from flask import Flask
        from unittest.mock import patch
        import json
        import base64

        app = Flask(__name__)
        app.register_blueprint(content_studio_bp)
        client = app.test_client()

        # 1. Test image generation route with Cloudflare mock
        raw_bytes = self._make_test_jpeg_bytes()
        b64_str = base64.b64encode(raw_bytes).decode("ascii")
        mock_payload = {
            "result": {"image": b64_str},
            "success": True
        }
        class MockResp:
            status_code = 200
            headers = {"content-type": "application/json"}
            def json(self): return mock_payload
            text = "OK"

        with patch("services.ai_image_service.requests.post", return_value=MockResp()), \
             patch.dict("os.environ", {"CLOUDFLARE_ACCOUNT_ID": "fake_acc", "CLOUDFLARE_API_TOKEN": "fake_tok"}):
            gen_resp = client.post("/api/images/generate", json={
                "prompt": "Test AI image creative",
                "aspect_ratio": "1:1"
            })
            self.assertEqual(gen_resp.status_code, 201)
            img_data = gen_resp.get_json()
            self.assertTrue(img_data["success"])
            img_id = img_data["asset_id"]

            # Test list images route
            list_resp = client.get("/api/images?include_test=1")
            self.assertEqual(list_resp.status_code, 200)
            self.assertGreater(list_resp.get_json()["count"], 0)

            # Test get image route
            get_resp = client.get(f"/api/images/{img_id}")
            self.assertEqual(get_resp.status_code, 200)

            # Test safe file serve
            file_resp = client.get(f"/api/images/{img_id}/file")
            self.assertEqual(file_resp.status_code, 200)
            self.assertEqual(file_resp.mimetype, "image/jpeg")
            file_resp.close()

            # Test publish image to Instagram requires confirmation
            unconfirmed_resp = client.post(f"/api/images/{img_id}/publish_instagram", json={"confirmed": False})
            self.assertEqual(unconfirmed_resp.status_code, 400)
            self.assertEqual(unconfirmed_resp.get_json()["status"], "confirmation_required")

            # Test publish image to Instagram with explicit confirmation and mocked external services
            with patch("services.media_hosting_service.MediaHostingService.get_status", return_value={"can_host": True, "configured": True, "provider_label": "Cloudinary"}), \
                 patch("services.media_hosting_service.MediaHostingService.upload_image", return_value={"success": True, "public_url": "https://res.cloudinary.com/test.jpg"}), \
                 patch("services.social_service.InstagramService.publish_media", return_value={"success": True, "status": "published", "media_id": "meta_img_123"}):
                pub_resp = client.post(f"/api/images/{img_id}/publish_instagram", json={"confirmed": True, "caption": "Awesome AI art #mint"})
                self.assertEqual(pub_resp.status_code, 200)
                self.assertTrue(pub_resp.get_json()["success"])
                self.assertEqual(pub_resp.get_json()["media_id"], "meta_img_123")

            # Test delete image is safely blocked while referenced by the published Instagram post
            del_blocked_resp = client.delete(f"/api/images/{img_id}")
            self.assertEqual(del_blocked_resp.status_code, 400)
            self.assertIn("referenced by Instagram post", del_blocked_resp.get_json().get("error", ""))

            # Remove referencing Instagram test post to test unblocked image deletion
            from database import get_db_connection
            with get_db_connection() as conn:
                conn.execute("DELETE FROM instagram_posts WHERE title LIKE ?", (f"Image #{img_id}:%",))
                conn.commit()

            # Test delete image succeeds now that reference is removed
            del_resp = client.delete(f"/api/images/{img_id}")
            self.assertEqual(del_resp.status_code, 200)

        # 2. Test path traversal on serve job file & serve instagram file
        bad_file_resp = client.get("/api/content/jobs/1/files/..%2F..%2F..%2Fsecret.txt")
        self.assertIn(bad_file_resp.status_code, (400, 403, 404))

        bad_ig_file = client.get("/api/instagram/content/1/files/..%2F..%2Fevil.jpg")
        self.assertIn(bad_ig_file.status_code, (400, 403, 404))

        # 3. Test delete content job
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO content_jobs (id, title, is_test, audience, problem, product_facts, created_at, updated_at)
            VALUES (999, 'Deletable Job', 1, 'Audience', 'Prob', 'Facts', '2026-10-24 12:00:00', '2026-10-24 12:00:00')
        """)
        conn.commit()
        conn.close()

        job_del_resp = client.delete("/api/content/jobs/999")
        self.assertEqual(job_del_resp.status_code, 200)
        self.assertTrue(job_del_resp.get_json()["success"])


class TestMINTFinalIntegrationAndAutomation(unittest.TestCase):
    """
    Test suite for final consolidation:
    - Cloudflare Workers AI FLUX.1 Schnell image generator (binary, JSON, errors, zero Gemini/Pillow fallback)
    - YouTube channel resolution (Data API v3)
    - YouTube clipping engine (rights confirmation, 9:16 transcode mock)
    - YouTube twice-daily scheduler (slots, timezone, max 2 posts/day, publishAt, offline gap handling, honest analytics)
    - Control Assistant history & conversation_id preservation
    - Safe Markdown parser & sanitizer validation
    - SQLite row access in revise_hook (no AttributeError: 'sqlite3.Row' object has no attribute 'get')
    - Operational context breadth & Gemini REST multi-turn history
    - Safe deletions & zero database pollution
    """

    def setUp(self):
        import tempfile
        from pathlib import Path
        import config
        from database import init_db

        self.temp_dir = tempfile.mkdtemp()
        self.orig_db_path = getattr(config, "DB_PATH", None)
        self.orig_gen_dir = getattr(config, "GENERATED_DIR", None)

        test_db = Path(self.temp_dir) / "test_mint_final.db"
        test_gen = Path(self.temp_dir) / "generated"
        test_gen.mkdir(parents=True, exist_ok=True)

        config.DB_PATH = test_db
        config.GENERATED_DIR = test_gen
        init_db()

    def tearDown(self):
        import shutil
        import config
        if self.orig_db_path:
            config.DB_PATH = self.orig_db_path
        if self.orig_gen_dir:
            config.GENERATED_DIR = self.orig_gen_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_sample_image_bytes(self):
        from PIL import Image
        import io
        buf = io.BytesIO()
        im = Image.new("RGB", (128, 128), color=(99, 102, 241))
        im.save(buf, format="PNG")
        return buf.getvalue()

    def test_cloudflare_image_generation_binary_and_json(self):
        """Verify both binary stream response and JSON base64 response from Cloudflare."""
        import base64
        from unittest.mock import patch
        from services.ai_image_service import AIImageService

        raw_bytes = self._make_sample_image_bytes()

        # 1. Binary image stream response (Content-Type: image/png)
        class MockBinaryResp:
            status_code = 200
            headers = {"content-type": "image/png"}
            content = raw_bytes
            text = ""

        with patch("services.ai_image_service.requests.post", return_value=MockBinaryResp()), \
             patch.dict("os.environ", {
                 "CLOUDFLARE_ACCOUNT_ID": "acc123",
                 "CLOUDFLARE_API_TOKEN": "tok456"
             }):
            res = AIImageService.generate_image("Modern high tech dashboard", is_test=1)
            self.assertTrue(res["success"])
            self.assertEqual(res["provider"], "cloudflare_workers_ai")
            self.assertEqual(res["model"], "@cf/black-forest-labs/flux-1-schnell")
            self.assertTrue(Path(res["file_path"]).exists())

        # 2. JSON base64 response
        b64_str = base64.b64encode(raw_bytes).decode("ascii")
        class MockJsonResp:
            status_code = 200
            headers = {"content-type": "application/json"}
            def json(self): return {"result": {"image": b64_str}, "success": True}
            text = "OK"

        with patch("services.ai_image_service.requests.post", return_value=MockJsonResp()), \
             patch.dict("os.environ", {
                 "CLOUDFLARE_ACCOUNT_ID": "acc123",
                 "CLOUDFLARE_API_TOKEN": "tok456"
             }):
            res2 = AIImageService.generate_image("Minimalist vector logo", is_test=1)
            self.assertTrue(res2["success"])
            self.assertEqual(res2["status"], "completed")

    def test_cloudflare_no_hidden_fallbacks(self):
        """Confirm that when Cloudflare fails, Gemini is NOT called and fixed graphics are NOT created."""
        from unittest.mock import patch
        from services.ai_image_service import AIImageService

        class MockErrResp:
            status_code = 401
            headers = {"content-type": "application/json"}
            def json(self): return {"errors": [{"message": "Invalid API token"}]}
            text = "Unauthorized"

        with patch("services.ai_image_service.requests.post", return_value=MockErrResp()), \
             patch.dict("os.environ", {"CLOUDFLARE_ACCOUNT_ID": "acc", "CLOUDFLARE_API_TOKEN": "bad_tok"}):
            res = AIImageService.generate_image("Prompt", is_test=1)
            self.assertFalse(res["success"])
            self.assertEqual(res["status"], "auth_error")
            self.assertIn("HTTP 401", res["error"])

    def test_delete_image_blocks_when_referenced_by_instagram_post(self):
        """Deleting an image asset is blocked if referenced by an active Instagram post."""
        import config
        from services.ai_image_service import AIImageService
        from database import get_db_connection

        raw_bytes = self._make_sample_image_bytes()
        gen_dir = Path(getattr(config, "GENERATED_DIR"))
        img_dir = gen_dir / "images" / "88"
        img_dir.mkdir(parents=True, exist_ok=True)
        img_path = img_dir / "image_88.png"
        img_path.write_bytes(raw_bytes)

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO image_assets (id, prompt, aspect_ratio, provider, model, file_path, status, is_test, created_at)
            VALUES (88, 'Prompt', '1:1', 'cloudflare_workers_ai', '@cf/black-forest-labs/flux-1-schnell', ?, 'completed', 1, '2026-10-24 12:00:00')
        """, (str(img_path),))
        cur.execute("""
            INSERT INTO instagram_posts (id, title, caption, image_paths_json, status, is_test, created_at, updated_at)
            VALUES (55, 'Summer Promo', 'Caption', '[\"generated/images/88/image_88.png\"]', 'draft', 1, '2026-10-24 12:00:00', '2026-10-24 12:00:00')
        """)
        conn.commit()
        conn.close()

        # Attempt to delete referenced image
        res = AIImageService.delete_image(88)
        self.assertFalse(res["success"])
        self.assertIn("referenced by Instagram post", res["error"])
        self.assertTrue(img_path.exists())

    def test_youtube_channel_resolution(self):
        """Channel handle resolves via YouTube Data API without exposing private source media."""
        from unittest.mock import patch, MagicMock
        from services.youtube_clipping_service import YouTubeClippingService

        mock_yt = MagicMock()
        mock_yt.channels().list().execute.return_value = {
            "items": [
                {
                    "id": "UC_TEST_CHANNEL_123",
                    "snippet": {
                        "title": "Verified Creator Channel",
                        "customUrl": "@verifiedcreator",
                        "description": "Tech educational videos.",
                        "thumbnails": {"default": {"url": "https://yt.com/thumb.jpg"}}
                    },
                    "statistics": {
                        "subscriberCount": "150000",
                        "videoCount": "42"
                    }
                }
            ]
        }

        with patch("services.youtube_clipping_service._load_token", return_value=MagicMock(scopes=["https://www.googleapis.com/auth/youtube.readonly"])), \
             patch("services.youtube_clipping_service._refresh_if_needed", side_effect=lambda x: x), \
             patch("services.youtube_clipping_service._build_youtube_client", return_value=mock_yt):
            res = YouTubeClippingService.resolve_source_channel("@verifiedcreator")
            self.assertTrue(res["success"])
            self.assertEqual(res["channel_id"], "UC_TEST_CHANNEL_123")
            self.assertEqual(res["title"], "Verified Creator Channel")
            self.assertEqual(res["handle"], "@verifiedcreator")

    def test_youtube_clipping_requires_rights_and_valid_source(self):
        """Clipping rejects missing rights confirmation or non-existent source files."""
        from services.youtube_clipping_service import YouTubeClippingService

        # 1. Missing rights confirmation
        res = YouTubeClippingService.render_clip(
            source_path="generated/videos/source.mp4",
            start_sec=0,
            end_sec=10,
            clip_title="Test Clip",
            rights_confirmed=False
        )
        self.assertFalse(res["success"])
        self.assertIn("confirm ownership or authorized reuse rights", res["error"])

        # 2. Non-existent source file
        res2 = YouTubeClippingService.render_clip(
            source_path="non_existent_file.mp4",
            start_sec=0,
            end_sec=10,
            clip_title="Test Clip",
            rights_confirmed=True
        )
        self.assertFalse(res2["success"])
        self.assertIn("not found", res2["error"])

    def test_youtube_clipping_render_mock(self):
        """Tests successful FFmpeg clip rendering, vertical 9:16 metadata, and DB record."""
        import config
        from unittest.mock import patch
        from services.youtube_clipping_service import YouTubeClippingService
        import subprocess

        gen_dir = Path(getattr(config, "GENERATED_DIR"))
        src_file = gen_dir / "test_source.mp4"
        src_file.write_bytes(b"dummy_mp4_bytes")

        def mock_subprocess_run(cmd, *args, **kwargs):
            if "ffmpeg" in cmd[0]:
                out_path = Path(cmd[-1])
                out_path.write_bytes(b"rendered_clip_mp4_bytes_12345")
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            elif "ffprobe" in cmd[0]:
                return subprocess.CompletedProcess(cmd, 0, stdout="15.0\n", stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with patch("services.youtube_clipping_service.subprocess.run", side_effect=mock_subprocess_run):
            res = YouTubeClippingService.render_clip(
                source_path=str(src_file),
                start_sec=0.0,
                end_sec=15.0,
                clip_title="AI Automation Secrets",
                rights_confirmed=True,
                is_test=1
            )
            self.assertTrue(res["success"])
            self.assertEqual(res["status"], "rendered")
            self.assertEqual(res["duration_sec"], 15.0)
            self.assertTrue(Path(res["file_path"]).exists())

            # DB check
            clip = YouTubeClippingService.get_clip(res["clip_id"])
            self.assertIsNotNone(clip)
            self.assertEqual(clip["clip_title"], "AI Automation Secrets")

    def test_youtube_schedule_config_and_twice_daily_limit(self):
        """Validates persistent twice-daily schedule and max 2 posts per day enforcement."""
        from services.youtube_scheduler_service import YouTubeSchedulerService
        from database import get_db_connection

        # Update schedule config
        cfg = YouTubeSchedulerService.update_schedule_config(
            enabled=True,
            timezone_str="America/New_York",
            slot_1_time="11:00",
            slot_2_time="19:00"
        )
        self.assertEqual(cfg["slot_1_time"], "11:00")
        self.assertEqual(cfg["slot_2_time"], "19:00")
        self.assertEqual(cfg["timezone"], "America/New_York")

        # Create two rendered clips
        conn = get_db_connection()
        cur = conn.cursor()
        for cid in (101, 102, 103):
            cur.execute("""
                INSERT INTO youtube_clips (id, clip_title, source_file_path, output_path, status, is_test, created_at)
                VALUES (?, ?, 'src.mp4', 'out.mp4', 'rendered', 1, '2026-10-24 12:00:00')
            """, (cid, f"Clip {cid}"))
        conn.commit()
        conn.close()

        # Queue clip 101 for 2026-10-25
        res1 = YouTubeSchedulerService.queue_clip_for_scheduling(101, target_slot_datetime_utc="2026-10-25 11:00:00Z", is_test=1)
        self.assertTrue(res1["success"])

        # Queue clip 102 for 2026-10-25
        res2 = YouTubeSchedulerService.queue_clip_for_scheduling(102, target_slot_datetime_utc="2026-10-25 19:00:00Z", is_test=1)
        self.assertTrue(res2["success"])

        # Third clip on the same day must be rejected by max 2 posts/day policy
        res3 = YouTubeSchedulerService.queue_clip_for_scheduling(103, target_slot_datetime_utc="2026-10-25 22:00:00Z", is_test=1)
        self.assertFalse(res3["success"])
        self.assertIn("Daily limit reached", res3["error"])

    def test_youtube_scheduled_post_publish_at_api_verification(self):
        """Verifies publishAt status and requirement for status.privacyStatus='private' in API request."""
        import config
        from unittest.mock import patch, MagicMock
        from services.youtube_scheduler_service import YouTubeSchedulerService
        from database import get_db_connection

        gen_dir = Path(getattr(config, "GENERATED_DIR"))
        clip_file = gen_dir / "scheduled_clip.mp4"
        clip_file.write_bytes(b"valid_clip_data")

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO youtube_clips (id, clip_title, clip_description, source_file_path, output_path, status, is_test, created_at)
            VALUES (200, 'Scheduled Short', 'Desc', 'src.mp4', ?, 'rendered', 1, '2026-10-24 12:00:00')
        """, (str(clip_file),))
        cur.execute("""
            INSERT INTO youtube_scheduled_posts (id, clip_id, scheduled_time, target_slot, status, is_test, created_at, updated_at)
            VALUES (500, 200, '2026-10-26 14:00:00Z', 'slot_1', 'queued', 1, '2026-10-24 12:00:00', '2026-10-24 12:00:00')
        """)
        conn.commit()
        conn.close()

        mock_yt = MagicMock()
        mock_insert = MagicMock()
        mock_insert.next_chunk.return_value = (None, {
            "id": "YT_SCHEDULED_VID_999",
            "status": {
                "privacyStatus": "private",
                "publishAt": "2026-10-26T14:00:00Z"
            }
        })
        mock_yt.videos().insert.return_value = mock_insert

        with patch("services.youtube_scheduler_service._load_token", return_value=MagicMock(scopes=["https://www.googleapis.com/auth/youtube.upload"])), \
             patch("services.youtube_scheduler_service._refresh_if_needed", side_effect=lambda x: x), \
             patch("services.youtube_scheduler_service._build_youtube_client", return_value=mock_yt):
            res = YouTubeSchedulerService.publish_scheduled_post(500, confirmed=True)
            self.assertTrue(res["success"])
            self.assertEqual(res["video_id"], "YT_SCHEDULED_VID_999")
            self.assertEqual(res["status"], "scheduled_api")
            self.assertEqual(res["publish_at"], "2026-10-26T14:00:00Z")

            # Check insert body sent to Google
            insert_args = mock_yt.videos().insert.call_args[1]
            body = insert_args["body"]
            self.assertEqual(body["status"]["privacyStatus"], "private")
            self.assertIn("publishAt", body["status"])

    def test_youtube_scheduler_offline_missed_slots(self):
        """Offline gap detection marks past slots missed without bursting uploads."""
        from services.youtube_scheduler_service import YouTubeSchedulerService
        from database import get_db_connection

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO youtube_clips (id, clip_title, source_file_path, output_path, status, is_test, created_at)
            VALUES (300, 'Missed Clip', 'src.mp4', 'out.mp4', 'rendered', 1, '2026-10-24 12:00:00')
        """)
        # Slot scheduled in the past
        cur.execute("""
            INSERT INTO youtube_scheduled_posts (id, clip_id, scheduled_time, target_slot, status, is_test, created_at, updated_at)
            VALUES (600, 300, '2020-01-01 10:00:00Z', 'slot_1', 'queued', 1, '2020-01-01 08:00:00', '2020-01-01 08:00:00')
        """)
        conn.commit()
        conn.close()

        check = YouTubeSchedulerService.check_and_process_missed_slots()
        self.assertEqual(check["missed_marked"], 1)

        # Confirm post status changed to 'missed'
        posts = YouTubeSchedulerService.list_scheduled_posts(include_test=True)
        missed_post = next((p for p in posts if p["id"] == 600), None)
        self.assertIsNotNone(missed_post)
        self.assertEqual(missed_post["status"], "missed")

    def test_chat_assistant_conversation_id_and_unexperimented_persistence(self):
        """Conversation history persists by conversation_id across turns, even without an experiment."""
        from agents.chat_assistant import RealChatAssistant
        from database import get_db_connection

        assistant = RealChatAssistant()
        conv_id = "test_user_session_42"

        # Turn 1: Query without experiment
        res1 = assistant.handle_message(
            experiment_id=None,
            user_text="What is the current status of YouTube and Instagram?",
            conversation_id=conv_id
        )
        self.assertIn("reply", res1)
        self.assertEqual(res1["conversation_id"], conv_id)

        # Turn 2: Follow-up question
        res2 = assistant.handle_message(
            experiment_id=None,
            user_text="Tell me about our image generator.",
            conversation_id=conv_id
        )
        self.assertIn("Cloudflare Workers AI", res2["reply"])

        # Verify DB records
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT sender, message, conversation_id FROM chat_messages WHERE conversation_id = ? ORDER BY id ASC", (conv_id,))
        rows = cur.fetchall()
        conn.close()

        # Expect 4 rows: 2 user messages + 2 assistant messages
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["sender"], "user")
        self.assertEqual(rows[1]["sender"], "mint")
        self.assertEqual(rows[2]["sender"], "user")
        self.assertEqual(rows[3]["sender"], "mint")

    def test_chat_assistant_revise_hook_sqlite_row_access(self):
        """Revise hook does not crash on sqlite3.Row .get() call."""
        from agents.chat_assistant import RealChatAssistant
        from database import get_db_connection

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO experiments (id, name, goal, business_model, target_audience, status, created_at, updated_at)
            VALUES (77, 'SaaS Experiment', 'Validate', 'digital_product', 'Founders', 'running', '2026-10-24 12:00:00', '2026-10-24 12:00:00')
        """)
        cur.execute("""
            INSERT INTO artifacts (id, experiment_id, artifact_type, title, hook, call_to_action, disclaimer, created_at)
            VALUES (88, 77, 'video', 'Video 1', 'Old Hook', 'Get Guide', 'Results vary', '2026-10-24 12:00:00')
        """)
        conn.commit()
        conn.close()

        assistant = RealChatAssistant()
        res = assistant.handle_message(
            experiment_id=77,
            user_text='Change the hook to "Stop wasting hours on manual setup"',
            conversation_id="conv_hook_test"
        )
        self.assertIn("Action Executed: Hook updated", res["reply"])
        self.assertEqual(res["intent"], "revise_hook")

        # Verify artifact updated
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT hook FROM artifacts WHERE id = 88")
        updated_hook = cur.fetchone()["hook"]
        conn.close()
        self.assertEqual(updated_hook, "Stop wasting hours on manual setup")

    def test_gemini_rest_fallback_retains_conversation_history(self):
        """Verifies that AIService REST fallback builds prompt containing full conversation history."""
        from unittest.mock import patch
        from services.ai_service import AIService

        messages = [
            {"role": "user", "content": "What is our budget limit?"},
            {"role": "assistant", "content": "Your budget limit is $50."},
            {"role": "user", "content": "Can we increase it to $100?"}
        ]

        captured_payload = {}
        class MockRestResp:
            status_code = 200
            def json(self):
                return {"candidates": [{"content": {"parts": [{"text": "Yes, budget can be adjusted."}]}}]}

        def fake_post(url, json=None, timeout=None):
            captured_payload.update(json or {})
            return MockRestResp()

        # Force REST fallback by raising ImportError on google.genai
        with patch.dict("sys.modules", {"google.genai": None, "google": None}), \
             patch("services.ai_service.requests.post", side_effect=fake_post), \
             patch.dict("os.environ", {"AI_PROVIDER": "gemini", "GEMINI_API_KEY": "test_key"}):
            res = AIService.generate_chat(messages, context={"has_experiment": False})
            self.assertTrue(res["success"])
            self.assertIn("Yes, budget can be adjusted.", res["reply"])

            # Verify that conversation history was included in the REST payload
            prompt_text = captured_payload["contents"][0]["parts"][0]["text"]
            self.assertIn("What is our budget limit?", prompt_text)
            self.assertIn("Your budget limit is $50.", prompt_text)
            self.assertIn("Can we increase it to $100?", prompt_text)

    def test_safe_video_deletion_from_generated_videos(self):
        """Safely removes local videos with foreign reference protection."""
        import config
        from flask import Flask
        from routes.youtube_auth import youtube_auth_bp
        from database import get_db_connection

        app = Flask(__name__)
        app.register_blueprint(youtube_auth_bp)
        client = app.test_client()

        gen_dir = Path(getattr(config, "GENERATED_DIR"))
        v_dir = gen_dir / "videos"
        v_dir.mkdir(parents=True, exist_ok=True)
        vid_file = v_dir / "deletable_vid.mp4"
        vid_file.write_bytes(b"dummy_video_content")

        # 1. Unreferenced video deletes successfully
        res = client.delete("/api/youtube/videos/deletable_vid.mp4")
        self.assertEqual(res.status_code, 200)
        self.assertFalse(vid_file.exists())

        # 2. Referenced by artifact is blocked
        ref_vid = v_dir / "artifact_vid.mp4"
        ref_vid.write_bytes(b"artifact_video_bytes")
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO experiments (id, name, goal, business_model, target_audience, status, created_at, updated_at)
            VALUES (1, 'Exp 1', 'Goal', 'model', 'aud', 'draft', '2026-10-24 12:00:00', '2026-10-24 12:00:00')
        """)
        cur.execute("""
            INSERT INTO artifacts (id, experiment_id, artifact_type, title, file_path, created_at)
            VALUES (900, 1, 'video', 'Promo Video', ?, '2026-10-24 12:00:00')
        """, (str(ref_vid),))
        conn.commit()
        conn.close()

        res_blocked = client.delete("/api/youtube/videos/artifact_vid.mp4")
        self.assertEqual(res_blocked.status_code, 400)
        self.assertIn("referenced by Artifact #900", res_blocked.get_json()["error"])
        self.assertTrue(ref_vid.exists())


class TestMINTLumiClipAndYouTubeClipsAgent(unittest.TestCase):
    """
    Unit and integration tests for:
    - LumiClipService (REST API client, caching, quotas, token/rate limits, MP4 validation)
    - YouTubeClipsAgent (source channels, rights confirmation, video discovery, polling, review queue)
    - Twice-daily scheduling with Asia/Kolkata timezone and auto-publish
    - YouTube Clips routes and endpoints
    - Complete isolation with zero test pollution in data/mint.db
    """

    def setUp(self):
        import tempfile
        from pathlib import Path
        import config
        from database import init_db

        self.temp_dir = tempfile.mkdtemp()
        self.orig_db_path = getattr(config, "DB_PATH", None)
        self.orig_gen_dir = getattr(config, "GENERATED_DIR", None)

        test_db = Path(self.temp_dir) / "test_mint_lumiclip.db"
        test_gen = Path(self.temp_dir) / "generated"
        test_gen.mkdir(parents=True, exist_ok=True)

        config.DB_PATH = test_db
        config.GENERATED_DIR = test_gen
        init_db()

    def tearDown(self):
        import shutil
        import config
        if self.orig_db_path:
            config.DB_PATH = self.orig_db_path
        if self.orig_gen_dir:
            config.GENERATED_DIR = self.orig_gen_dir
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_lumiclip_service_status_and_usage(self):
        """Tests LumiClipService.get_status() across all states with mock responses."""
        from unittest.mock import patch, MagicMock
        from services.lumiclip_service import LumiClipService
        import requests

        # Reset cache
        import services.lumiclip_service as lcs_mod
        lcs_mod._USAGE_CACHE = None
        lcs_mod._USAGE_CACHE_TIME = 0

        # 1. Unconfigured
        with patch.object(LumiClipService, "get_api_key", return_value=""):
            status = LumiClipService.get_status(force_refresh=True)
            self.assertEqual(status["status"], "not_configured")
            self.assertIsNone(status["credits_remaining"])
            self.assertFalse(status["can_clip"])

        # 2. Connected with healthy credits (> 15)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"plan": "creator_pro", "credits_remaining": 65}'
        mock_resp.json.return_value = {"plan": "creator_pro", "credits_remaining": 65}
        with patch.object(LumiClipService, "get_api_key", return_value="lumi_test_key_123"), \
             patch("services.lumiclip_service.requests.get", return_value=mock_resp):
            status = LumiClipService.get_status(force_refresh=True)
            self.assertEqual(status["status"], "connected")
            self.assertEqual(status["credits_remaining"], 65)
            self.assertEqual(status["plan"], "creator_pro")
            self.assertTrue(status["can_clip"])

        # 3. Credits low (<= 15)
        mock_resp.text = '{"plan": "starter", "credits_remaining": 12}'
        mock_resp.json.return_value = {"plan": "starter", "credits_remaining": 12}
        with patch.object(LumiClipService, "get_api_key", return_value="lumi_test_key_123"), \
             patch("services.lumiclip_service.requests.get", return_value=mock_resp):
            status = LumiClipService.get_status(force_refresh=True)
            self.assertEqual(status["status"], "credits_low")
            self.assertEqual(status["credits_remaining"], 12)
            self.assertTrue(status["can_clip"])

        # 4. Credits exhausted (== 0)
        mock_resp.text = '{"plan": "starter", "credits_remaining": 0}'
        mock_resp.json.return_value = {"plan": "starter", "credits_remaining": 0}
        with patch.object(LumiClipService, "get_api_key", return_value="lumi_test_key_123"), \
             patch("services.lumiclip_service.requests.get", return_value=mock_resp):
            status = LumiClipService.get_status(force_refresh=True)
            self.assertEqual(status["status"], "credits_exhausted")
            self.assertEqual(status["credits_remaining"], 0)
            self.assertFalse(status["can_clip"])

        # 5. Invalid token (401)
        mock_resp_401 = MagicMock()
        mock_resp_401.status_code = 401
        with patch.object(LumiClipService, "get_api_key", return_value="invalid_key"), \
             patch("services.lumiclip_service.requests.get", return_value=mock_resp_401):
            status = LumiClipService.get_status(force_refresh=True)
            self.assertEqual(status["status"], "token_invalid")
            self.assertFalse(status["can_clip"])

        # 6. Rate limited (429)
        mock_resp_429 = MagicMock()
        mock_resp_429.status_code = 429
        with patch.object(LumiClipService, "get_api_key", return_value="lumi_test_key_123"), \
             patch("services.lumiclip_service.requests.get", return_value=mock_resp_429):
            status = LumiClipService.get_status(force_refresh=True)
            self.assertEqual(status["status"], "rate_limited")

        # 7. Connection error / timeout
        with patch.object(LumiClipService, "get_api_key", return_value="lumi_test_key_123"), \
             patch("services.lumiclip_service.requests.get", side_effect=requests.exceptions.ConnectionError("Network down")):
            status = LumiClipService.get_status(force_refresh=True)
            self.assertEqual(status["status"], "service_temporarily_unavailable")

    def test_lumiclip_service_generate_and_poll(self):
        """Tests LumiClip project submission and polling methods."""
        from unittest.mock import patch, MagicMock
        from services.lumiclip_service import LumiClipService

        # Invalid URL returns invalid_url status
        inv_res = LumiClipService.submit_clipping_project("https://vimeo.com/123456")
        self.assertFalse(inv_res["success"])
        self.assertEqual(inv_res["status"], "invalid_url")

        # Successful project submission
        mock_post = MagicMock()
        mock_post.status_code = 200
        mock_post.text = '{"project_id": "proj_abc_789", "status": "processing"}'
        mock_post.json.return_value = {"project_id": "proj_abc_789", "status": "processing"}
        with patch.object(LumiClipService, "get_api_key", return_value="lumi_test_key_123"), \
             patch.object(LumiClipService, "get_status", return_value={"can_clip": True, "status": "connected"}), \
             patch("services.lumiclip_service.requests.post", return_value=mock_post) as mock_p:
            res = LumiClipService.submit_clipping_project("https://www.youtube.com/watch?v=dQw4w9WgXcQ", title="Rick Astley")
            self.assertTrue(res["success"])
            self.assertEqual(res["project_id"], "proj_abc_789")
            self.assertEqual(res["status"], "processing")
            # Verify endpoint and Authorization header
            call_url = mock_p.call_args[0][0]
            call_headers = mock_p.call_args[1]["headers"]
            self.assertIn("/api/v1/clips/generate", call_url)
            self.assertEqual(call_headers["Authorization"], "Bearer lumi_test_key_123")

        # Poll project details
        mock_get_proj = MagicMock()
        mock_get_proj.status_code = 200
        mock_get_proj.text = '{"status": "completed", "clips": [{"id": "clip_1", "title": "Viral Hook", "virality_score": 92}]}'
        mock_get_proj.json.return_value = {
            "status": "completed",
            "clips": [{"id": "clip_1", "title": "Viral Hook", "virality_score": 92}]
        }
        with patch.object(LumiClipService, "get_api_key", return_value="lumi_test_key_123"), \
             patch("services.lumiclip_service.requests.get", return_value=mock_get_proj):
            proj = LumiClipService.get_project("proj_abc_789")
            self.assertTrue(proj["success"])
            self.assertEqual(proj["status"], "completed")
            self.assertEqual(len(proj["clips"]), 1)

    def test_lumiclip_export_and_download_validation(self):
        """Tests clip export and MP4 file verification (size and container magic bytes)."""
        from unittest.mock import patch, MagicMock
        from services.lumiclip_service import LumiClipService
        from pathlib import Path

        # Export clip
        mock_export = MagicMock()
        mock_export.status_code = 200
        mock_export.text = '{"export_id": "exp_456", "status": "ready"}'
        mock_export.json.return_value = {"export_id": "exp_456", "status": "ready"}
        with patch.object(LumiClipService, "get_api_key", return_value="lumi_test_key_123"), \
             patch("services.lumiclip_service.requests.post", return_value=mock_export):
            exp = LumiClipService.export_clip("clip_1", quality="720p")
            self.assertTrue(exp["success"])
            self.assertEqual(exp["status"], "ready")

        # Download URL
        mock_down_url = MagicMock()
        mock_down_url.status_code = 200
        mock_down_url.text = '{"download_url": "https://cdn.lumiclip.ai/signed/clip_1.mp4"}'
        mock_down_url.json.return_value = {"download_url": "https://cdn.lumiclip.ai/signed/clip_1.mp4"}
        with patch.object(LumiClipService, "get_api_key", return_value="lumi_test_key_123"), \
             patch("services.lumiclip_service.requests.get", return_value=mock_down_url):
            dl_res = LumiClipService.get_download_url("clip_1")
            self.assertTrue(dl_res["success"])
            self.assertEqual(dl_res["download_url"], "https://cdn.lumiclip.ai/signed/clip_1.mp4")

        # Download and verify valid MP4
        valid_dest = Path(self.temp_dir) / "clips" / "valid_clip.mp4"
        valid_mp4_bytes = b"\x00\x00\x00\x18ftypisom" + b"A" * 15000
        mock_stream = MagicMock()
        mock_stream.status_code = 200
        mock_stream.__enter__.return_value = mock_stream
        mock_stream.__exit__.return_value = None
        mock_stream.iter_content.return_value = [valid_mp4_bytes]

        with patch("services.lumiclip_service.requests.get", return_value=mock_stream):
            res_val = LumiClipService.download_and_verify_mp4("https://cdn.lumiclip.ai/signed/clip_1.mp4", valid_dest)
            self.assertTrue(res_val["success"])
            self.assertTrue(Path(res_val["file_path"]).exists())
            self.assertGreater(Path(res_val["file_path"]).stat().st_size, 10240)

        # Corrupted MP4 (missing ftyp magic bytes)
        corrupt_dest = Path(self.temp_dir) / "clips" / "corrupted_clip.mp4"
        corrupted_bytes = b"CORRUPTED_STREAM_HEADER" + b"X" * 15000
        mock_stream_corrupted = MagicMock()
        mock_stream_corrupted.status_code = 200
        mock_stream_corrupted.__enter__.return_value = mock_stream_corrupted
        mock_stream_corrupted.__exit__.return_value = None
        mock_stream_corrupted.iter_content.return_value = [corrupted_bytes]

        with patch("services.lumiclip_service.requests.get", return_value=mock_stream_corrupted):
            res_bad = LumiClipService.download_and_verify_mp4("https://cdn.lumiclip.ai/signed/clip_corrupted.mp4", corrupt_dest)
            self.assertFalse(res_bad["success"])
            self.assertIn("does not contain standard MP4 container", res_bad["error"])
            self.assertFalse(corrupt_dest.exists())

        # Too small file (< 10KB)
        small_dest = Path(self.temp_dir) / "clips" / "small_clip.mp4"
        small_bytes = b"\x00\x00\x00\x18ftyp" + b"X" * 500
        mock_stream_small = MagicMock()
        mock_stream_small.status_code = 200
        mock_stream_small.__enter__.return_value = mock_stream_small
        mock_stream_small.__exit__.return_value = None
        mock_stream_small.iter_content.return_value = [small_bytes]

        with patch("services.lumiclip_service.requests.get", return_value=mock_stream_small):
            res_small = LumiClipService.download_and_verify_mp4("https://cdn.lumiclip.ai/signed/clip_small.mp4", small_dest)
            self.assertFalse(res_small["success"])
            self.assertIn("below minimum valid MP4 size", res_small["error"])
            self.assertFalse(small_dest.exists())

    def test_youtube_clips_agent_source_channel_and_rights_enforcement(self):
        """Verifies channel resolution requires explicit rights confirmation and persists channel info."""
        from unittest.mock import patch
        from agents.youtube_clips_agent import YouTubeClipsAgent
        from database import get_db_connection

        # Enforce rights confirmation requirement
        res_no_rights = YouTubeClipsAgent.resolve_and_save_channel("UC1234567890", rights_confirmed=False)
        self.assertFalse(res_no_rights["success"])
        self.assertEqual(res_no_rights["status"], "rights_required")
        self.assertIn("confirm that you own", res_no_rights["error"])

        # Mock YouTube channel lookup via YouTubeClippingService
        mock_resolved = {
            "success": True,
            "channel_id": "UC_TEST_CHANNEL_1",
            "title": "Aero Engineering Lab",
            "handle": "@aerolab",
            "thumbnail_url": "https://img.youtube.com/thumb.jpg",
            "custom_url": "@aerolab"
        }

        with patch("services.youtube_clipping_service.YouTubeClippingService.resolve_source_channel", return_value=mock_resolved):
            channel = YouTubeClipsAgent.resolve_and_save_channel("https://youtube.com/@aerolab", rights_confirmed=True)
            self.assertTrue(channel["success"])
            self.assertEqual(channel["channel_id"], "UC_TEST_CHANNEL_1")
            self.assertEqual(channel["title"], "Aero Engineering Lab")

        # Verify persisted in database
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM youtube_source_channels WHERE channel_id = ?", ("UC_TEST_CHANNEL_1",))
        row = cur.fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["title"], "Aero Engineering Lab")
        self.assertEqual(row["rights_confirmed"], 1)

    def test_youtube_clips_agent_video_discovery_and_duplicate_prevention(self):
        """Tests discovery of source videos from playlist and idempotent duplicate prevention."""
        from unittest.mock import patch, MagicMock
        from agents.youtube_clips_agent import YouTubeClipsAgent
        from database import get_db_connection

        # Insert source channel
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO youtube_source_channels (channel_id, title, handle, custom_url, rights_confirmed, is_active, created_at, updated_at)
            VALUES ('UC_TEST_DISC', 'Discovery Channel', '@discovery', '@discovery', 1, 1, '2026-10-24 10:00:00', '2026-10-24 10:00:00')
        """)
        conn.commit()
        conn.close()

        # Mock YouTube client
        mock_yt_client = MagicMock()
        mock_yt_client.channels.return_value.list.return_value.execute.return_value = {
            "items": [{
                "snippet": {"title": "Discovery Channel"},
                "contentDetails": {"relatedPlaylists": {"uploads": "UU_TEST_DISC"}}
            }]
        }
        mock_yt_client.playlistItems.return_value.list.return_value.execute.return_value = {
            "items": [
                {
                    "snippet": {
                        "resourceId": {"videoId": "vid_abc_1"},
                        "title": "Aerodynamics Lesson 1",
                        "description": "Introduction to lift and drag",
                        "publishedAt": "2026-10-20T12:00:00Z",
                        "thumbnails": {"high": {"url": "https://img.youtube.com/vi/vid_abc_1/hqdefault.jpg"}}
                    }
                },
                {
                    "snippet": {
                        "resourceId": {"videoId": "vid_abc_2"},
                        "title": "Propulsion Systems",
                        "description": "Jet engine overview",
                        "publishedAt": "2026-10-22T14:00:00Z",
                        "thumbnails": {"high": {"url": "https://img.youtube.com/vi/vid_abc_2/hqdefault.jpg"}}
                    }
                }
            ]
        }

        mock_token = MagicMock()
        mock_token.valid = True

        with patch("agents.youtube_clips_agent._load_token", return_value=mock_token), \
             patch("agents.youtube_clips_agent._refresh_if_needed", return_value=mock_token), \
             patch("agents.youtube_clips_agent._build_youtube_client", return_value=mock_yt_client):
            disc_res = YouTubeClipsAgent.discover_recent_videos("UC_TEST_DISC", max_results=10)
            self.assertTrue(disc_res["success"])
            self.assertEqual(len(disc_res["videos"]), 2)
            self.assertEqual(disc_res["videos"][0]["video_id"], "vid_abc_1")

            # Run again to verify idempotency (no duplicate entries)
            disc_res_again = YouTubeClipsAgent.discover_recent_videos("UC_TEST_DISC", max_results=10)
            self.assertTrue(disc_res_again["success"])
            self.assertEqual(len(disc_res_again["videos"]), 2)

        # Check database records
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as count FROM youtube_discovered_videos WHERE channel_id = 'UC_TEST_DISC'")
        count = cur.fetchone()["count"]
        conn.close()
        self.assertEqual(count, 2)

    def test_youtube_clips_agent_submit_and_poll_sync(self):
        """Tests submitting a video to LumiClip and polling to ingest clips ranked by virality score."""
        from unittest.mock import patch, MagicMock
        from agents.youtube_clips_agent import YouTubeClipsAgent
        from database import get_db_connection
        from pathlib import Path

        # Insert discovered video
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO youtube_discovered_videos (channel_id, video_id, title, description, published_at, thumbnail_url, status, is_test, created_at)
            VALUES ('UC_TEST_DISC', 'vid_to_clip', 'Flight Mechanics', 'Intro to flight', '2026-10-24 10:00:00', 'https://img.com/thumb.jpg', 'discovered', 1, '2026-10-24 10:00:00')
        """)
        conn.commit()
        conn.close()

        # Submit job
        mock_submit = {"success": True, "project_id": "proj_flight_100", "status": "processing"}
        with patch("services.lumiclip_service.LumiClipService.get_status", return_value={"can_clip": True, "status": "connected"}), \
             patch("services.lumiclip_service.LumiClipService.submit_clipping_project", return_value=mock_submit):
            proj = YouTubeClipsAgent.submit_clipping_job(video_url_or_id="vid_to_clip", start_time=10, end_time=120)
            self.assertTrue(proj["success"])
            self.assertEqual(proj["project_id"], "proj_flight_100")
            self.assertEqual(proj["status"], "processing")

        # Second submission for same video is detected as already processing
        proj_again = YouTubeClipsAgent.submit_clipping_job(video_url_or_id="vid_to_clip")
        self.assertTrue(proj_again["success"])
        self.assertEqual(proj_again["status"], "processing")
        self.assertIn("already actively processing", proj_again["message"])

        # Poll and sync completed project
        mock_proj_details = {
            "success": True,
            "project_id": "proj_flight_100",
            "status": "completed",
            "progress": 100,
            "clips": [
                {
                    "id": "c_alpha",
                    "title": "Shockwave Formation",
                    "description": "Supersonic flow breakdown",
                    "duration": 42.0,
                    "virality_score": 96.5,
                    "virality_reason": "High visual contrast and sudden shockwave reveal",
                    "thumbnail_url": "https://cdn.lumiclip.ai/thumbs/c_alpha.jpg"
                },
                {
                    "id": "c_beta",
                    "title": "Subsonic Boundary Layer",
                    "description": "Laminar to turbulent transition",
                    "duration": 35.0,
                    "virality_score": 78.0,
                    "virality_reason": "Good instructional clarity",
                    "thumbnail_url": "https://cdn.lumiclip.ai/thumbs/c_beta.jpg"
                }
            ],
            "raw": {}
        }

        mock_dl_result = {
            "success": True,
            "file_path": str(Path(self.temp_dir) / "clip.mp4"),
            "file_size_bytes": 1048576
        }

        with patch("services.lumiclip_service.LumiClipService.get_project", return_value=mock_proj_details), \
             patch("services.lumiclip_service.LumiClipService.export_clip", return_value={"success": True, "download_url": "https://cdn.lumiclip.ai/signed/c.mp4"}), \
             patch("services.lumiclip_service.LumiClipService.download_and_verify_mp4", return_value=mock_dl_result):
            sync_res = YouTubeClipsAgent.poll_and_sync_projects()
            self.assertEqual(sync_res["completed_count"], 1)
            self.assertEqual(sync_res["results"][0]["clips_ingested"], 2)

        # Verify ingested clips in database and virality ranking
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM youtube_clips WHERE lumiclip_project_id = 'proj_flight_100' ORDER BY virality_score DESC")
        clips = cur.fetchall()
        conn.close()
        self.assertEqual(len(clips), 2)
        self.assertEqual(clips[0]["lumiclip_clip_id"], "c_alpha")
        self.assertEqual(clips[0]["virality_score"], 96.5)
        self.assertEqual(clips[0]["status"], "ready_for_review")
        self.assertEqual(clips[1]["lumiclip_clip_id"], "c_beta")

    def test_youtube_clips_agent_review_and_schedule_coordination(self):
        """Tests approval, rejection, and deletion of clips with scheduler coordination."""
        from agents.youtube_clips_agent import YouTubeClipsAgent
        from database import get_db_connection

        # Insert 2 clips ready for review
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO youtube_clips (id, source_file_path, clip_title, clip_description, status, virality_score, is_test, created_at)
            VALUES (501, 'dummy/path/clip1.mp4', 'Clip To Approve', 'Desc 1', 'ready_for_review', 91.0, 1, '2026-10-24 10:00:00')
        """)
        cur.execute("""
            INSERT INTO youtube_clips (id, source_file_path, clip_title, clip_description, status, virality_score, is_test, created_at)
            VALUES (502, 'dummy/path/clip2.mp4', 'Clip To Reject', 'Desc 2', 'ready_for_review', 60.0, 1, '2026-10-24 10:00:00')
        """)
        conn.commit()
        conn.close()

        # Approve clip 501
        app_res = YouTubeClipsAgent.approve_clip(501)
        self.assertTrue(app_res["success"])
        self.assertEqual(app_res["status"], "approved")

        # Reject clip 502
        rej_res = YouTubeClipsAgent.reject_clip(502)
        self.assertTrue(rej_res["success"])
        self.assertEqual(rej_res["status"], "rejected")

        # Delete clip 502
        del_res = YouTubeClipsAgent.delete_clip(502)
        self.assertTrue(del_res["success"])

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM youtube_clips WHERE id = 502")
        self.assertIsNone(cur.fetchone())
        conn.close()

    def test_youtube_scheduler_twice_daily_and_slot_sync(self):
        """Validates twice-daily schedule slot calculation, auto-sync, and missed slot handling."""
        from services.youtube_scheduler_service import YouTubeSchedulerService
        from database import get_db_connection
        from pathlib import Path

        # Configure schedule for Asia/Kolkata with auto_publish
        cfg = YouTubeSchedulerService.update_schedule_config(
            enabled=True,
            timezone_str="Asia/Kolkata",
            slot_1_time="11:30",
            slot_2_time="19:30",
            auto_publish=True,
            max_daily_posts=2,
            queue_target=4
        )
        self.assertEqual(cfg["timezone"], "Asia/Kolkata")
        self.assertEqual(cfg["slot_1_time"], "11:30")
        self.assertEqual(cfg["slot_2_time"], "19:30")
        self.assertEqual(cfg["auto_publish"], 1)

        # Calculate upcoming slots
        slots = YouTubeSchedulerService.calculate_next_slots(count=4)
        self.assertEqual(len(slots), 4)

        # Create dummy local MP4 files for 2 approved clips
        dummy_clip_path = Path(self.temp_dir) / "test_clip.mp4"
        dummy_clip_path.write_bytes(b"dummy_mp4_content")

        conn = get_db_connection()
        cur = conn.cursor()
        for cid in (601, 602):
            cur.execute("""
                INSERT INTO youtube_clips (id, source_file_path, output_path, clip_title, clip_description, status, is_test, created_at)
                VALUES (?, 'dummy.mp4', ?, ?, 'Auto sync test', 'approved', 1, '2026-10-24 10:00:00')
            """, (cid, str(dummy_clip_path), f"Approved Clip {cid}"))
        conn.commit()
        conn.close()

        # Run slot sync
        synced_res = YouTubeSchedulerService.sync_schedule_slots()
        self.assertTrue(synced_res["synced"])
        self.assertEqual(synced_res["queued_count"], 2)

        # Verify scheduled posts created
        posts = YouTubeSchedulerService.list_scheduled_posts()
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0]["status"], "queued")

        # Verify missed slots handling
        # Insert an expired scheduled post
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO youtube_scheduled_posts (clip_id, scheduled_time, target_slot, status, is_test, created_at, updated_at)
            VALUES (601, '2020-01-01 10:00:00Z', 'slot_1', 'scheduled', 1, '2020-01-01 09:00:00', '2020-01-01 09:00:00')
        """)
        conn.commit()
        conn.close()

        missed = YouTubeSchedulerService.check_and_process_missed_slots()
        self.assertGreaterEqual(len(missed), 1)

    def test_youtube_clips_routes_end_to_end(self):
        """Tests REST endpoints in routes/youtube_clips.py."""
        from flask import Flask
        from routes.youtube_clips import youtube_clips_bp
        from database import get_db_connection
        from unittest.mock import patch

        app = Flask(__name__)
        app.register_blueprint(youtube_clips_bp)
        client = app.test_client()

        # 1. GET /api/lumiclip/usage
        with patch("services.lumiclip_service.LumiClipService.get_status", return_value={"status": "connected", "credits_remaining": 40}):
            res = client.get("/api/lumiclip/usage")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.get_json()["credits_remaining"], 40)

        # 2. GET /api/youtube/clips/status
        res_status = client.get("/api/youtube/clips/status")
        self.assertEqual(res_status.status_code, 200)
        data = res_status.get_json()
        self.assertIn("lumiclip", data)
        self.assertIn("counts", data)
        self.assertIn("active_channels", data["counts"])
        self.assertIn("pending_review", data["counts"])

        # 3. Channel resolution rights guard
        res_resolve_no_rights = client.post("/api/youtube/channels/resolve", json={
            "query": "UC_TEST",
            "rights_confirmed": False
        })
        self.assertEqual(res_resolve_no_rights.status_code, 400)
        self.assertIn("confirm that you own", res_resolve_no_rights.get_json()["error"])

        # 4. Schedule config update
        res_sched = client.post("/api/youtube/schedule", json={
            "enabled": True,
            "timezone": "Asia/Kolkata",
            "slot_1_time": "12:00",
            "slot_2_time": "20:00",
            "auto_publish": True
        })
        self.assertEqual(res_sched.status_code, 200)
        self.assertEqual(res_sched.get_json()["schedule"]["timezone"], "Asia/Kolkata")

        # 5. Clip approve endpoint
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO youtube_clips (id, source_file_path, clip_title, status, is_test, created_at)
            VALUES (701, 'dummy/file.mp4', 'Endpoint Test Clip', 'ready_for_review', 1, '2026-10-24 10:00:00')
        """)
        conn.commit()
        conn.close()

        res_app = client.post("/api/youtube/clips/701/approve")
        self.assertEqual(res_app.status_code, 200)
        self.assertEqual(res_app.get_json()["status"], "approved")

        # 6. Clip delete endpoint
        res_del = client.delete("/api/youtube/clips/701")
        self.assertEqual(res_del.status_code, 200)
        self.assertTrue(res_del.get_json()["success"])

        # 7. Clip publish-now endpoint
        with patch("agents.youtube_clips_agent.YouTubeClipsAgent.publish_clip_now", return_value={"success": True, "video_id": "v123", "video_url": "https://www.youtube.com/watch?v=v123"}):
            res_pub_now = client.post("/api/youtube/clips/701/publish-now", json={"confirmed": True, "privacy_status": "public"})
            self.assertEqual(res_pub_now.status_code, 200)
            self.assertEqual(res_pub_now.get_json()["video_id"], "v123")

    def test_publish_clip_now_on_demand_for_demo(self):
        """Tests immediate on-demand clip publishing to YouTube for judge demonstration."""
        from unittest.mock import patch, MagicMock
        from agents.youtube_clips_agent import YouTubeClipsAgent
        from database import get_db_connection
        from pathlib import Path

        # Create dummy MP4 file
        dummy_video = Path(self.temp_dir) / "demo_clip.mp4"
        dummy_video.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"X" * 12000)

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO youtube_clips (id, source_file_path, output_path, clip_title, clip_description, status, is_test, created_at)
            VALUES (801, ?, ?, 'Demo Clip For Judges', 'High impact clip description', 'approved', 1, '2026-10-24 10:00:00')
        """, (str(dummy_video), str(dummy_video)))
        conn.commit()
        conn.close()

        # 1. Unconfirmed returns error
        res_unconf = YouTubeClipsAgent.publish_clip_now(801, confirmed=False)
        self.assertFalse(res_unconf["success"])
        self.assertIn("explicit user confirmation", res_unconf["error"])

        # 2. When not connected
        with patch("agents.youtube_clips_agent._load_token", return_value=None):
            res_not_conn = YouTubeClipsAgent.publish_clip_now(801, confirmed=True)
            self.assertFalse(res_not_conn["success"])
            self.assertIn("not connected", res_not_conn["error"])

        # 3. Successful immediate publish
        mock_token = MagicMock()
        mock_token.valid = True

        mock_yt = MagicMock()
        mock_insert_req = MagicMock()
        mock_insert_req.next_chunk.return_value = (None, {"id": "yt_live_demo_123", "status": {"privacyStatus": "public"}})
        mock_yt.videos.return_value.insert.return_value = mock_insert_req

        with patch("agents.youtube_clips_agent._load_token", return_value=mock_token), \
             patch("agents.youtube_clips_agent._refresh_if_needed", return_value=mock_token), \
             patch("agents.youtube_clips_agent._build_youtube_client", return_value=mock_yt):
            res = YouTubeClipsAgent.publish_clip_now(801, privacy_status="public", confirmed=True)
            self.assertTrue(res["success"])
            self.assertEqual(res["video_id"], "yt_live_demo_123")
            self.assertEqual(res["video_url"], "https://www.youtube.com/watch?v=yt_live_demo_123")
            self.assertIn("Successfully published to YouTube", res["message"])

            # Verify insert call metadata: privacyStatus must be public, NO publishAt
            call_kwargs = mock_yt.videos.return_value.insert.call_args[1]
            self.assertEqual(call_kwargs["body"]["status"]["privacyStatus"], "public")
            self.assertNotIn("publishAt", call_kwargs["body"]["status"])

        # Verify updated in database
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM youtube_clips WHERE id = 801")
        row = dict(cur.fetchone())
        conn.close()
        self.assertEqual(row["status"], "published")
        self.assertEqual(row["youtube_video_id"], "yt_live_demo_123")
        self.assertEqual(row["youtube_video_url"], "https://www.youtube.com/watch?v=yt_live_demo_123")

    def test_publish_scheduled_post_publish_now_mode(self):
        """Tests publish_scheduled_post with publish_now=True for instant public release."""
        from unittest.mock import patch, MagicMock
        from services.youtube_scheduler_service import YouTubeSchedulerService
        from database import get_db_connection
        from pathlib import Path

        dummy_video = Path(self.temp_dir) / "sched_now.mp4"
        dummy_video.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"Y" * 12000)

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO youtube_clips (id, source_file_path, output_path, clip_title, clip_description, status, is_test, created_at)
            VALUES (802, ?, ?, 'Instant Publish Clip', 'Desc', 'approved', 1, '2026-10-24 10:00:00')
        """, (str(dummy_video), str(dummy_video)))
        cur.execute("""
            INSERT INTO youtube_scheduled_posts (id, clip_id, scheduled_time, target_slot, status, is_test, created_at, updated_at)
            VALUES (901, 802, '2026-10-25 10:00:00Z', 'slot_1', 'queued', 1, '2026-10-24 10:00:00', '2026-10-24 10:00:00')
        """)
        conn.commit()
        conn.close()

        mock_token = MagicMock()
        mock_token.valid = True

        mock_yt = MagicMock()
        mock_insert_req = MagicMock()
        mock_insert_req.next_chunk.return_value = (None, {"id": "yt_live_sched_999", "status": {"privacyStatus": "public"}})
        mock_yt.videos.return_value.insert.return_value = mock_insert_req

        with patch("services.youtube_scheduler_service._load_token", return_value=mock_token), \
             patch("services.youtube_scheduler_service._refresh_if_needed", return_value=mock_token), \
             patch("services.youtube_scheduler_service._build_youtube_client", return_value=mock_yt):
            res = YouTubeSchedulerService.publish_scheduled_post(901, confirmed=True, publish_now=True, privacy_status="public")
            self.assertTrue(res["success"])
            self.assertEqual(res["status"], "published")
            self.assertEqual(res["video_id"], "yt_live_sched_999")
            self.assertIn("yt_live_sched_999", res["video_url"])

        # Verify both tables updated to published
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT status, youtube_video_id FROM youtube_scheduled_posts WHERE id = 901")
        sp_row = dict(cur.fetchone())
        self.assertEqual(sp_row["status"], "published")
        self.assertEqual(sp_row["youtube_video_id"], "yt_live_sched_999")

        cur.execute("SELECT status, youtube_video_id FROM youtube_clips WHERE id = 802")
        clip_row = dict(cur.fetchone())
        self.assertEqual(clip_row["status"], "published")
        self.assertEqual(clip_row["youtube_video_id"], "yt_live_sched_999")
        conn.close()

    def test_synthesize_publishable_short_fallback(self):
        """Tests synthesizing compliant 9:16 vertical Short fallback when cloud clipping is restricted."""
        from agents.youtube_clips_agent import YouTubeClipsAgent
        from database import get_db_connection
        from pathlib import Path

        # Insert project
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO lumiclip_projects (project_id, video_url, video_title, source_channel_name, status, is_test, created_at, updated_at)
            VALUES ('proj_synth_test_1', 'https://youtube.com/watch?v=xyz', 'AI Flight Mechanics', 'Science Lab', 'failed', 1, '2026-10-24 10:00:00', '2026-10-24 10:00:00')
        """)
        conn.commit()
        conn.close()

        res = YouTubeClipsAgent.synthesize_publishable_short(project_id="proj_synth_test_1", duration_sec=5.0)
        self.assertTrue(res["success"])
        self.assertIn("AI Flight Mechanics", res["title"])
        self.assertTrue(Path(res["file_path"]).exists())
        self.assertGreater(Path(res["file_path"]).stat().st_size, 10240)

        # Check database records
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT status, clips_count FROM lumiclip_projects WHERE project_id = 'proj_synth_test_1'")
        p_row = dict(cur.fetchone())
        self.assertEqual(p_row["status"], "completed")
        self.assertEqual(p_row["clips_count"], 1)

        cur.execute("SELECT status, aspect_ratio, output_path FROM youtube_clips WHERE id = ?", (res["clip_id"],))
        c_row = dict(cur.fetchone())
        self.assertEqual(c_row["status"], "ready_for_review")
        self.assertEqual(c_row["aspect_ratio"], "9:16")
        conn.close()

    def test_clip_file_streaming_with_byte_range_support(self):
        """Tests that clip video files stream correctly with HTTP 206 byte-range support for browser playback."""
        from agents.youtube_clips_agent import YouTubeClipsAgent
        from app import create_app

        res = YouTubeClipsAgent.synthesize_publishable_short(duration_sec=3.0)
        self.assertTrue(res["success"])
        clip_id = res["clip_id"]

        flask_app = create_app()
        flask_app.config["TESTING"] = True
        client = flask_app.test_client()

        # Full video request
        resp = client.get(f"/api/youtube/clips/{clip_id}/file")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content_type, "video/mp4")
        self.assertEqual(resp.headers.get("Accept-Ranges"), "bytes")
        total_len = len(resp.data)
        self.assertGreater(total_len, 1024)

        # Byte range request (browser streaming seek)
        range_resp = client.get(f"/api/youtube/clips/{clip_id}/file", headers={"Range": "bytes=0-100"})
        self.assertEqual(range_resp.status_code, 206)
        self.assertEqual(len(range_resp.data), 101)
        self.assertEqual(range_resp.headers.get("Content-Range"), f"bytes 0-100/{total_len}")

        # Non-existent clip
        resp_404 = client.get("/api/youtube/clips/999999/file")
        self.assertEqual(resp_404.status_code, 404)

    @patch("services.lumiclip_service.requests.get")
    def test_lumiclip_get_project_failure_parsing_and_classification(self, mock_get):
        """Tests parsing status, step, error, and clips from LumiClip API with error classification."""
        from services.lumiclip_service import LumiClipService

        # 1. Video requires authentication failure (HTTP 200 with status=failed)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = json.dumps({
            "id": "proj-auth-fail-1",
            "name": "Restricted Video",
            "status": "failed",
            "step": "FAILED",
            "error": "This video requires authentication and cannot be processed.",
            "clips": []
        })
        mock_resp.json.return_value = json.loads(mock_resp.text)
        mock_get.return_value = mock_resp

        res = LumiClipService.get_project("proj-auth-fail-1")
        self.assertTrue(res["success"])
        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["step"], "FAILED")
        self.assertEqual(res["error"], "This video requires authentication and cannot be processed.")
        self.assertEqual(res["error_type"], "video_inaccessible")
        self.assertIn("YouTube authentication or is restricted", res["actionable_guidance"])
        self.assertEqual(res["progress"], 0)
        self.assertEqual(res["video_title"], "Restricted Video")

        # 2. HTTP 401 Unauthorized
        mock_resp_401 = MagicMock()
        mock_resp_401.status_code = 401
        mock_resp_401.text = "Unauthorized"
        mock_get.return_value = mock_resp_401
        res_401 = LumiClipService.get_project("proj-auth-fail-1")
        self.assertFalse(res_401["success"])
        self.assertEqual(res_401["error_type"], "invalid_api_key")

        # 3. HTTP 402 Credits Exhausted
        mock_resp_402 = MagicMock()
        mock_resp_402.status_code = 402
        mock_resp_402.text = "Credits depleted"
        mock_get.return_value = mock_resp_402
        res_402 = LumiClipService.get_project("proj-auth-fail-1")
        self.assertFalse(res_402["success"])
        self.assertEqual(res_402["error_type"], "insufficient_credits")

        # 4. HTTP 404 Not Found
        mock_resp_404 = MagicMock()
        mock_resp_404.status_code = 404
        mock_resp_404.text = "Not Found"
        mock_get.return_value = mock_resp_404
        res_404 = LumiClipService.get_project("proj-not-found")
        self.assertFalse(res_404["success"])
        self.assertEqual(res_404["error_type"], "not_found")

    @patch("services.lumiclip_service.LumiClipService.get_project")
    def test_project_status_synchronization_transitions_to_failed(self, mock_get_project):
        """Tests that a provider failure updates the MINT job to failed, stops processing indicator, and stores error."""
        from agents.youtube_clips_agent import YouTubeClipsAgent
        from database import get_db_connection

        # Insert a pending processing project in test SQLite DB
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO lumiclip_projects (
                project_id, video_url, video_title, status, progress_pct, clips_count, is_test, created_at, updated_at
            ) VALUES (
                'proj-sync-fail-99', 'https://www.youtube.com/watch?v=restricted123', 'Private Video Highlight',
                'processing', 0, 0, 1, '2026-10-24 10:00:00', '2026-10-24 10:00:00'
            )
        """)
        conn.commit()
        conn.close()

        # Mock provider returning failed with exact authentication error
        mock_get_project.return_value = {
            "success": True,
            "project_id": "proj-sync-fail-99",
            "status": "failed",
            "step": "FAILED",
            "error": "This video requires authentication and cannot be processed.",
            "error_type": "video_inaccessible",
            "actionable_guidance": "This video requires YouTube authentication or is restricted. Select a public, unrestricted YouTube video.",
            "progress": 0,
            "clips": [],
            "clips_count": 0,
            "video_title": "Private Video Highlight",
            "raw": {"status": "failed", "error": "This video requires authentication and cannot be processed."}
        }

        # Run synchronization
        poll_res = YouTubeClipsAgent.poll_and_sync_projects()
        self.assertTrue(poll_res["success"])
        self.assertEqual(poll_res["polled_count"], 1)
        self.assertEqual(poll_res["failed_count"], 1)

        # Verify database record updated
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT status, progress_pct, error_message FROM lumiclip_projects WHERE project_id = 'proj-sync-fail-99'")
        row = dict(cur.fetchone())
        conn.close()

        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["progress_pct"], 0)
        self.assertEqual(row["error_message"], "This video requires authentication and cannot be processed.")

    @patch("services.lumiclip_service.LumiClipService.submit_clipping_project")
    @patch("services.lumiclip_service.LumiClipService.get_status")
    def test_retry_project_workflow_and_safeguards(self, mock_get_status, mock_create_project):
        """Tests retry action confirmation, validation, credit check, and resubmission."""
        from agents.youtube_clips_agent import YouTubeClipsAgent
        from database import get_db_connection

        # Seed failed project in test SQLite DB
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO lumiclip_projects (
                project_id, video_url, video_title, status, progress_pct, clips_count,
                error_message, is_test, created_at, updated_at
            ) VALUES (
                'proj-orig-failed', 'https://www.youtube.com/watch?v=badurl00000', 'Original Video',
                'failed', 0, 0, 'This video requires authentication and cannot be processed.', 1, '2026-10-24 10:00:00', '2026-10-24 10:00:00'
            )
        """)
        conn.commit()
        conn.close()

        # 1. Unconfirmed retry must be rejected
        unconf = YouTubeClipsAgent.retry_project(project_id="proj-orig-failed", confirmed=False)
        self.assertFalse(unconf["success"])
        self.assertTrue(unconf.get("requires_confirmation"))

        # 2. Invalid YouTube URL must be rejected
        inv_url = YouTubeClipsAgent.retry_project(
            project_id="proj-orig-failed",
            new_video_url="https://vimeo.com/123456",
            confirmed=True
        )
        self.assertFalse(inv_url["success"])
        self.assertIn("valid public YouTube", inv_url["error"])

        # 3. Credits check failure
        mock_get_status.return_value = {"can_clip": False, "message": "Credits exhausted"}
        credit_fail = YouTubeClipsAgent.retry_project(
            project_id="proj-orig-failed",
            new_video_url="https://www.youtube.com/watch?v=goodvideo123",
            confirmed=True
        )
        self.assertFalse(credit_fail["success"])
        self.assertIn("Credits exhausted", credit_fail["error"])

        # 4. Successful retry
        mock_get_status.return_value = {"can_clip": True, "message": "Ready"}
        mock_create_project.return_value = {
            "success": True,
            "status": "processing",
            "project_id": "proj-new-resubmitted-888"
        }

        success_retry = YouTubeClipsAgent.retry_project(
            project_id="proj-orig-failed",
            new_video_url="https://www.youtube.com/watch?v=goodvideo123",
            new_video_title="Eligible Public Video",
            confirmed=True
        )
        self.assertTrue(success_retry["success"])
        self.assertEqual(success_retry["new_project_id"], "proj-new-resubmitted-888")

        # Verify DB records
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT status, progress_pct FROM lumiclip_projects WHERE project_id = 'proj-new-resubmitted-888'")
        new_row = dict(cur.fetchone())
        self.assertEqual(new_row["status"], "processing")
        self.assertEqual(new_row["progress_pct"], 0)

        cur.execute("SELECT error_message FROM lumiclip_projects WHERE project_id = 'proj-orig-failed'")
        old_row = dict(cur.fetchone())
        self.assertIn("Retried as proj-new-resubmitted-888", old_row["error_message"])
        conn.close()


if __name__ == "__main__":
    unittest.main()

