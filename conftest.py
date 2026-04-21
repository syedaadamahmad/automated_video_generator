import pytest

# Set asyncio mode to "auto" so async test functions are collected and run
# without requiring @pytest.mark.asyncio on every test or --asyncio-mode=auto
# on the command line. Works with pytest-asyncio 0.21+ and 1.x.
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )
