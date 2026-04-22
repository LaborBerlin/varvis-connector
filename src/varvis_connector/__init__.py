"""
varvis_connector package main module


:author: Markus Konrad <markus.konrad@laborberlin.com>
"""

from importlib.metadata import version

from ._varvis_client import VarvisClient as VarvisClient

__version__ = version("varvis-connector")
