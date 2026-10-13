"""Hosted dependency maintenance must not silently change the Mac profile."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def pins(path):
    result = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('-r '):
            result.update(pins(path.parent / line[3:]))
            continue
        name, version = line.split('==')
        key = name.lower().replace('_', '-')
        if key in result:
            raise ValueError('Duplicate dependency pin')
        result[key] = version
    return result


class HostedDependencyTests(unittest.TestCase):
    def test_hosted_profile_is_independent_with_only_reviewed_server_changes(self):
        hosted_path = ROOT / 'requirements-hosted.lock'
        self.assertNotIn('-r ', hosted_path.read_text())
        mac = pins(ROOT / 'requirements-security.lock')
        hosted = pins(hosted_path)
        self.assertEqual(set(hosted) - set(mac), {'psycopg', 'psycopg-binary'})
        self.assertEqual(set(mac) - set(hosted), set())
        expected = {'anyio': '4.14.2', 'starlette': '1.3.1', 'python-multipart': '0.0.31'}
        self.assertEqual({name: version for name, version in hosted.items()
                          if name in mac and version != mac[name]}, expected)


if __name__ == '__main__':
    unittest.main()
