# -*- encoding: utf-8 -*-
"""Implements Jobs UI."""
from robottelo.ui.base import Base
from robottelo.ui.locators import locators
from robottelo.ui.navigator import Navigator


class RecurringLogic(Base):
    """Provides the basic functionality for Jobs."""

    def navigate_to_entity(self):
        """Navigate to Jobs entity page"""
        Navigator(self.browser).go_to_recurring_logics()

    def _search_locator(self):
        """Specify locator for Jobs entity search procedure"""
        return locators['recurring_logic.select']

