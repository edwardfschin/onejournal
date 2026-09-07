from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = PROJECT_ROOT / "web"


class WebRouteContractTests(unittest.TestCase):
    def test_shared_registry_declares_mode_first_canonical_routes(self) -> None:
        routes = (WEB_ROOT / "lib" / "routes.ts").read_text(encoding="utf-8")

        for route in (
            "/demo",
            "/demo/portfolio",
            "/demo/trades",
            "/demo/journal",
            "/demo/reports",
            "/demo/data",
            "/demo/settings",
            "/local/portfolio",
            "/local/trades",
            "/local/journal",
        ):
            self.assertIn(f"'{route}'", routes)

    def test_canonical_route_entrypoints_exist(self) -> None:
        for relative_path in (
            "app/demo/page.tsx",
            "app/demo/portfolio/page.tsx",
            "app/demo/trades/page.tsx",
            "app/demo/journal/page.tsx",
            "app/demo/reports/page.tsx",
            "app/demo/data/page.tsx",
            "app/demo/settings/page.tsx",
            "app/local/portfolio/page.tsx",
            "app/local/trades/page.tsx",
            "app/local/journal/page.tsx",
        ):
            self.assertTrue((WEB_ROOT / relative_path).is_file(), relative_path)

    def test_page_components_do_not_hard_code_legacy_routes(self) -> None:
        forbidden = (
            'href="/portfolio"',
            'href="/trades"',
            'href="/journal"',
            'href="/reports"',
            'href="/data"',
            'href="/settings"',
            "'/portfolio/local'",
            "'/journal/local'",
        )

        for page_path in (WEB_ROOT / "app").rglob("*.tsx"):
            source = page_path.read_text(encoding="utf-8")
            for legacy_route in forbidden:
                self.assertNotIn(legacy_route, source, f"{page_path}: {legacy_route}")

    def test_legacy_paths_are_centralized_as_redirects(self) -> None:
        next_config = (WEB_ROOT / "next.config.ts").read_text(encoding="utf-8")
        routes = (WEB_ROOT / "lib" / "routes.ts").read_text(encoding="utf-8")

        self.assertIn("LEGACY_ROUTE_REDIRECTS", next_config)
        self.assertIn("async redirects()", next_config)
        self.assertIn("source: '/portfolio/local'", routes)
        self.assertIn("destination: LOCAL_ROUTES.portfolio", routes)
        self.assertIn("source: '/journal/local'", routes)
        self.assertIn("destination: LOCAL_ROUTES.journal", routes)


if __name__ == "__main__":
    unittest.main()
