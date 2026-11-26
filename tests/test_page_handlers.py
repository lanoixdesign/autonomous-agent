"""Regression: every element a page wires at load ($("id").onclick=..., .onchange=...,
.addEventListener) must exist in that page's HTML. A missing element throws at load and
leaves later let-variables uninitialized (WebKit: "Cannot access uninitialized variable")."""
import re

import pytest

from agent.harness_chat import CHAT_PAGE
from agent.harness_connect import CONNECT_PAGE
from agent.harness_dev import DEV_PAGE
from agent.harness_help import HELP_PAGE
from agent.harness_page import PAGE
from agent.harness_settings import SETTINGS_PAGE, WELCOME_PAGE

PAGES = {"chat": CHAT_PAGE, "dashboard": PAGE, "connect": CONNECT_PAGE, "settings": SETTINGS_PAGE,
         "welcome": WELCOME_PAGE, "help": HELP_PAGE, "dev": DEV_PAGE}
WIRED = re.compile(r'^\s*\$\("([\w-]+)"\)\.(?:on\w+\s*=|addEventListener\()', re.M)


@pytest.mark.parametrize("name", sorted(PAGES))
def test_load_time_handlers_target_existing_elements(name):
    html = PAGES[name]
    ids = set(re.findall(r'\bid="([\w-]+)"', html))
    missing = sorted({i for i in WIRED.findall(html) if i not in ids})
    assert not missing, f"{name} page wires missing elements: {missing}"
